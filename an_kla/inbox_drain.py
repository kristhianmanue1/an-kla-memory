"""Vaciado de la bandeja en lote bajo ``write_lock`` (ADR-0063 D1, pasos 0 a 7), sin demonio.

``drain`` recolecta ``tmp/`` (candado de bandeja exclusivo y sin esperar), pide ``write_lock``
con plazo corto (``{"state": "queued"}`` si está ocupado) y, ya dentro, reconcilia los lotes en
vuelo (paso 0, ``inbox_close``), lee ``CURRENT`` y el snapshot, examina y valida las entradas
(``inbox_entries``), resuelve ``--supersedes`` (D3), deduplica, evalúa cada entrada sola con
las funciones puras, arma un lote homogéneo y lo compromete con
``write_commit._commit_write_plan_locked``. Un intento = un lote; ``drain`` repite intentos
soltando el candado entre lotes. El candado de bandeja no se toma teniendo ``write_lock``
(orden total de ``lock_order``).

Entradas malas: las que ninguna entrada produce sola (dos supersedes al mismo target) se
filtran con ``duplicate_supersede_targets``; si un lote aun así falla, la bisección por
prefijos, en memoria y sin soltar el candado, atribuye el fallo a una entrada (≤ ⌈log₂ n⌉
evaluaciones por entrada mala) y el resto va en un lote nuevo. Sólo si el lote falla con un
error que la evaluación pura no predijo (``duplicate_<stream>_id``, que nace en
``_assign_records``) se compromete entrada por entrada, con su marcador por commit.

Ninguna rama de resultado desconocido borra marcador ni entradas: lo resuelve el paso 0 del
vaciado siguiente. Los puntos de corte de las pruebas se instalan en el proceso del test,
nunca aquí.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from . import lock_order
from .custody import CustodyError
from .disputes import (
    build_remember_op,
    build_remember_plan,
    build_remember_proposal,
    duplicate_supersede_targets,
    resolve_supersede_target,
)
from .identity import IdentityError, _mutation_preflight_with_context
from .inbox import (
    InboxError,
    record_id as record_id_of,
    stream_for_kind,
    collect_tmp,
    ensure_layout,
    inbox_paths,
    is_entry_name,
    is_marker_name,
    marker_names,
    root_state,
    subdir_names,
)
from .inbox_close import (
    DrainAbort,
    delete_entries,
    delete_marker,
    reconcile_markers,
    settle_committed,
    write_marker,
)
from .inbox_anchors import record_fields
from .inbox_entries import Entry, Reject, age_key, kind_of_path, load_entry, reject_entry, safe_codes
from .inbox_ops import build_dispute_op, build_resolution_op, intent_mismatch
from .reader_gate import ReaderGateError
from .state_slot import StateAlready, resolve_state
from .store import STREAMS
from .store_errors import LockBusyError, StoreError
from .transaction_attempts import TransactionError
from .write_commit import _commit_write_plan_locked, _finish_locked_commit
from .write_policy import WritePolicyError, verify_write_plan

RESULT_SCHEMA = "an-kla/inbox-drain-result-v1"
# Espacio de nombres fijo y declarado del ``transaction_id`` de un lote: uuid5(NAMESPACE_DNS,
# "inbox.memory.an-kla.v1"). Los lotes se identifican por base y contenido, sin depender de él
# para saber qué journals son suyos (eso lo dice el marcador).
NS_AN_KLA_INBOX = uuid.UUID("0e5e62b5-3b89-5866-8492-bf023b220a6c")
MAX_BATCH_ENTRIES = 250
# Tope de nodos POR DOCUMENTO (la propuesta y el plan, cada uno; ADR-0063 D1 paso 5): margen sobre el
# `_MAX_JSON_NODES = 10_000` del núcleo, que también se aplica por documento.
MAX_DOCUMENT_NODES = 9000
DRAIN_LOCK_WAIT_SECONDS = 0.5
DEFAULT_BUDGET_SECONDS = 30.0
SCAN_CHUNK = 250
MAX_LISTED = 1000
_TERMINAL_STORE_PREFIXES = ("duplicate_", "missing_")
_KNOWN_INFRA = (LockBusyError, IdentityError, CustodyError, TransactionError, ReaderGateError)
# Fallos de preparación (preflight, layout, recolección de `tmp/`): se informan como `drain_error`.
_SETUP_ERRORS = (StoreError, IdentityError, TransactionError, ReaderGateError, InboxError, OSError)


class BatchFail(Exception):
    """El lote (o un prefijo) no pasa las funciones puras de política."""

    def __init__(self, code: str, reason_codes: list[str] | None = None, size: int = 0) -> None:
        super().__init__(code)
        self.code = code
        self.reason_codes = safe_codes(reason_codes or [])
        self.size = size


class CommitTerminal(Exception):
    """Error terminal de política o de asignación antes de que ``commit_locked`` escriba nada."""

    def __init__(self, code: str, reason_codes: list[str] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.reason_codes = safe_codes(reason_codes or [])


@dataclass
class Run:
    """Acumulador del informe de un ``drain`` (``inbox-drain-result-v1``)."""

    committed: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    already_committed: list[dict[str, Any]] = field(default_factory=list)
    duplicates_removed: list[str] = field(default_factory=list)
    batches: list[dict[str, Any]] = field(default_factory=list)
    closed_journals: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    finish: list[tuple[Any, Any]] = field(default_factory=list)
    ignored: int = 0
    attempts: int = 0
    queued_attempts: int = 0
    entry_evaluations: int = 0
    plan_evaluations: int = 0
    bisect_probes: int = 0
    one_by_one_commits: int = 0
    max_lock_seconds: float = 0.0
    drain_error: str | None = None
    unknown: bool = False
    tmp: dict[str, Any] = field(default_factory=dict)


# --- utilidades puras --------------------------------------------------------


def error_code(exc: BaseException) -> str:
    """Código estable de una excepción; nunca el mensaje crudo (puede llevar rutas)."""

    code = getattr(exc, "code", None)
    if isinstance(code, str) and code:
        return code
    if isinstance(exc, OSError):
        return "storage_io_failed"
    text = str(exc)
    if isinstance(exc, (StoreError, TransactionError, IdentityError, RuntimeError, ValueError)) and text:
        cleaned = safe_codes([text])
        if cleaned:
            return cleaned[0]
    return type(exc).__name__.lower()


def json_nodes(value: Any) -> int:
    count, stack = 0, [value]
    while stack:
        item = stack.pop()
        count += 1
        if isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, dict):
            stack.extend(item.values())
    return count


def batch_txid(base_revision: str, entries: list[Entry]) -> str:
    """``uuid5(NS_AN_KLA_INBOX, base_revision + sorted(digests))``; mismo lote y base, mismo id."""

    return str(uuid.uuid5(NS_AN_KLA_INBOX, base_revision + "".join(sorted(entry.digest for entry in entries))))


def plan_batch(base: str, entries: list[Entry], run: Run | None = None) -> dict[str, Any]:
    """Propuesta, autoridad ``model_derived``, decisión y plan con las funciones puras; sin escribir."""

    try:
        proposal = build_remember_proposal(base, [entry.op for entry in entries])
        built = build_remember_plan(proposal)
        if built["decision"]["decision"] == "skip":
            raise BatchFail("remember_policy_skip", built["decision"]["reason_codes"], len(entries))
        verify_write_plan(built["plan"], built["proposal"], built["authority"], built["decision"])
    except WritePolicyError as exc:
        raise BatchFail(exc.code, [exc.detail] if exc.detail else [], len(entries)) from None
    if run is not None:
        run.plan_evaluations += 1
    return built


def locate_culprit(base: str, entries: list[Entry], failure: BatchFail, run: Run) -> tuple[int, BatchFail]:
    """Bisección por prefijos: el prefijo más corto que falla termina en la entrada culpable.

    ``entries`` falla entero con ``failure``. Con n entradas son ⌈log₂ n⌉ evaluaciones. Por
    mitades no se atribuyen los fallos de par (las dos mitades pasan solas).
    """

    low, high = 0, len(entries)
    failures = {high: failure}
    while high - low > 1:
        mid = (low + high) // 2
        run.bisect_probes += 1
        try:
            plan_batch(base, entries[:mid])
            low = mid
        except BatchFail as exc:
            high = mid
            failures[mid] = exc
    return high - 1, failures[high]


def fit_batch(base: str, entries: list[Entry], run: Run) -> tuple[list[Entry], dict[str, Any]]:
    """Recorta a ≤ 250 entradas y al presupuesto de nodos por documento y devuelve el plan."""

    count = min(len(entries), MAX_BATCH_ENTRIES)
    while count > 1 and sum(json_nodes(e.op.record) + 8 for e in entries[:count]) > MAX_DOCUMENT_NODES:
        count -= 1
    while True:
        try:
            built = plan_batch(base, entries[:count], run)
        except BatchFail as exc:
            raise BatchFail(exc.code, exc.reason_codes, count) from None
        nodes = max(json_nodes(built["proposal"]), json_nodes(built["plan"]))
        if nodes <= MAX_DOCUMENT_NODES or count == 1:
            return entries[:count], built
        count = max(1, min(count - 1, count * MAX_DOCUMENT_NODES // nodes))


# --- exploración de pending/ (pasos 2 a 5) -----------------------------------


def _snapshot_index(snapshot: Any) -> dict[str, Any]:
    index: dict[str, Any] = {}
    for stream in ("facts", "events", "episodes"):
        for row in snapshot.records[stream]:
            index[str(row.get("id", ""))] = row
    return index


class Scanner:
    """Un intento: lee, valida, resuelve, deduplica y evalúa las entradas más antiguas."""

    def __init__(self, store: Any, snapshot: Any, observed: str, run: Run) -> None:
        self.store, self.snapshot, self.observed, self.run = store, snapshot, observed, run
        self.index = _snapshot_index(snapshot)
        self.by_stream = {stream: {str(row.get("id", "")): row for row in snapshot.records[stream]} for stream in STREAMS}
        self.seen: dict[str, Entry] = {}
        self.by_name: dict[str, Entry] = {}
        self.prefiltered: list[Entry] = []
        self.accepted: list[Entry] = []
        self.to_delete: list[str] = []
        self.touched_slots: set[str] = set()  # ADR-0065 §1: un `state` por casilla y transacción
        self.stop = False

    def reject(self, name: str, code: str, reason_codes: list[str] | None = None) -> None:
        final = reject_entry(self.store, name, code, reason_codes)
        self.run.rejected.append({"entry": name, "rejected_as": final, "code": code, "reason_codes": safe_codes(reason_codes or [])})
        # R2-03: la gemela de una entrada rechazada va también a `rejected/` con el mismo código.
        owner = self.by_name.get(name)
        for twin in (owner.extra.pop("twins", []) if owner is not None else []):
            self.reject(twin, code, reason_codes)

    def _resolve(self, entry: Entry) -> None:
        operation = entry.data.get("operation", "remember")
        if operation != "remember":
            build = build_dispute_op if operation == "dispute" else build_resolution_op
            entry.op = build(self.snapshot, entry.envelope, entry.data)
            return
        target = None
        if entry.target_id is not None:
            target = resolve_supersede_target(
                self.snapshot, entry.target_id, kind=entry.data["kind"],
                kind_explicit=entry.data["kind_explicit"], envelope=entry.envelope,
            )
        entry.op = build_remember_op(entry.envelope, entry.text, entry.data["kind"], target)
        entry.op.record.update(record_fields(entry.data))  # ADR-0066: anchors and coverage; nothing for a plain entry

    def _target_exists(self, target_id: str) -> bool:
        return any(str(row.get("id", "")) == target_id for stream in STREAMS for row in self.snapshot.raw_records[stream])

    def _prepare_state(self, entry: Entry) -> Entry | None:
        """Un ``state`` (ADR-0065): su casilla decide qué jubila y si es un reintento; no pasa por D3."""

        if entry.slot in self.touched_slots:
            # Segundo `state` de una casilla ya tocada en este lote: el vaciado parte aquí. Lo acumulado se
            # compromete y este (y lo que le sigue) se resuelve en el intento siguiente, contra la cabeza nueva.
            self.stop = True
            return None
        try:
            outcome = resolve_state(
                self.snapshot, envelope=entry.envelope, text=entry.text, key=entry.key, slot=entry.slot,
                target_id=entry.target_id, fields=record_fields(entry.data),
            )
        except WritePolicyError as exc:
            self.reject(entry.name, exc.code, [exc.detail] if exc.detail else [])
            return None
        if isinstance(outcome, StateAlready):
            self.to_delete.append(entry.name)
            item = {"entry": entry.name, "record_id": outcome.record_id}
            if outcome.retired_by is not None:
                item["retired_by"] = outcome.retired_by
            self.run.already_committed.append(item)
            return None
        entry.op = outcome
        self.touched_slots.add(entry.slot)
        self.by_name[entry.name] = entry
        return entry

    def _prepare(self, name: str) -> Entry | None:
        try:
            entry = load_entry(self.store, name)
        except Reject as rejected:
            self.reject(name, rejected.code, rejected.reason_codes)
            return None
        if entry is None:  # directorio: se ignora sin tocarlo
            return None
        if entry.data["kind"] == "state":
            return self._prepare_state(entry)
        # R1-01 de B5: un record con la misma clave y el mismo texto ya está en el snapshot: es un reintento
        # ya comprometido. Va ANTES de resolver `--supersedes` (el target propio ya está `sustituida` y la
        # resolución lo rechazaría con `invalid_supersede_target`): se borra sin evidencia en `rejected/`.
        # R2-01/R2-02 de B5: se busca por el `record.id` de la entrada EN SU PROPIO STREAM (el de su `kind`);
        # una clave igual en otro stream no cuenta. Con una `--idempotency-key` explícita reutilizada con otro
        # target del mismo stream es la misma intención (el target no se guarda en el record).
        stream = stream_for_kind(entry.data["kind"])
        done = self.by_stream[stream].get(record_id_of(stream, entry.key))
        if done is not None:
            envelope = done.get("an_kla_envelope")
            same_key = isinstance(envelope, dict) and envelope.get("idempotency_key") == entry.key and done.get("text") == entry.text
            if same_key and envelope.get("kind") != entry.data["kind"]:
                # #218 R3-01: `fact` y `decision` comparten stream y, con la misma clave, el mismo id; el `kind`
                # es parte de la intención y reutilizar la clave con otro es un rechazo, no un reintento.
                self.reject(name, "remember_id_collision", ["idempotency_key_other_kind"])
            elif same_key and intent_mismatch(done, entry.data):
                self.reject(name, "remember_id_collision", [intent_mismatch(done, entry.data)])  # ADR-0066 §2
            elif same_key and entry.target_id is not None and not self._target_exists(entry.target_id):
                # #218 R3-03: el target es parte de la intención; uno inexistente responde lo que respondería
                # sin el registro previo.
                self.reject(name, "invalid_supersede_target", ["target_missing"])
            elif same_key:
                self.to_delete.append(name)
                self.run.already_committed.append({"entry": name, "record_id": str(done.get("id", ""))})
            else:
                self.reject(name, "remember_id_collision", ["id_exists_in_snapshot"])
            return None
        try:
            self._resolve(entry)
        except WritePolicyError as exc:
            self.reject(name, exc.code, [exc.detail] if exc.detail else [])
            return None
        record_id = entry.op.record["id"]
        prior = self.seen.get(record_id)
        if prior is not None:
            if (prior.key, prior.payload) != (entry.key, entry.payload):
                self.reject(name, "remember_id_collision", ["same_id_other_payload"])
                return None
            fate = prior.extra.get("fate")
            if fate is None:  # la conservada sigue en juego: la gemela espera a su suerte (R2-03)
                prior.extra.setdefault("twins", []).append(name)
            elif fate[0] == "already":
                self.to_delete.append(name)
                self.run.already_committed.append({"entry": name, "record_id": record_id})
            else:
                self.reject(name, fate[1], fate[2])
            return None
        self.seen[record_id] = entry
        self.by_name[name] = entry
        existing = self.index.get(record_id)
        if existing is not None:
            envelope = existing.get("an_kla_envelope")
            same = isinstance(envelope, dict) and envelope.get("idempotency_key") == entry.key and existing.get("text") == entry.text
            if same and intent_mismatch(existing, entry.data):
                reason = [intent_mismatch(existing, entry.data)]
                entry.extra["fate"] = ("rejected", "remember_id_collision", reason)
                self.reject(name, "remember_id_collision", reason)
            elif same:
                entry.extra["fate"] = ("already",)
                self.to_delete.append(name)
                self.run.already_committed.append({"entry": name, "record_id": record_id})
            else:
                entry.extra["fate"] = ("rejected", "remember_id_collision", ["id_exists_in_snapshot"])
                self.reject(name, "remember_id_collision", ["id_exists_in_snapshot"])
            return None
        return entry

    def _evaluate(self, entry: Entry) -> bool:
        self.run.entry_evaluations += 1
        try:
            plan_batch(self.observed, [entry])
        except BatchFail as fail:
            self.reject(entry.name, fail.code, fail.reason_codes)
            return False
        return True

    def scan(self, names: list[str]) -> list[Entry]:
        for start in range(0, len(names), SCAN_CHUNK):
            candidates = []
            for candidate_name in names[start:start + SCAN_CHUNK]:
                prepared = self._prepare(candidate_name)
                if prepared:
                    candidates.append(prepared)
                if self.stop:
                    break
            if self.to_delete:
                delete_entries(self.store, self.to_delete)
                self.to_delete = []
            # R2-01: primero la evaluación por entrada (paso 5); el prefiltro sólo mira a las que
            # PASARON, así una rechazada por política nunca bloquea a otra válida.
            survivors = [entry for entry in candidates if self._evaluate(entry)]
            combined = self.prefiltered + survivors
            repeated = set(duplicate_supersede_targets([entry.op for entry in combined]))
            kept = []
            for position, entry in enumerate(combined):
                if position in repeated:
                    self.reject(entry.name, "supersedes:duplicate_target", [])
                elif position >= len(self.prefiltered):
                    kept.append(entry)
            self.prefiltered = [e for p, e in enumerate(combined) if p not in repeated]
            self.accepted += kept
            if self.stop or (self.accepted and self._first_group_full()):
                break
        return self.accepted

    def _first_group_full(self) -> bool:
        first = self.accepted[0].op
        return sum(1 for e in self.accepted if (e.op.stream, e.op.operation) == (first.stream, first.operation)) >= MAX_BATCH_ENTRIES


def select_group(accepted: list[Entry], include: str | None) -> list[Entry]:
    """Lote homogéneo (mismo stream y operación): el de la entrada pedida o el de la más antigua."""

    if not accepted:
        return []
    anchor = next((e for e in accepted if e.name == include), accepted[0])
    group = [e for e in accepted if (e.op.stream, e.op.operation) == (anchor.op.stream, anchor.op.operation)]
    if anchor not in group[:MAX_BATCH_ENTRIES]:  # la entrada pedida entra aunque no sea de las más antiguas
        group = sorted([anchor, *group[: MAX_BATCH_ENTRIES - 1]], key=lambda e: age_key(e.name))
    return group


# --- commit (pasos 6 y 7) ----------------------------------------------------


def _classify(store: Any, txid: str, exc: Exception) -> Exception:
    """Traduce una excepción de ``_commit_write_plan_locked`` según el paso 7 del ADR."""

    code = error_code(exc)
    if isinstance(exc, WritePolicyError) and code != "write_plan_base_changed":
        delete_marker(store, txid)
        return CommitTerminal(code, [exc.detail] if exc.detail else [])
    if isinstance(exc, StoreError) and code.startswith(_TERMINAL_STORE_PREFIXES):
        delete_marker(store, txid)
        return CommitTerminal(code)
    if isinstance(exc, (WritePolicyError, *_KNOWN_INFRA)):
        delete_marker(store, txid)
        return DrainAbort(code)
    # R1-04, conservador a propósito: una excepción de E/S lanzada DENTRO del commit (`OSError`,
    # `StorageOperationError`) o cualquier otra sin clasificar no prueba que `commit_locked` no
    # escribiera nada; es `unknown` y conserva el marcador. El paso 0 del vaciado siguiente lo resuelve
    # (sin rastro / no comprometido / comprometido). Las E/S que `commit_locked` devuelve como
    # resultado (`outcome.committed` false) sí son conocidas y borran el marcador (ver `commit_entries`).
    return DrainAbort(code, unknown=True)


def commit_entries(
    store: Any, lock_result: Any, preflight: Any, run: Run, observed: str,
    entries: list[Entry], built: dict[str, Any], mode: str,
) -> None:
    """Marcador, commit y resultado de un lote. Lanza ``CommitTerminal`` o ``DrainAbort``."""

    txid = batch_txid(observed, entries)
    names = [entry.name for entry in entries]
    twins = [twin for entry in entries for twin in entry.extra.get("twins", [])]
    write_marker(store, txid, observed, names)
    try:
        locked = _commit_write_plan_locked(
            store, lock_result, expected_current_hash=observed, plan=built["plan"],
            proposal=built["proposal"], authority=built["authority"], decision=built["decision"],
            transaction_id=txid, preflight=preflight,
        )
    except Exception as exc:
        raise _classify(store, txid, exc) from None
    if locked.final is not None:
        if locked.final.get("committed") is not True:  # `skip` del lote: nada se escribió
            delete_marker(store, txid)
            raise CommitTerminal("remember_policy_skip", locked.final.get("reason_codes"))
        revision = locked.final["revision"]
        # R1-09: el replay pasa por el mismo predicado que la rama normal (durabilidad completa).
        state = (locked.final.get("outcome") or {}).get("state", "committed")
    else:
        outcome = locked.outcome
        revision, state = locked.revision, outcome["state"]
        if outcome["committed"] is False:
            delete_marker(store, txid)
            raise DrainAbort(outcome.get("operation_error_code") or "not_committed")
        if outcome["committed"] is None:
            raise DrainAbort(outcome.get("operation_error_code") or "outcome_unknown", unknown=True)
        run.finish.append((lock_result, locked))
    if state == "committed":
        delete_entries(store, names + twins)
        delete_marker(store, txid)
    else:  # durabilidad o auditoría incompletas: cierra, repara y borra como el paso 0
        settle_committed(store, txid, names + twins, run.warnings)
    run.duplicates_removed.extend(twins)  # R2-03: sólo se informan como borradas si la conservada se comprometió
    run.batches.append({"transaction_id": txid, "mode": mode, "stream": entries[0].op.stream,
                        "operation": entries[0].op.operation, "entries": len(entries), "revision": revision})
    for entry in entries:
        run.committed.append({"entry": entry.name, "record_id": entry.op.record["id"], "revision": revision,
                              "stream": entry.op.stream, "operation": entry.op.operation, **entry.op.result_fields()})


def commit_one_by_one(store: Any, lock_result: Any, preflight: Any, run: Run, entries: list[Entry], scanner: Scanner) -> None:
    """Último recurso: un commit por entrada, releyendo ``CURRENT``, con marcador por commit."""

    for entry in entries:
        observed = store.read_current()
        try:
            built = plan_batch(observed, [entry], run)
            commit_entries(store, lock_result, preflight, run, observed, [entry], built, "one_by_one")
        except BatchFail as fail:
            scanner.reject(entry.name, fail.code, fail.reason_codes)
        except CommitTerminal as terminal:
            scanner.reject(entry.name, terminal.code, terminal.reason_codes)
        else:
            run.one_by_one_commits += 1


def process_group(
    store: Any, lock_result: Any, preflight: Any, run: Run, observed: str, group: list[Entry], scanner: Scanner,
) -> None:
    entries: list[Entry] = list(group)
    while entries:
        try:
            batch, built = fit_batch(observed, entries, run)
            break
        except BatchFail as fail:  # bisección por prefijos: nada se escribe
            index, culprit = locate_culprit(observed, entries[: fail.size], fail, run)
            scanner.reject(entries[index].name, culprit.code, culprit.reason_codes)
            del entries[index]
    else:
        return
    try:
        commit_entries(store, lock_result, preflight, run, observed, batch, built, "batch")
    except CommitTerminal:
        commit_one_by_one(store, lock_result, preflight, run, batch, scanner)


# --- un intento y el bucle ---------------------------------------------------


def processable_names(store: Any) -> list[str]:
    """«Entrada» = nombre que casa el patrón y NO es directorio (R1-10): con independencia de si
    ``inbox.entry_names`` cuenta o no los directorios con nombre de entrada, el vaciado sólo procesa
    archivos (regulares o no: los no seguros van a ``rejected/``)."""

    # R2-02: enumeración propia de `pending/` (scandir + lstat, sin abrir), independiente de la
    # semántica de `inbox.entry_names`: un FIFO, enlace o hardlink con nombre de entrada se procesa
    # (y va a `rejected/`) con cualquier definición de «vacío» que adopten B1 o B4.
    pending = inbox_paths(store).pending
    return [name for name in subdir_names(store, "pending") if is_entry_name(name) and kind_of_path(pending / name) in ("ok", "unsafe")]


def count_ignored(store: Any) -> int:
    """Lo que el vaciado no toca: directorios y nombres que no casan, en ``pending/`` e ``inflight/``."""

    paths = inbox_paths(store)
    total = 0
    for directory, matches in ((paths.pending, is_entry_name), (paths.inflight, is_marker_name)):
        try:
            names = os.listdir(directory)
        except OSError:
            continue
        total += sum(1 for n in names if not matches(n) or kind_of_path(directory / n) == "dir")
    return total


def _safe_ignored(store: Any, run: Run) -> int:
    """``count_ignored`` fuera de los manejadores de error (#218 R3-04): su fallo es `drain_error`, no una línea."""

    try:
        return count_ignored(store)
    except _SETUP_ERRORS as exc:
        run.drain_error = run.drain_error or error_code(exc)
        return 0


def _has_work(store: Any) -> bool:
    return bool(marker_names(store)) or bool(processable_names(store))


def _include_is_state(store: Any, include: str | None) -> bool:
    """Un ``state`` no se adelanta en la cola: gana el último encolado, en orden de la bandeja (ADR-0065 §3)."""

    if include is None:
        return False
    try:
        entry = load_entry(store, include)
    except Reject:
        return False
    return entry is not None and entry.data["kind"] == "state"


def _pending_names(store: Any, include: str | None) -> list[str]:
    names = sorted(processable_names(store), key=age_key)
    if include in names and not _include_is_state(store, include):
        names.remove(include)
        names.insert(0, include)
    return names


def _locked_attempt(store: Any, lock_result: Any, preflight: Any, run: Run, include: str | None) -> bool:
    """Pasos 0 a 7 con ``write_lock`` tomado. ``True`` si hubo progreso (commit, rechazo o borrado)."""

    marks = len(run.committed) + len(run.rejected) + len(run.duplicates_removed) + len(run.already_committed)
    run.closed_journals.extend(reconcile_markers(store, run.warnings))
    observed = store.read_current()
    snapshot = store.snapshot(observed)
    scanner = Scanner(store, snapshot, observed, run)
    accepted = scanner.scan(_pending_names(store, include))
    group = select_group(accepted, include)
    if group:
        process_group(store, lock_result, preflight, run, observed, group, scanner)
    return len(run.committed) + len(run.rejected) + len(run.duplicates_removed) + len(run.already_committed) > marks


def attempt(store: Any, run: Run, include: str | None, lock_wait: float) -> str:
    """``idle`` | ``progress`` | ``queued`` | ``aborted``. Un intento = un lote."""

    run.attempts += 1
    try:
        if not _has_work(store):
            return "idle"
        preflight = _mutation_preflight_with_context(store)
        store._make_layout()
        ensure_layout(store)
    except _SETUP_ERRORS as exc:  # R3-06 de B2: infraestructura, nunca traza; nada se tocó
        run.drain_error = error_code(exc)
        return "aborted"
    acquired = False
    started = 0.0
    try:
        with store.write_lock(deadline=lock_wait) as lock_result:
            acquired, started = True, time.monotonic()
            try:
                progress = _locked_attempt(store, lock_result, preflight, run, include)
            except DrainAbort as abort:
                run.drain_error, run.unknown = abort.code, abort.unknown
                return "aborted"
            except (StoreError, IdentityError, TransactionError, ReaderGateError, InboxError, OSError) as exc:
                run.drain_error = error_code(exc)  # lectura de CURRENT/snapshot: infraestructura, no rechazo
                return "aborted"
            finally:
                run.max_lock_seconds = max(run.max_lock_seconds, time.monotonic() - started)
    except LockBusyError:
        if acquired:
            raise
        run.queued_attempts += 1
        return "queued"
    except _SETUP_ERRORS as exc:  # #218 R3-02: el candado no se pudo abrir (o soltar): `drain_error`, sin ruta
        if acquired:
            raise
        run.drain_error = error_code(exc)
        return "aborted"
    finally:
        _finish_commits(store, run)
    return "progress" if progress else "idle"


def _finish_commits(store: Any, run: Run) -> None:
    """Post-proceso común de ``write_commit`` tras soltar el candado, en el orden de los commits."""

    pending, run.finish = run.finish, []
    for lock_result, locked in pending:
        try:
            result = _finish_locked_commit(store, lock_result, locked)
        except Exception:
            run.warnings.append("post_commit_incomplete")
            continue
        run.warnings.extend(result.get("outcome", {}).get("warnings", []))


def drain(
    store: Any,
    *,
    budget_seconds: float = DEFAULT_BUDGET_SECONDS,
    lock_wait_seconds: float = DRAIN_LOCK_WAIT_SECONDS,
    include_entry: str | None = None,
    max_batches: int | None = None,
    clock: Any = time.monotonic,
) -> dict[str, Any]:
    """Vacía la bandeja en lotes sucesivos soltando el candado entre lotes (``inbox-drain-result-v1``).

    Termina con ``pending/`` sin entradas procesables, al agotar ``budget_seconds`` (se mira entre
    lotes), con ``max_batches`` lotes comprometidos, con ``write_lock`` ocupado (``queued``) o al
    abortar (``drain_error`` / ``outcome: unknown``). ``include_entry`` hace que la entrada pedida
    vaya en el primer lote: ``remember`` pasa su nombre y ``max_batches=1``.
    """

    lock_order.require_inbox_allowed(store)
    run = Run()
    try:
        top = root_state(store)
    except _SETUP_ERRORS as exc:  # R2-03 de B5: ningún fallo de la raíz sale como línea de error
        run.drain_error = error_code(exc)
        return _result(run, "aborted", "present")
    if top == "unsafe":
        run.drain_error = "inbox_unsafe_path"
        return _result(run, "aborted", "present")
    if top == "absent":
        return _result(run, "drained", "absent")
    try:
        run.tmp = collect_tmp(store)
    except _SETUP_ERRORS as exc:  # R3-06 de B2: el vaciado informa `drain_error`, no una traza
        run.drain_error = error_code(exc)
        run.ignored = _safe_ignored(store, run)
        return _result(run, "aborted", "present")
    deadline = clock() + budget_seconds
    state = "drained"
    while True:
        status = attempt(store, run, include_entry, lock_wait_seconds)
        if status == "idle":
            break
        if status == "queued":
            state = "queued"
            break
        if status == "aborted":
            state = "aborted"
            break
        if (max_batches is not None and len(run.batches) >= max_batches) or clock() >= deadline:
            try:
                state = "partial" if _has_work(store) else "drained"
            except _SETUP_ERRORS as exc:  # R2-03: ni `partial` silencioso ni traza
                run.drain_error = error_code(exc)
                state = "aborted"
            break
    run.ignored = _safe_ignored(store, run)
    if run.drain_error is not None:
        state = "aborted"
    return _result(run, state, "present")


def _with_retired_by(committed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """``retired_by``: el ``state`` de este mismo vaciado que jubiló a cada uno de los comprometidos (ADR-0065 §1)."""

    retirers = {c["retired"]["id"]: c["record_id"] for c in committed if "retired" in c}
    return [{**c, "retired_by": retirers[c["record_id"]]} if c["record_id"] in retirers else c for c in committed]


def _capped(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"count": len(items), "entries": items[:MAX_LISTED], "truncated": len(items) > MAX_LISTED}


def _result(run: Run, state: str, inbox: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "untrusted_memory_data": True,
        "state": state,
        "inbox": inbox,
        "outcome": "unknown" if run.unknown else "known",
        "queued": state == "queued" or run.queued_attempts > 0,
        "committed": _capped(_with_retired_by(run.committed)),
        "rejected": _capped(run.rejected),
        "already_committed": _capped(run.already_committed),
        "duplicates_removed": {
            "count": len(run.duplicates_removed), "names": run.duplicates_removed[:MAX_LISTED],
            "truncated": len(run.duplicates_removed) > MAX_LISTED,
        },
        "batches": run.batches[:MAX_LISTED],
        "closed_journals": run.closed_journals[:MAX_LISTED],
        "warnings": sorted(set(run.warnings)),
        "tmp": run.tmp,
        "metrics": {
            "attempts": run.attempts, "queued_attempts": run.queued_attempts, "ignored": run.ignored,
            "entry_evaluations": run.entry_evaluations, "plan_evaluations": run.plan_evaluations,
            "bisect_probes": run.bisect_probes, "one_by_one_commits": run.one_by_one_commits,
            "max_write_lock_seconds": round(run.max_lock_seconds, 6),
        },
    }
    if run.drain_error is not None:
        result["drain_error"] = run.drain_error
    return result


__all__ = [
    "DEFAULT_BUDGET_SECONDS", "DRAIN_LOCK_WAIT_SECONDS", "MAX_BATCH_ENTRIES", "NS_AN_KLA_INBOX", "RESULT_SCHEMA",
    "batch_txid", "drain",
]
