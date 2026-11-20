"""Normalização e tokenização em português, compartilhadas por BM25, guardrails e avaliação."""
from __future__ import annotations

import re
import unicodedata

STOPWORDS = set(
    """
    a à às ao aos as o os um uma uns umas de da das do dos dum duma em na nas no nos num numa
    por pela pelas pelo pelos para pra pro com sem sob sobre entre até após ante contra desde
    e ou mas nem que se como quando onde quem qual quais cujo cuja porque pois porém também já
    não sim mais menos muito muita muitos muitas pouco pouca bem mal só apenas ainda tão
    eu tu ele ela nós vós eles elas me te lhe nos vos lhes meu minha meus minhas teu tua seu sua
    seus suas nosso nossa isso isto aquilo esse essa esses essas este esta estes estas aquele aquela
    é ser são foi era estar está estão estou tem têm ter tenho há haver fazer faz fiz pode posso
    devo deve vai vou ir lá aqui aí então assim cada todo toda todos todas outro outra outros outras
    qualquer algum alguma alguns algumas nenhum nenhuma mesmo mesma tipo coisa gente
    """.split()
)

_SUFFIXES = (
    "amentos", "imentos", "amento", "imento", "ações", "ação", "ções", "ção", "mente",
    "idades", "idade", "ismos", "ismo", "istas", "ista", "ários", "ário", "árias", "ária",
    "ados", "adas", "idos", "idas", "ado", "ada", "ido", "ida", "ando", "endo", "indo",
    "ar", "er", "ir", "es", "os", "as", "s",
)


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def normalize(text: str) -> str:
    return strip_accents(text.lower())


def light_stem(token: str) -> str:
    """Stemmer leve por sufixo (sem dependências externas). Mantém radicais com >= 4 letras."""
    for suf in _SUFFIXES:
        s = strip_accents(suf)
        if token.endswith(s) and len(token) - len(s) >= 4:
            return token[: -len(s)]
    return token


try:  # stemmer Snowball para português (RSLP-like); fallback: stemmer leve por sufixo
    import snowballstemmer

    _SNOW = snowballstemmer.stemmer("portuguese")
except Exception:  # pragma: no cover
    _SNOW = None

_STOP_NORM = {strip_accents(w) for w in STOPWORDS}


def tokenize(text: str, stem: bool = True, drop_stopwords: bool = True) -> list[str]:
    toks = re.findall(r"[a-zà-ÿ0-9]+", text.lower())
    out = [t for t in toks if not (drop_stopwords and strip_accents(t) in _STOP_NORM) and (len(t) > 1 or t.isdigit())]
    if stem:
        if _SNOW is not None:
            out = _SNOW.stemWords(out)
        else:
            out = [light_stem(strip_accents(t)) for t in out]
    return [strip_accents(t) for t in out]


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?;])\s+|\n+", text)
    return [p.strip(" -•\t") for p in parts if len(p.strip(" -•\t")) > 3]


def extract_numbers(text: str) -> set[str]:
    """Números relevantes (telefones, prazos, valores, leis), normalizados só com dígitos."""
    found = set()
    for m in re.findall(r"\d[\d.\-/ ,]*\d|\d", text):
        digits = re.sub(r"\D", "", m)
        if digits:
            found.add(digits)
    return found
