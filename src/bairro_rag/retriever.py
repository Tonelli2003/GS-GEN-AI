"""Retrievers: BM25 (lexical), denso (embeddings) e híbrido (Reciprocal Rank Fusion)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

import numpy as np
from rank_bm25 import BM25Okapi

from .corpus import Chunk
from .text import tokenize, normalize

DEFAULT_EMB_MODEL = os.getenv("BAIRRO_EMB_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
# categorias transversais que nunca são removidas pelo filtro
ALWAYS_CATEGORIES = {"atendimento_geral", "geral_zeladoria"}


# Expansão de consulta: linguagem do cidadão → vocabulário das cartas de serviço (só para o BM25).
QUERY_EXPANSION = {
    r"quanto tempo|demora|em quantos dias": "prazo",
    r"\bconsert\w*|arrum\w*": "manutenção",
    r"\broub\w*": "furto",
    r"\bpostes?\b|\bl[aâ]mpadas?\b|\bluz\b": "iluminação pública",
    r"barulh\w*|som alto|zoeira": "ruído PSIU",
    r"\bbueiros?\b": "boca de lobo",
    r"\bsof[aá]s?\b|\bm[oó]veis\b|colch[aã]o": "objetos volumosos Cata-Bagulho Ecoponto",
    r"\bindeniza\w*|ressarc\w*|preju[ií]zo": "reparação de danos",
    r"\bburacos?\b": "tapa-buraco",
}


# Intenção da pergunta → seções preferidas. Só é possível porque o chunking estrutural preserva o nome da seção.
SECTION_INTENTS = [
    (r"\bprazo|quanto tempo|demora|em quantos dias|quando (v[aã]o|vai)", r"prazo"),
    (r"document|preciso levar|requisit|o que (devo )?informar|o que preciso", r"document|requisit|informa|o que informar"),
    (r"\bcanal|canais|telefone|whatsapp|onde (eu )?(pe[cç]o|solicito|denuncio|ligo)|como (eu )?(pe[cç]o|solicito|denuncio)",
     r"canais|como solicitar|contato|onde solicitar"),
    (r"\bcusta|\btaxa|gr[aá]tis|pagar|pago", r"taxa"),
    (r"\bmulta|penalidade", r"penalidade|descarte irregular|multa"),
    (r"hor[aá]rio|que horas|funciona", r"hor[aá]rio"),
]


def section_intent(query: str) -> list[str]:
    return [sec for pat, sec in SECTION_INTENTS if re.search(pat, query, re.I)]


def expand_query(query: str) -> str:
    extra = [v for pat, v in QUERY_EXPANSION.items() if re.search(pat, query, re.I)]
    return query + (" " + " ".join(extra) if extra else "")


@dataclass
class Hit:
    chunk: Chunk
    score: float
    rank: int
    detail: dict


class BM25Retriever:
    name = "bm25"

    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.bm25 = BM25Okapi([tokenize(c.text) for c in chunks], k1=k1, b=b)

    def scores(self, query: str) -> np.ndarray:
        return np.asarray(self.bm25.get_scores(tokenize(query)), dtype=float)


class DenseRetriever:
    """Embeddings multilíngues (sentence-transformers). Sem acesso ao modelo, usa LSA
    (TF-IDF de n-gramas de caracteres + SVD) como aproximação densa offline."""

    def __init__(self, chunks: list[Chunk], model_name: str = DEFAULT_EMB_MODEL, force_lsa: bool = False):
        self.chunks = chunks
        self.backend = None
        texts = [c.text for c in chunks]
        if not force_lsa:
            try:
                from sentence_transformers import SentenceTransformer

                self.model = SentenceTransformer(model_name)
                self.matrix = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
                self.backend = f"st:{model_name}"
            except Exception as exc:  # sem internet / sem pacote
                self._init_error = repr(exc)
        if self.backend is None:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.decomposition import TruncatedSVD
            from sklearn.preprocessing import normalize as l2

            self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), preprocessor=normalize, sublinear_tf=True)
            X = self.vec.fit_transform(texts)
            n_comp = max(2, min(128, X.shape[0] - 1, X.shape[1] - 1))
            self.svd = TruncatedSVD(n_components=n_comp, random_state=42)
            self.matrix = l2(self.svd.fit_transform(X))
            self._l2 = l2
            self.backend = f"lsa:char3-5+svd{n_comp}"
        self.name = "dense"

    def embed_query(self, query: str) -> np.ndarray:
        if self.backend.startswith("st:"):
            return self.model.encode([query], normalize_embeddings=True, show_progress_bar=False)[0]
        return self._l2(self.svd.transform(self.vec.transform([query])))[0]

    def scores(self, query: str) -> np.ndarray:
        return self.matrix @ self.embed_query(query)


class HybridRetriever:
    """Combina BM25 e denso por Reciprocal Rank Fusion: score = Σ 1/(rrf_k + rank)."""

    def __init__(self, chunks: list[Chunk], mode: str = "hybrid", dense: DenseRetriever | None = None,
                 rrf_k: int = 60, w_bm25: float = 1.0, w_dense: float = 1.0, expand: bool = True,
                 intent: bool = True):
        self.expand, self.intent = expand, intent
        self.chunks = chunks
        self.mode = mode
        self.bm25 = BM25Retriever(chunks)
        self.dense = dense if dense is not None else (DenseRetriever(chunks) if mode != "bm25" else None)
        self.rrf_k, self.w_bm25, self.w_dense = rrf_k, w_bm25, w_dense

    @property
    def dense_backend(self) -> str:
        return self.dense.backend if self.dense else "-"

    def _mask(self, categories: set[str] | None) -> np.ndarray:
        if not categories:
            return np.ones(len(self.chunks), dtype=bool)
        allowed = set(categories) | ALWAYS_CATEGORIES
        return np.array([c.meta.get("categoria") in allowed for c in self.chunks])

    def search(self, query: str, top_k: int = 4, categories: set[str] | None = None,
               boost: set[str] | None = None, boost_weight: float = 0.5) -> list[Hit]:
        """categories = filtro rígido (ex.: categoria do relato); boost = filtro suave
        (soma um termo RRF extra, equivalente a estar em 1º lugar, para chunks da categoria prevista)."""
        mask = self._mask(categories)
        bm = self.bm25.scores(expand_query(query) if self.expand else query)
        de = self.dense.scores(query) if self.dense else np.zeros(len(self.chunks))
        idx = np.where(mask)[0]

        def ranks(arr):
            order = idx[np.argsort(-arr[idx], kind="stable")]
            return {int(i): r + 1 for r, i in enumerate(order)}

        r_bm, r_de = ranks(bm), ranks(de)
        if self.mode == "bm25":
            fused = {i: bm[i] for i in idx}
        elif self.mode == "dense":
            fused = {i: de[i] for i in idx}
        else:
            fused = {int(i): self.w_bm25 / (self.rrf_k + r_bm[int(i)]) + self.w_dense / (self.rrf_k + r_de[int(i)]) for i in idx}
            if self.intent:
                pats = section_intent(query)
                if pats:
                    for i in fused:
                        sec = self.chunks[i].section.lower()
                        if any(re.search(p, sec) for p in pats):
                            fused[i] += 0.5 / (self.rrf_k + 1)
            if boost:
                for i in fused:
                    if self.chunks[i].meta.get("categoria") in (set(boost) | ALWAYS_CATEGORIES):
                        fused[i] += boost_weight / (self.rrf_k + 1)
        order = sorted(fused, key=lambda i: -fused[i])[:top_k]
        bm_max = float(bm.max()) if bm.max() > 0 else 1.0
        return [
            Hit(self.chunks[i], float(fused[i]), r + 1,
                {"bm25": float(bm[i]), "bm25_norm": float(bm[i] / bm_max), "bm25_raw_top": float(bm.max()),
                 "dense": float(de[i]), "rank_bm25": r_bm[i], "rank_dense": r_de[i]})
            for r, i in enumerate(order)
        ]
