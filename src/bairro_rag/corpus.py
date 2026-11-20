"""Leitura do corpus (Markdown com front matter) e chunking estrutural / por tamanho."""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class Document:
    doc_id: str
    meta: dict
    body: str


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    text: str            # texto indexado (inclui título e seção como contexto)
    section: str
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def parse_front_matter(raw: str) -> tuple[dict, str]:
    if not raw.startswith("---"):
        return {}, raw
    _, fm, body = raw.split("---", 2)
    meta = {}
    for line in fm.strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, body.strip()


def load_documents(folder: str | Path) -> list[Document]:
    docs = []
    for path in sorted(Path(folder).glob("*.md")):
        meta, body = parse_front_matter(path.read_text(encoding="utf-8"))
        meta["arquivo"] = path.name
        docs.append(Document(doc_id=meta.get("id", path.stem), meta=meta, body=body))
    return docs


def _meta_for_chunk(doc: Document) -> dict:
    keep = ("titulo", "orgao", "categoria", "url", "data_publicacao", "data_consulta", "nota_atualizacao")
    return {k: doc.meta[k] for k in keep if k in doc.meta}


def chunk_structural(docs: list[Document], max_words: int = 220, overlap_words: int = 40,
                     list_group: int | None = None) -> list[Chunk]:
    """Um chunk por seção (## ...). Seções longas são subdivididas por parágrafo/linha com overlap.
    Cada chunk recebe o título do documento e o nome da seção como prefixo (contexto + metadados).
    list_group: seções longas compostas por itens de lista (tabelas de prazos, FAQs em tópicos) viram
    grupos de N itens — cada item é autocontido, então o grupo pequeno não perde contexto."""
    chunks: list[Chunk] = []
    for doc in docs:
        title = doc.meta.get("titulo", doc.doc_id)
        sections = re.split(r"^##\s+", doc.body, flags=re.M)
        intro = sections[0]
        intro = re.sub(r"^#\s+.*$", "", intro, flags=re.M).strip()
        blocks = ([("Introdução", intro)] if intro else []) + [
            (s.split("\n", 1)[0].strip(), s.split("\n", 1)[1].strip() if "\n" in s else "")
            for s in sections[1:]
        ]
        idx = 0
        for sec_name, sec_text in blocks:
            if not sec_text:
                continue
            lines = [l for l in sec_text.splitlines() if l.strip()]
            bullets = [l for l in lines if l.lstrip().startswith(("-", "*")) or re.match(r"^\s*\d+\.", l)]
            if list_group and len(bullets) >= 2 * list_group and len(sec_text.split()) > 80:
                head = [l for l in lines if l not in bullets]
                prefix = ("\n".join(head) + "\n") if head and len(" ".join(head).split()) < 40 else ""
                pieces = [prefix + "\n".join(bullets[i:i + list_group]) for i in range(0, len(bullets), list_group)]
            else:
                pieces = _split_long(sec_text, max_words, overlap_words)
            for piece in pieces:
                text = f"{title} — {sec_name}\n{piece}"
                chunks.append(Chunk(f"{doc.doc_id}#{idx}", doc.doc_id, text, sec_name, _meta_for_chunk(doc)))
                idx += 1
    return chunks


def merge_small_chunks(chunks: list[Chunk], merge_to: int) -> list[Chunk]:
    """Junta seções vizinhas do MESMO documento até ~merge_to palavras, sem nunca cortar uma seção ao meio.
    Mantém a fronteira estrutural, mas dá mais contexto a seções muito curtas (ex.: "Taxas: gratuito")."""
    out: list[Chunk] = []
    for c in chunks:
        prev = out[-1] if out else None
        body = c.text.split("\n", 1)[1] if "\n" in c.text else c.text
        if (prev and prev.doc_id == c.doc_id and len(prev.text.split()) + len(body.split()) <= merge_to):
            prev.text += f"\n[{c.section}]\n{body}"
            prev.section += f" | {c.section}"
        else:
            title = c.text.split("\n", 1)[0].split(" — ")[0]
            out.append(Chunk(c.chunk_id, c.doc_id, f"{title}\n[{c.section}]\n{body}", c.section, dict(c.meta)))
    for i, c in enumerate(out):  # renumera por documento
        n = sum(1 for o in out[:i] if o.doc_id == c.doc_id)
        c.chunk_id = f"{c.doc_id}#{n}"
    return out


def _split_long(text: str, max_words: int, overlap_words: int) -> list[str]:
    if len(text.split()) <= max_words:
        return [text]
    lines = [l for l in text.splitlines() if l.strip()]
    pieces, cur = [], []
    for line in lines:
        if cur and len(" ".join(cur + [line]).split()) > max_words:
            pieces.append("\n".join(cur))
            # overlap: carrega as últimas linhas até ~overlap_words
            carry, n = [], 0
            for prev in reversed(cur):
                n += len(prev.split())
                carry.insert(0, prev)
                if n >= overlap_words:
                    break
            cur = carry
        cur.append(line)
    if cur:
        pieces.append("\n".join(cur))
    return pieces


def chunk_fixed(docs: list[Document], size_words: int = 120, overlap_words: int = 30) -> list[Chunk]:
    """Baseline: janelas de tamanho fixo em palavras, ignorando a estrutura do documento."""
    chunks: list[Chunk] = []
    step = max(1, size_words - overlap_words)
    for doc in docs:
        plain = re.sub(r"^#+\s*", "", doc.body, flags=re.M)
        words = plain.split()
        for idx, start in enumerate(range(0, max(1, len(words) - overlap_words), step)):
            piece = " ".join(words[start : start + size_words])
            if not piece:
                continue
            chunks.append(Chunk(f"{doc.doc_id}#f{idx}", doc.doc_id, piece, "janela", _meta_for_chunk(doc)))
    return chunks


def build_chunks(docs: list[Document], strategy: str = "structural", **kw) -> list[Chunk]:
    if strategy == "structural":
        merge_to = kw.pop("merge_to", None)
        chunks = chunk_structural(docs, **kw)
        return merge_small_chunks(chunks, merge_to) if merge_to else chunks
    if strategy == "fixed":
        return chunk_fixed(docs, **kw)
    raise ValueError(f"estratégia desconhecida: {strategy}")
