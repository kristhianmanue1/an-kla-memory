"""``recall``: recuperar hechos por relevancia léxica ponderada, determinista y acotada (ADR-0064).

BM25 (``k1 = 1,2``, ``b = 0,75``) sobre el texto analizado por :mod:`an_kla.lexico_es`, con ``N``, ``df`` y la longitud
media calculados sobre el conjunto candidato: los registros vigentes de los streams buscados dentro del ámbito. No
comparte puntuación con ``retrieve`` ni lo cambia. Lee un snapshot bajo el gate compartido de lectores y no persiste
nada: cada consulta recorre el snapshot, así que no hay índice que pueda faltar o envejecer.

Orden total (Enmienda 1): puntuación exacta descendente, después ``enqueued_at`` del sobre válido descendente (un registro
sin sobre válido va detrás) y después ``id`` ascendente.

El presupuesto acota la salida JSON completa, tal como se imprime. Se decide con la longitud exacta de la respuesta
terminada en salto de línea, con cotas superiores en lugar de los contadores aún desconocidos (``used_bytes`` = el
presupuesto, que tiene al menos tantas cifras como el real; ``excluded.budget`` y ``excluded.truncated`` = el número
total de candidatos, que acota sus valores finales): la respuesta final nunca mide más que la última comprobada. Si la
entrada completa de un candidato no cabe, se prueba su stub (sin texto, escritor ni ``disputed_by``); sólo si ni el
stub cabe, se salta.
"""

from __future__ import annotations

import math
from contextlib import nullcontext
from copy import deepcopy
from typing import Any, Mapping

from . import identity_c0
from .canonical import canonical_json
from .disputes import _valid_disputes, list_disputes
from .inbox import read_status as inbox_read_status
from .lexico_es import ANALYZER, query_terms, record_terms
from .reader_gate import shared_reader_gate
from .record_text import record_text
from .vigency import is_active

RESULT_SCHEMA = "an-kla/recall-result-v1"
K1 = 1.2
B = 0.75
SCORE_DECIMALS = 6
DEFAULT_BUDGET = 4000
DEFAULT_STREAMS = ("facts",)
RECALL_STREAMS = ("facts", "episodes")
SCOPES = ("repo", "all")
_HINTS = {
    "recall_query_empty": "la consulta no deja términos: usa palabras, números o identificadores",
    "recall_budget_too_small": "ni la respuesta vacía cabe en --budget: súbelo",
    "recall_scope_unavailable": "--scope repo necesita un repo Git en --project-root; usa --scope all para no filtrar por repo",
    "unsupported_recall_stream": "--streams admite facts y episodes, separados por comas",
    "unsupported_recall_scope": "--scope admite repo o all",
    "recall_min_terms_invalid": "--min-terms es un entero mayor o igual que 1",
}


class RecallError(ValueError):
    """Error estable de ``recall``; ``str(error)`` es el código y ``detail`` la pista (el CLI la imprime)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
        self.detail = _HINTS.get(code)


def _streams(value: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    selected = tuple(value) if value is not None else DEFAULT_STREAMS
    if not selected or any(s not in RECALL_STREAMS for s in selected):
        raise RecallError("unsupported_recall_stream")
    return tuple(dict.fromkeys(selected))


def _scope_repo_id(store: Any, scope: str) -> str | None:
    """``repo.id`` C0 del ``--project-root``, derivado como lo hace ``remember``; con ``repo`` sin Git falla."""

    try:
        return identity_c0.repo_id_for(store.project_root)
    except identity_c0.IdentityC0Error:
        if scope == "repo":
            raise RecallError("recall_scope_unavailable") from None
        return None  # `all` no filtra: sin repo propio, ningún sobre válido se marca `repo`


def _envelope_view(record: Mapping[str, Any]) -> tuple[str, Mapping[str, Any] | None]:
    """``("legacy", None)`` sin campo de sobre, ``("invalid", None)`` con sobre inválido, ``("valid", sobre)``."""

    if "an_kla_envelope" not in record:
        return "legacy", None
    envelope = record["an_kla_envelope"]
    if identity_c0.validate_envelope(envelope):
        return "invalid", None
    return "valid", envelope


def _writer(envelope: Mapping[str, Any] | None) -> tuple[Any, Any]:
    if envelope is None:
        return None, None
    return deepcopy(envelope["writer"]), envelope["enqueued_at"]


def _scope_match(kind: str, envelope: Mapping[str, Any] | None, repo_id: str | None) -> str:
    if kind == "legacy":
        return "legacy"
    if kind == "invalid":
        return "invalid_envelope"
    return "repo" if repo_id is not None and envelope["writer"]["repo"]["id"] == repo_id else "other"  # type: ignore[index]


def _inbox(store: Any) -> dict[str, Any]:
    """Estado de la bandeja de ``inbox.read_status`` (sólo nombres, sin candado); nunca falla la consulta."""

    try:
        status = inbox_read_status(store)
    except (OSError, ValueError, RuntimeError):
        return {"state": "unsafe", "pending": None, "inflight": None}
    top, dirs = status["inbox"], status["directories"]
    if top == "absent":
        return {"state": "absent", "pending": 0, "inflight": 0}
    counts: dict[str, Any] = {}
    for label in ("pending", "inflight"):
        state = "unsafe" if top == "unsafe" else dirs.get(label)
        counts[label] = {"present": status[label]["count"], "absent": 0}.get(state)
    unsafe = top == "unsafe" or "unsafe" in (dirs.get("pending"), dirs.get("inflight"))
    return {"state": "unsafe" if unsafe else "present", **counts}


def _bm25(
    terms: list[str], candidates: list[dict[str, Any]], tokens_by_index: list[list[str]]
) -> list[tuple[float, int, list[str]]]:
    """``(puntuación, índice, términos de la consulta presentes)`` de cada candidato con puntuación mayor que cero."""

    count = len(candidates)
    lengths = [len(tokens) for tokens in tokens_by_index]
    average = sum(lengths) / count if count else 0.0
    if count == 0 or average == 0:
        return []
    frequencies: list[dict[str, int]] = []
    df: dict[str, int] = {}
    wanted = set(terms)
    for tokens in tokens_by_index:
        tf: dict[str, int] = {}
        for token in tokens:
            if token in wanted:
                tf[token] = tf.get(token, 0) + 1
        frequencies.append(tf)
        for token in tf:
            df[token] = df.get(token, 0) + 1
    idf = {t: math.log(1 + (count - df[t] + 0.5) / (df[t] + 0.5)) for t in terms if t in df}
    scored = []
    for index, tf in enumerate(frequencies):
        norm = K1 * (1 - B + B * lengths[index] / average)
        score = 0.0
        for term in terms:
            freq = tf.get(term)
            if freq:
                score += idf[term] * freq * (K1 + 1) / (freq + norm)
        if score > 0:
            scored.append((score, index, [t for t in terms if t in tf]))
    return scored


def _body(
    query: str, revision: str, repo_id: str | None, scope: str, streams: tuple[str, ...], budget: int,
    inbox: dict[str, Any], excluded: Mapping[str, int], used: int, results: list[Any],
    terms: list[str], no_strong_match: bool,
) -> dict[str, Any]:
    return {
        "schema": RESULT_SCHEMA,
        "untrusted_memory_data": True,
        "revision": revision,
        "analyzer": ANALYZER,
        "query": query,
        "scope": {"mode": scope, "repo_id": repo_id},
        "streams": list(streams),
        "budget_bytes": budget,
        "used_bytes": used,
        "inbox": inbox,
        "excluded": dict(excluded),
        "query_terms": terms,
        "no_strong_match": no_strong_match,
        "results": results,
    }


def render(result: Mapping[str, Any]) -> bytes:
    """Los bytes de la salida: JSON canónico (claves ordenadas, sin espacios sobrantes) y un salto de línea."""

    return canonical_json(result) + b"\n"


def _under_gate(
    store: Any, query: str, budget: int, scope: str, streams: tuple[str, ...], min_terms: int
) -> dict[str, Any]:
    tokens, terms = query_terms(query)
    if not tokens:
        raise RecallError("recall_query_empty")
    repo_id = _scope_repo_id(store, scope)
    snapshot = store.snapshot()
    disputes = list_disputes(snapshot)["disputes"]
    disputed_by: dict[str, list[dict[str, Any]]] = {}
    for item in disputes:
        disputed_by.setdefault(item["target"]["id"], []).append(
            {k: item[k] for k in ("id", "text", "writer", "enqueued_at")}
        )
    excluded = {"budget": 0, "invalid_envelope": 0, "min_terms": 0, "scope": 0, "truncated": 0}
    candidates: list[dict[str, Any]] = []
    for stream in streams:
        for record in snapshot.records[stream]:
            if not is_active(record) or not record.get("id"):
                continue
            kind, envelope = _envelope_view(record)
            if scope == "repo":
                if kind == "invalid":
                    excluded["invalid_envelope"] += 1
                    continue
                if kind == "valid" and envelope["writer"]["repo"]["id"] != repo_id:  # type: ignore[index]
                    excluded["scope"] += 1
                    continue
            text = record_text(dict(record))
            if not text:
                continue
            writer, enqueued_at = _writer(envelope)
            marked = record.get("disputes")
            candidates.append({
                "id": str(record["id"]), "stream": stream, "text": text, "writer": writer,
                "enqueued_at": enqueued_at, "scope_match": _scope_match(kind, envelope, repo_id),
                "marked": marked,
            })
    found = _bm25(terms, candidates, [record_terms(c["text"]) for c in candidates]) if terms else []
    survivors = [row for row in found if len(row[2]) >= min_terms]
    excluded["min_terms"] = len(found) - len(survivors)
    no_strong_match = bool(found) and not survivors
    # Orden total: puntuación exacta descendente, `enqueued_at` descendente (sin sobre válido, detrás) e `id`.
    survivors.sort(key=lambda row: candidates[row[1]]["id"])
    survivors.sort(key=lambda row: (candidates[row[1]]["enqueued_at"] is not None, candidates[row[1]]["enqueued_at"] or ""),
                   reverse=True)
    survivors.sort(key=lambda row: -row[0])
    inbox = _inbox(store)
    total = len(survivors)

    def size(used: int, skipped: int, truncated: int, items: int, items_bytes: int) -> int:
        shell = _body(query, snapshot.revision_id, repo_id, scope, streams, budget, inbox,
                      {**excluded, "budget": skipped, "truncated": truncated}, used, [], terms, no_strong_match)
        return len(render(shell)) + items_bytes + max(items - 1, 0)

    if size(budget, total, total, 0, 0) > budget:
        raise RecallError("recall_budget_too_small")
    results: list[dict[str, Any]] = []
    items_bytes = 0
    stubs = 0
    for rank, (score, index, matched) in enumerate(survivors, start=1):
        c = candidates[index]
        disputed = disputed_by.get(c["id"], [])
        full = {
            "rank": rank, "id": c["id"], "stream": c["stream"], "score": round(score, SCORE_DECIMALS),
            "text": c["text"], "writer": c["writer"], "enqueued_at": c["enqueued_at"],
            "scope_match": c["scope_match"], "matched_terms": matched, "truncated": False,
            "disputed_by": disputed, "disputes": _disputes_field(c["marked"]),
        }
        stub = {
            "rank": rank, "id": c["id"], "stream": c["stream"], "score": round(score, SCORE_DECIMALS),
            "enqueued_at": c["enqueued_at"], "scope_match": c["scope_match"], "matched_terms": matched,
            "truncated": True, "disputed": bool(disputed),
        }
        for item in (full, stub):
            cost = len(canonical_json(item))
            # Cotas de prueba: `excluded.budget` y `excluded.truncated` valen el total de candidatos.
            if size(budget, total, total, len(results) + 1, items_bytes + cost) <= budget:
                results.append(item)
                items_bytes += cost
                stubs += item["truncated"]
                break
    excluded["truncated"] = stubs
    excluded["budget"] = total - len(results)
    used = size(budget, excluded["budget"], stubs, len(results), items_bytes)
    for _ in range(8):  # punto fijo: `used_bytes` es la longitud de la salida que lo contiene; sus cifras sólo bajan
        out = _body(query, snapshot.revision_id, repo_id, scope, streams, budget, inbox, excluded, used, results,
                    terms, no_strong_match)
        length = len(render(out))
        if length == used:
            return out
        used = length
    raise RecallError("recall_budget_too_small")  # inalcanzable: las cifras de `used_bytes` sólo bajan


def _disputes_field(value: Any) -> dict[str, str] | None:
    """``{stream, target_id}`` si el registro es una disputa bien formada (la misma forma que ``disputes list``)."""

    if _valid_disputes(value):
        return {"stream": value["stream"], "target_id": value["target_id"]}
    return None


def recall(
    store: Any,
    query: str,
    *,
    budget: int = DEFAULT_BUDGET,
    scope: str = "repo",
    streams: tuple[str, ...] | list[str] | None = None,
    min_terms: int = 1,
) -> dict[str, Any]:
    """``recall-result-v1`` de ``query``; los errores salen como :class:`RecallError` (o los del store).

    ``min_terms`` (entero ≥ 1) excluye a los candidatos con menos de ``min_terms`` términos distintos de la consulta."""

    selected = _streams(streams)
    if not isinstance(min_terms, int) or isinstance(min_terms, bool) or min_terms < 1:
        raise RecallError("recall_min_terms_invalid")
    if scope not in SCOPES:
        raise RecallError("unsupported_recall_scope")
    gate = shared_reader_gate(store) if hasattr(store, "root") else nullcontext()
    with gate:
        return _under_gate(store, query, budget, scope, selected, min_terms)


__all__ = ["RESULT_SCHEMA", "RecallError", "recall", "render"]
