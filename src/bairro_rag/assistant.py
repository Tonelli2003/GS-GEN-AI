"""Orquestração do assistente: guardrails de entrada → recuperação → portão de abstenção → geração → verificação."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from .corpus import load_documents, build_chunks
from .generator import (ABSTAIN_MSG, SYSTEM_PROMPT, ExtractiveBackend, build_user_prompt, make_backend)
from .guardrails import check_output, check_places, detect_injection, mask_pii, quarantine_documents
from .retriever import DenseRetriever, HybridRetriever
from .text import tokenize
from .classifier import classify_keywords
import re

ROOT = Path(__file__).resolve().parents[2]
BLOCK_MSG = ("Não posso atender a esse pedido. Eu ajudo apenas com orientações sobre serviços do bairro "
             "(buracos, iluminação, lixo e entulho, barulho, bueiros, árvores e calçadas) com base em fontes oficiais.")
CLARIFY_TMPL = ("Sua pergunta pode se referir a mais de um serviço. Você quer saber sobre: {opts}? "
                "Me diga qual problema você está enfrentando e onde.")
CAT_LABEL = {"buraco_via": "buraco no asfalto", "iluminacao": "iluminação pública", "lixo_entulho": "lixo e entulho",
             "barulho": "barulho (PSIU)", "drenagem": "bueiros e alagamento", "reparacao_danos": "indenização por danos",
             "atendimento_geral": "canais do SP156", "geral_zeladoria": "prazos de zeladoria"}
# Termos genéricos de atendimento: indicam que a pergunta é do domínio, mas sem dizer QUAL serviço.
GENERIC_SERVICE = re.compile(r"problema|reclama|prazo|solicita|servi[cç]o|den[uú]ncia|denunciar|protocolo|"
                             r"atendimento|pedido|consert|minha rua|meu bairro|ocorr[eê]ncia", re.I)
FOLLOWUP_HINTS = {"isso", "esse", "essa", "dele", "dela", "e", "também", "tambem", "mesmo", "prazo", "quanto", "onde"}


@dataclass
class Answer:
    question: str
    answer: str
    status: str                       # answered | fallback | abstained | blocked | clarify
    hits: list = field(default_factory=list)
    check: object = None
    pii_found: list = field(default_factory=list)
    injection_flags: list = field(default_factory=list)
    retrieval_query: str = ""
    backend: str = ""
    model_version: str | None = None
    latency_s: float = 0.0
    raw_answer: str = ""              # 1ª saída do generator, antes de retry/fallback
    raw_check: object = None

    def sources(self) -> list[dict]:
        return [{"n": i, "titulo": h.chunk.meta.get("titulo"), "secao": h.chunk.section,
                 "url": h.chunk.meta.get("url"), "data_consulta": h.chunk.meta.get("data_consulta"),
                 "chunk_id": h.chunk.chunk_id} for i, h in enumerate(self.hits, 1)]


class Assistant:
    def __init__(self, corpus_dir: str | Path = ROOT / "corpus" / "docs", chunking: str = "structural",
                 retriever_mode: str = "hybrid", top_k: int = 4, backend="auto",
                 min_bm25: float = 3.5, min_dense: float = 0.75, extra_docs_dir: str | Path | None = None,
                 quarantine: bool = True, chunk_kwargs: dict | None = None, dense=None,
                 category_boost: bool = False, expand_query: bool = True):
        docs = load_documents(corpus_dir)
        if extra_docs_dir:
            docs += load_documents(extra_docs_dir)
        self.quarantined = []
        if quarantine:
            docs, self.quarantined = quarantine_documents(docs)
        self.docs = docs
        if chunk_kwargs is None:
            chunk_kwargs = ({"max_words": 220, "overlap_words": 40, "list_group": 4, "merge_to": 150}
                            if chunking == "structural" else {})
        self.chunks = build_chunks(docs, chunking, **chunk_kwargs)
        if dense == "lsa":
            dense = DenseRetriever(self.chunks, force_lsa=True)
        self.retriever = HybridRetriever(self.chunks, mode=retriever_mode, dense=dense, expand=expand_query)
        self.top_k, self.min_bm25, self.min_dense = top_k, min_bm25, min_dense
        self.category_boost = category_boost
        self.backend = make_backend(backend) if isinstance(backend, str) else backend
        self.fallback = ExtractiveBackend()

    # ---------- etapas ----------
    def rewrite_query(self, question: str, history) -> str:
        """Perguntas de continuação curtas ("e o prazo?") herdam o tema da pergunta anterior."""
        if not history:
            return question
        toks = question.lower().split()
        if len(tokenize(question)) <= 3 or (toks and toks[0] in FOLLOWUP_HINTS):
            return f"{history[-1][0]} {question}"
        return question

    def is_ambiguous(self, query: str, hits) -> list[str] | None:
        content = tokenize(query)
        if len(content) <= 2 and classify_keywords(query)["categoria"] == "outros" and GENERIC_SERVICE.search(query):
            return ["buraco no asfalto", "iluminação pública", "lixo e entulho", "barulho", "bueiro", "árvore ou calçada"]
        cats = []
        for h in hits:
            c = h.chunk.meta.get("categoria")
            if c not in cats and c not in ("atendimento_geral", "geral_zeladoria"):
                cats.append(c)
        if len(content) <= 2 and len(cats) >= 3:
            return [CAT_LABEL.get(c, c) for c in cats]
        return None

    def ask(self, question: str, history: list[tuple[str, str]] | None = None,
            categories: set[str] | None = None) -> Answer:
        t0 = time.time()
        q_masked, pii = mask_pii(question)
        flags = detect_injection(q_masked)
        bname = getattr(self.backend, "name", "?")
        if flags:
            return Answer(question, BLOCK_MSG, "blocked", pii_found=pii, injection_flags=flags,
                          backend=bname, latency_s=time.time() - t0)

        # placeholders de PII não devem influenciar a busca
        rq = self.rewrite_query(re.sub(r"\[[A-Z]+ REMOVIDO\]", " ", q_masked), history)
        boost = None
        if self.category_boost and not categories:
            cat = classify_keywords(rq)["categoria"]
            boost = {cat} if cat != "outros" else None
        hits = self.retriever.search(rq, self.top_k, categories, boost=boost)
        top_bm25 = hits[0].detail["bm25_raw_top"] if hits else 0.0
        top_dense = max((h.detail["dense"] for h in hits), default=0.0)
        # 1º ambiguidade (perguntas vagas recuperam pouco por natureza), 2º portão de relevância
        opts = self.is_ambiguous(rq, hits)
        if opts:
            return Answer(question, CLARIFY_TMPL.format(opts=", ".join(opts)), "clarify", hits, pii_found=pii,
                          retrieval_query=rq, backend=bname, latency_s=time.time() - t0)
        if not hits or (top_bm25 < self.min_bm25 and top_dense < self.min_dense):
            return Answer(question, ABSTAIN_MSG, "abstained", hits, pii_found=pii, retrieval_query=rq,
                          backend=bname, latency_s=time.time() - t0)

        chunks = [h.chunk for h in hits]
        contexts = [c.text for c in chunks]
        places = check_places(q_masked, contexts)
        if places["outro_municipio"]:
            msg = (f"Minhas fontes cobrem apenas serviços da Prefeitura da cidade de São Paulo, não de "
                   f"{', '.join(places['outro_municipio'])}. Procure a prefeitura desse município.")
            return Answer(question, msg, "abstained", hits, pii_found=pii, retrieval_query=rq, backend=bname,
                          latency_s=time.time() - t0)
        if places["subprefeitura_sem_fonte"]:
            msg = (f"Não encontrei nas fontes oficiais que consultei informações específicas de "
                   f"{', '.join(places['subprefeitura_sem_fonte'])}. Para contatos e atendimento dessa região, "
                   "procure a Central 156 (telefone 156, Portal ou aplicativo SP156).")
            return Answer(question, msg, "abstained", hits, pii_found=pii, retrieval_query=rq, backend=bname,
                          latency_s=time.time() - t0)
        user_prompt = build_user_prompt(q_masked, chunks, history)
        if hasattr(self.backend, "set_chunks"):
            self.backend.set_chunks(chunks)
        try:
            text = self.backend.generate(SYSTEM_PROMPT, user_prompt)
        except Exception as exc:  # erro de API → fallback
            text = f"__erro__ {exc}"
        status = "answered"
        if text.startswith("Não encontrei essa informação"):
            return Answer(question, text, "abstained", hits, pii_found=pii, retrieval_query=rq, backend=bname,
                          model_version=getattr(self.backend, "last_model_version", None), latency_s=time.time() - t0)
        check = check_output(text, contexts, q_masked)
        raw_answer, raw_check = text, check
        if not check.ok and bname == "gemini":
            retry_prompt = user_prompt + ("\n\nATENÇÃO: sua resposta anterior trouxe informação sem citação ou "
                                          "não presente nos trechos. Reescreva usando apenas os trechos, citando [n].")
            try:
                text = self.backend.generate(SYSTEM_PROMPT, retry_prompt)
                check = check_output(text, contexts, q_masked)
            except Exception:
                pass
        if not check.ok:
            self.fallback.set_chunks(chunks)
            text = self.fallback.generate(SYSTEM_PROMPT, user_prompt)
            check = check_output(text, contexts, q_masked)
            status = "fallback"
            if not check.ok:
                text, status = ABSTAIN_MSG, "abstained"
        if pii:
            text = "Por segurança, removi dados pessoais da sua mensagem; não é preciso informá-los aqui.\n" + text
        return Answer(question, text, status, hits, check, pii, [], rq, bname,
                      getattr(self.backend, "last_model_version", None), time.time() - t0, raw_answer, raw_check)
