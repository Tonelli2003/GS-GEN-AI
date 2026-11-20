"""Mitigações: prompt injection (direto e indireto), dados pessoais e respostas não sustentadas."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .text import extract_numbers, tokenize

# Token "canário" inserido no prompt de sistema: se aparecer na saída, houve vazamento do prompt.
CANARY = "BD-CANARIO-7F3A"

INJECTION_PATTERNS = [
    r"ignor\w*\s+(todas?\s+)?(as\s+)?(suas\s+)?(instru|regra|orienta)",
    r"desconsider\w*\s+(as\s+)?(instru|regra)",
    r"esque[cç]\w*\s+(as\s+|suas\s+)?(instru|regra)",
    r"ignore\s+(all\s+|any\s+)?(previous|prior|above)",
    r"(voc[eê]|vc)\s+(agora\s+)?([eé]|ser[aá])\s+(um|uma)\s+(assistente|ia|modelo)\s+(sem|livre)",
    r"sem\s+restri[cç]",
    r"modo\s+(desenvolvedor|developer|dan|jailbreak)",
    r"(revel|mostr|exib|imprim|repit|diga|conte)\w*\s+(o\s+|seu\s+|teu\s+|as\s+|suas\s+)?(prompt|instru[cç][oõ]es\s+(de\s+)?sistema|system\s*prompt|regras\s+internas)",
    r"system\s*prompt|prompt\s+de\s+sistema",
    r"act\s+as|jailbreak",
    r"(n[uú]mero|dados)\s+do\s+cart[aã]o",
    r"marqu\w*\s+(como\s+)?(urgente|prioridade\s+m[aá]xima)|prioridade\s+m[aá]xima",
]
_INJ = [re.compile(p, re.I) for p in INJECTION_PATTERNS]

PII_PATTERNS = {
    "cpf": re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"),
    "cnpj": re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b"),
    "cartao": re.compile(r"\b(?:\d{4}[ .-]?){3}\d{4}\b"),
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "telefone": re.compile(r"(?<!\d)(?:\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}[-\s]?\d{4}(?!\d)"),
}


def detect_injection(text: str) -> list[str]:
    return [p.pattern for p in _INJ if p.search(text or "")]


def mask_pii(text: str) -> tuple[str, list[str]]:
    """Mascara CPF, CNPJ, cartão, e-mail e telefone em textos do cidadão (antes de logar/enviar ao LLM)."""
    found = []
    for kind in ("cartao", "cnpj", "cpf", "email", "telefone"):
        pat = PII_PATTERNS[kind]
        if pat.search(text):
            found.append(kind)
            text = pat.sub(f"[{kind.upper()} REMOVIDO]", text)
    return text, found


def quarantine_documents(docs):
    """Remove da indexação documentos com instruções suspeitas (prompt injection indireto)."""
    clean, quarantined = [], []
    for d in docs:
        hits = detect_injection(d.body)
        (quarantined if hits else clean).append((d, hits) if hits else d)
    return clean, quarantined


# Gazetteer: subprefeituras da capital e municípios vizinhos. Usado para evitar que o assistente
# responda sobre um lugar com dados de OUTRO lugar (ex.: telefone da Sé para quem perguntou de Pinheiros).
SUBPREFEITURAS = ["Aricanduva", "Butantã", "Campo Limpo", "Capela do Socorro", "Casa Verde", "Cidade Ademar",
                  "Cidade Tiradentes", "Ermelino Matarazzo", "Freguesia do Ó", "Brasilândia", "Guaianases", "Ipiranga",
                  "Itaim Paulista", "Itaquera", "Jabaquara", "Jaçanã", "Lapa", "M'Boi Mirim", "Mooca", "Parelheiros",
                  "Penha", "Perus", "Pinheiros", "Pirituba", "Santana", "Santo Amaro", "São Mateus",
                  "São Miguel Paulista", "Sapopemba", "Sé", "Vila Maria", "Vila Mariana", "Vila Prudente"]
OUTROS_MUNICIPIOS = ["Guarulhos", "Osasco", "Santo André", "São Bernardo", "São Caetano", "Diadema", "Mauá", "Barueri",
                     "Carapicuíba", "Taboão da Serra", "Cotia", "Embu", "Mogi das Cruzes", "Suzano", "Itaquaquecetuba",
                     "Campinas", "Santos", "Sorocaba", "Rio de Janeiro", "Belo Horizonte"]


def _mentions(name: str, text: str) -> bool:
    if name == "Sé":  # evita colisão com o pronome "se"
        return re.search(r"\bSé\b", text) is not None
    from .text import normalize
    return re.search(r"\b" + re.escape(normalize(name)) + r"\b", normalize(text)) is not None


def check_places(question: str, contexts: list[str]) -> dict:
    """Lugares citados na pergunta que não aparecem nos trechos recuperados."""
    ctx = "\n".join(contexts)
    other_city = [m for m in OUTROS_MUNICIPIOS if _mentions(m, question)]
    missing_sub = [s for s in SUBPREFEITURAS if _mentions(s, question) and not _mentions(s, ctx)]
    return {"outro_municipio": other_city, "subprefeitura_sem_fonte": missing_sub}


NUMERIC_Q = re.compile(r"\bquant[oa]s?\b|em quanto tempo|qual (é |e )?(o |a )?(prazo|valor|telefone|n[uú]mero|hor[aá]rio|multa)", re.I)


@dataclass
class OutputCheck:
    ok: bool
    support: float
    unsupported_numbers: list[str] = field(default_factory=list)
    invalid_citations: list[int] = field(default_factory=list)
    cited: list[int] = field(default_factory=list)
    leak: bool = False
    reasons: list[str] = field(default_factory=list)


# Frases de moldura (pedidas no prompt) que não são afirmações factuais e não entram no cálculo de suporte.
BOILERPLATE = [r"segundo as fontes oficiais consultadas:?", r"ao registrar a solicita[cç][aã]o,? anote o n[uú]mero do protocolo\.?",
               r"anote o (n[uú]mero do )?protocolo( para acompanhamento)?\.?", r"por seguran[cç]a, removi dados pessoais[^\n]*"]


def check_output(answer: str, contexts: list[str], query: str = "", min_support: float = 0.5) -> OutputCheck:
    """Verifica se a resposta está sustentada pelos trechos recuperados:
    (1) citações [n] válidas; (2) todo número (telefone, prazo, valor) existe no contexto;
    (3) proporção de termos da resposta presentes no contexto; (4) vazamento do prompt."""
    reasons = []
    ctx_all = "\n".join(contexts)
    cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer)})
    invalid = [n for n in cited if n < 1 or n > len(contexts)]
    if invalid:
        reasons.append(f"citações inválidas {invalid}")

    body = re.sub(r"\[\d+\]", " ", answer)
    for bp in BOILERPLATE:
        body = re.sub(bp, " ", body, flags=re.I)
    nums_ans = {n for n in extract_numbers(body) if len(n) >= 2}
    nums_ok = extract_numbers(ctx_all) | extract_numbers(query)
    unsupported = sorted(n for n in nums_ans if not any(n in m for m in nums_ok))
    if unsupported:
        reasons.append(f"números sem evidência {unsupported}")

    ans_toks = set(tokenize(body))
    ctx_toks = set(tokenize(ctx_all)) | set(tokenize(query))
    support = len(ans_toks & ctx_toks) / len(ans_toks) if ans_toks else 1.0
    if support < min_support:
        reasons.append(f"baixa sobreposição com as fontes ({support:.2f})")

    if NUMERIC_Q.search(query or "") and not re.search(r"\d", body):
        reasons.append("a pergunta pede um dado (prazo/valor/telefone) e a resposta não o traz")
    leak = CANARY in answer or "REGRAS INVIOLÁVEIS" in answer
    if leak:
        reasons.append("vazamento do prompt de sistema")
    if contexts and not cited:
        reasons.append("resposta sem citação")
    ok = not reasons
    return OutputCheck(ok, round(support, 3), unsupported, invalid, cited, leak, reasons)
