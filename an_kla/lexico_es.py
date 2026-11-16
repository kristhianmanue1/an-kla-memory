"""Analizador léxico ``an-kla/lexico-es-v1`` de ``recall`` (ADR-0064): plegado, corte, raíz e interrogativos.

Puro y determinista, sólo biblioteca estándar. La raíz es el programa canónico de Snowball para español
(snowballstem.org) aplicado al término ya plegado, con dos cambios declarados y sólo dos:

1. Los sufijos de los pasos 0 (pronombre enclítico), 1 (sufijo estándar) y 2a (verbo en ``y``) se comparan
   en su forma plegada (``acion``, ``logia``, ``ucion``, ``iendo``).
2. En los pasos 2b (verbo) y 3 (residual) se omiten los sufijos que en la referencia llevan tilde
   (``ía``, ``ió``, ``ís``, ``í``, ``aría``, ``éis``...): plegados chocarían con terminaciones nominales átonas que la
   referencia no toca (historia, criterio, crisis, taxi).

Sólo se reduce un término alfabético de 3 o más letras; los dígitos y los mixtos quedan tal cual. No hay lista de
palabras vacías: las frecuentes las descuenta el peso por rareza de BM25. De la consulta (no de los registros) se
quitan los interrogativos de la gramática, una clase cerrada.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

VOWELS = frozenset("aeiou")  # tras plegar, `ü` es `u` y las vocales acentuadas son las llanas

PRONOUNS = ("selas", "selos", "sela", "selo", "las", "les", "los", "nos", "me", "se", "la", "le", "lo")
PRONOUN_BASES = ("iendo", "ando", "ar", "er", "ir")  # `yendo` precedido de `u`, aparte

# Paso 1 (`standard_suffix`): sufijo -> acción. La búsqueda es la del `among` de Snowball: el más largo.
_G_R2 = "anza anzas ico ica icos icas ismo ismos able ables ible ibles ista istas oso osa osos osas " \
        "amiento amientos imiento imientos"
_G_IC = "adora ador acion adoras adores aciones ante antes ancia ancias"
STANDARD: dict[str, str] = {}
STANDARD.update({s: "r2" for s in _G_R2.split()})
STANDARD.update({s: "r2_ic" for s in _G_IC.split()})
STANDARD.update({"logia": "log", "logias": "log", "ucion": "u", "uciones": "u", "encia": "ente", "encias": "ente",
                 "amente": "amente", "mente": "mente", "idad": "idad", "idades": "idad",
                 "iva": "iv", "ivo": "iv", "ivas": "iv", "ivos": "iv"})

Y_VERB = ("yeron", "yendo", "yamos", "yais", "yan", "yen", "yas", "yes", "ya", "ye", "yo")
VERB_GU = ("emos", "en", "es")  # `éis` lleva tilde: omitido (cambio 2)
VERB = tuple(sorted("""aremos eremos iremos aba ada ida ara iera ad ed id ase iese aste iste an aban aran ieran
asen iesen aron ieron ado ido ando iendo ar er ir as abas adas idas aras ieras ases ieses abais arais ierais
aseis ieseis asteis isteis ados idos amos imos""".split(), key=len, reverse=True))
RESIDUAL = ("os", "a", "o")  # `á`, `ó` pliegan a `a`, `o`; `í` omitido (cambio 2)


def _regions(w: str) -> tuple[int, int, int]:
    n = len(w)

    def gopast_vowel(i: int) -> int | None:
        while i < n:
            if w[i] in VOWELS:
                return i + 1
            i += 1
        return None

    def gopast_consonant(i: int) -> int | None:
        while i < n:
            if w[i] not in VOWELS:
                return i + 1
            i += 1
        return None

    pv = n
    if n >= 2:
        if w[1] not in VOWELS:  # V C… o C C…: tras la vocal siguiente
            pv = gopast_vowel(2) or n
        elif w[0] in VOWELS:  # V V…: tras la consonante siguiente
            pv = gopast_consonant(2) or n
        else:  # C V…: tras la tercera letra
            pv = min(3, n)
    p1 = n
    a = gopast_vowel(0)
    if a is not None:
        p1 = gopast_consonant(a) or n
    p2 = n
    if p1 < n:
        a = gopast_vowel(p1)
        if a is not None:
            p2 = gopast_consonant(a) or n
    return pv, p1, p2


def _longest(w: str, suffixes, limit: int = 0) -> str | None:
    """El sufijo más largo de ``suffixes`` que termina ``w`` y empieza en ``limit`` o después.

    Con ``limit`` es el ``setlimit tomark pV`` de Snowball: se busca sólo dentro de RV."""
    best = None
    for s in suffixes:
        if w.endswith(s) and len(w) - len(s) >= limit and (best is None or len(s) > len(best)):
            best = s
    return best


def _attached_pronoun(w: str, pv: int) -> str:
    p = _longest(w, PRONOUNS)
    if p is None:
        return w
    base = w[: -len(p)]
    b = _longest(base, PRONOUN_BASES + ("yendo",))
    if b is None or len(base) - len(b) < pv:
        return w
    if b == "yendo" and not base[: -len(b)].endswith("u"):
        return w
    return base


def _standard(w: str, p1: int, p2: int) -> str | None:
    s = _longest(w, STANDARD)
    if s is None:
        return None
    start, action = len(w) - len(s), STANDARD[s]
    if action == "amente":
        if start < p1:
            return None
        w = w[:start]
        sub = _longest(w, ("iv", "os", "ic", "ad"))
        if sub and len(w) - len(sub) >= p2:
            w = w[: -len(sub)]
            if sub == "iv" and w.endswith("at") and len(w) - 2 >= p2:
                w = w[:-2]
        return w
    if start < p2:
        return None
    w = w[:start]
    if action in ("log", "u", "ente"):
        return w + action
    if action == "r2_ic":
        if w.endswith("ic") and len(w) - 2 >= p2:
            w = w[:-2]
    elif action == "mente":
        sub = _longest(w, ("ante", "able", "ible"))
        if sub and len(w) - len(sub) >= p2:
            w = w[: -len(sub)]
    elif action == "idad":
        sub = _longest(w, ("abil", "ic", "iv"))
        if sub and len(w) - len(sub) >= p2:
            w = w[: -len(sub)]
    elif action == "iv":
        if w.endswith("at") and len(w) - 2 >= p2:
            w = w[:-2]
    return w


def _y_verb(w: str, pv: int) -> str | None:
    s = _longest(w, Y_VERB, pv)
    if s is None or not w[: -len(s)].endswith("u"):
        return None
    return w[: -len(s)]


def _verb(w: str, pv: int) -> str | None:
    s = _longest(w, VERB_GU + VERB, pv)
    if s is None:
        return None
    w = w[: -len(s)]
    if s in VERB_GU and w.endswith("gu"):
        w = w[:-1]
    return w


def _residual(w: str, pv: int) -> str:
    s = _longest(w, RESIDUAL)
    if s is not None:
        return w[: -len(s)] if len(w) - len(s) >= pv else w
    if w.endswith("e") and len(w) - 1 >= pv:
        w = w[:-1]
        if w.endswith("gu") and len(w) - 1 >= pv:
            w = w[:-1]
    return w


def stem(w: str) -> str:
    """Raíz de una palabra YA plegada y en minúsculas."""
    pv, p1, p2 = _regions(w)
    w = _attached_pronoun(w, pv)
    for step in (lambda x: _standard(x, p1, p2), lambda x: _y_verb(x, pv), lambda x: _verb(x, pv)):
        out = step(w)
        if out is not None:
            w = out
            break
    return _residual(w, pv)


ANALYZER = "an-kla/lexico-es-v1"
MIN_STEM_LETTERS = 3
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
# Plegados, como se comparan: «qué» y «que», «cómo» y «como» son el mismo término de la consulta.
INTERROGATIVES = frozenset(
    "que quien quienes cual cuales cuanto cuanta cuantos cuantas como donde adonde cuando "
    "what who whom which how where when why".split()
)


def fold(text: str) -> str:
    """``casefold``, NFKD y descarte de las marcas combinantes (categoría ``Mn``): «facturación» = «facturacion»."""

    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def cut(text: str) -> list[str]:
    """Secuencias maximales de letras o dígitos del texto plegado: ``_``, ``-``, ``.``, ``/`` y todo signo cortan."""

    return _TOKEN.findall(fold(text))


@lru_cache(maxsize=1 << 16)
def reduce_term(token: str) -> str:
    """Raíz de un término ya plegado; sólo si es alfabético y de 3 o más letras (R2-01), si no, tal cual.

    Pura, así que se memoiza: el vocabulario de un store se repite y la raíz domina el coste de una consulta."""

    if len(token) >= MIN_STEM_LETTERS and token.isalpha():
        return stem(token)
    return token


def record_terms(text: str) -> list[str]:
    """Términos de un registro: plegado, corte y raíz; con repeticiones (BM25 cuenta la frecuencia)."""

    return [reduce_term(token) for token in cut(text)]


def query_terms(text: str) -> tuple[list[str], list[str]]:
    """``(tokens, términos)`` de una consulta: los tokens son el corte; los términos, sin interrogativos,
    con raíz y sin repetir (conservando el orden)."""

    tokens = cut(text)
    terms = list(dict.fromkeys(reduce_term(t) for t in tokens if t not in INTERROGATIVES))
    return tokens, terms


__all__ = ["ANALYZER", "INTERROGATIVES", "cut", "fold", "query_terms", "record_terms", "reduce_term", "stem"]
