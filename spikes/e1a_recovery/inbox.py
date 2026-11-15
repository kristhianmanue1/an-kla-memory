"""Spike E1.a-B2: vaciado mínimo de bandeja según D1 del ADR-0063.

Código de prototipo: NUNCA se fusiona. Todo punto de corte vive aquí (variable
de entorno ``SPIKE_CUT``), nunca en el camino de producción de ``an_kla``.

Lo que se tuvo que sacar de ``an_kla/write_commit.py`` para comprometer con el
candado tomado: el cuerpo de ``commit_write_plan`` entre ``with
store.write_lock()`` y ``store._commit_locked`` (líneas 84-189), sin la
rama de replay por CAS (bajo el candado ``observed`` se lee aquí, no se espera
de fuera) ni el post-proceso tras soltar (``_post_lock_outcome``,
``_maybe_reindex``, ``_context_diagnostics``).
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import hashlib
import json
import os
import random
import re
import signal
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterator

from an_kla import transactions as tx
from an_kla.canonical import canonical_json, digest_json
from an_kla.identity import _mutation_preflight_with_context, assert_unchanged
from an_kla.store_errors import LockBusyError
from an_kla.subject_binding import check_subject_ref_binding
from an_kla.supersede import resolve_supersede_targets
from an_kla.transaction_attempts import begin_transaction
from an_kla.write_policy import (
    WritePolicyError,
    build_write_plan,
    evaluate_write,
    verify_write_plan,
)

NS_INBOX = uuid.uuid5(uuid.NAMESPACE_DNS, "an-kla.inbox.spike")
NAME_RE = re.compile(r"^[0-9]+-[0-9]+-[0-9a-f]{16}-[0-9a-f]{8}\.json$")
DIGEST_B = "sha256:" + "b" * 64
MAX_BATCH = 250


class DrainAbort(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


# ---------------------------------------------------------------- cortes
def cut(point: str) -> None:
    """``kill -9`` real sobre el propio proceso si ``SPIKE_CUT`` coincide."""
    if os.environ.get("SPIKE_CUT") == point:
        os.kill(os.getpid(), signal.SIGKILL)


def install_cuts(store: Any) -> None:
    """Envuelve métodos de la instancia (no del código de producción)."""
    original_replace = store._replace_current
    original_write_tx = store._write_transaction

    def replace_current(identifier: str) -> None:
        cut("pre_replace_current")
        original_replace(identifier)
        cut("post_replace_current")

    def write_transaction(txid: str, body: Any) -> None:
        if body.get("stage") == "committed" and body.get("observed_log") is None:
            cut("pre_committed_journal")
        original_write_tx(txid, body)

    store._replace_current = replace_current
    store._write_transaction = write_transaction


# ---------------------------------------------------------------- rutas
class Inbox:
    def __init__(self, store: Any) -> None:
        self.store = store
        self.root = Path(store.root) / "inbox"
        self.tmp = self.root / "tmp"
        self.pending = self.root / "pending"
        self.inflight = self.root / "inflight"
        self.rejected = self.root / "rejected"
        self.lock_path = self.root / ".lock"

    def make(self) -> None:
        for d in (self.tmp, self.pending, self.inflight, self.rejected):
            d.mkdir(parents=True, exist_ok=True)


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


# ---------------------------------------------------------------- candados
@contextlib.contextmanager
def inbox_lock(inbox: Inbox, *, exclusive: bool, deadline: float = 0.0) -> Iterator[bool]:
    """Candado de bandeja; rinde ``True`` si lo obtuvo (``False`` si ocupado)."""
    inbox.make()
    with inbox.lock_path.open("a+b") as handle:
        mode = (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB
        end = time.monotonic() + deadline
        while True:
            try:
                fcntl.flock(handle.fileno(), mode)
                got = True
                break
            except OSError:
                if time.monotonic() >= end:
                    got = False
                    break
                time.sleep(0.01)
        try:
            yield got
        finally:
            if got:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def write_lock_deadline(root: Path, deadline: float) -> Iterator[None]:
    """Copia de ``store_locks.write_lock`` con plazo parametrizable.

    Es el «parámetro opcional nuevo de write_lock» que pide D1; se prototipa
    aquí en vez de tocar ``store_locks.py``.
    """
    with (root / ".write.lock").open("a+b") as handle:
        end = time.monotonic() + deadline
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if time.monotonic() >= end:
                    raise LockBusyError("write_lock_busy") from exc
                time.sleep(0.01)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


# ---------------------------------------------------------------- encolar
def publish(tmp: Path, dest: Path, mode: str) -> None:
    """Publica ``tmp`` en ``dest``. ``replace`` = D1 r4; ``lstat`` y ``link``
    son las alternativas de H7."""
    if mode == "replace":
        os.replace(tmp, dest)
    elif mode == "lstat":
        try:
            os.lstat(dest)
        except FileNotFoundError:
            os.replace(tmp, dest)
        else:
            raise FileExistsError(errno.EEXIST, "pending_name_taken", str(dest))
    elif mode == "link":
        os.link(tmp, dest)  # EEXIST si el nombre existe: nunca sobrescribe
        os.unlink(tmp)
    else:
        raise ValueError(mode)


def enqueue(
    store: Any,
    text: str,
    *,
    key: str | None = None,
    kind: str = "fact",
    publish_mode: str = "replace",
    name: str | None = None,
    preflight: bool = True,
) -> dict[str, Any]:
    inbox = Inbox(store)
    t0 = time.perf_counter()
    if preflight:
        _mutation_preflight_with_context(store)
    key = key or hashlib.sha256(
        canonical_json({"kind": kind, "text": text})
    ).hexdigest()
    with inbox_lock(inbox, exclusive=False, deadline=2.0) as got:
        if not got:
            return {"state": "failed", "code": "inbox_busy"}
        if preflight:
            _mutation_preflight_with_context(store)
        payload = {
            "schema": "an-kla/inbox-entry-v1",
            "text": text,
            "kind": kind,
            "key": key,
            "payload_sha256": hashlib.sha256(
                canonical_json({"text": text, "kind": kind, "target": None})
            ).hexdigest(),
            "enqueued_ns": time.time_ns(),
        }
        data = json.dumps(payload, sort_keys=True).encode()
        entry_name = name or (
            f"{time.time_ns()}-{os.getpid()}-{key[:16]}-{random.getrandbits(32):08x}.json"
        )
        tmp = inbox.tmp / entry_name
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        cut("enq_tmp")
        publish(tmp, inbox.pending / entry_name, publish_mode)
        _fsync_dir(inbox.pending)
    return {
        "state": "queued",
        "entry": entry_name,
        "key": key,
        "elapsed": time.perf_counter() - t0,
    }


# ---------------------------------------------------------------- recolector
def collect_tmp_by_lock(inbox: Inbox) -> int:
    """Recolector sin reloj: un ``flock`` exclusivo no bloqueante sólo se obtiene
    si no hay ningún encolador vivo (el SO suelta el candado al morir, también
    con ``kill -9``), así que todo lo que hay en ``tmp/`` es huérfano."""
    removed = 0
    with inbox_lock(inbox, exclusive=True, deadline=0.0) as got:
        if not got:
            return 0
        for path in inbox.tmp.iterdir():
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
                removed += 1
    return removed


def collect_tmp_by_age(inbox: Inbox, min_age: float) -> int:
    """Recolector con antigüedad mínima (la alternativa que pide el mandato)."""
    removed = 0
    now = time.time()
    for path in inbox.tmp.iterdir():
        try:
            if now - path.lstat().st_mtime >= min_age:
                path.unlink()
                removed += 1
        except FileNotFoundError:
            pass
    return removed


# ---------------------------------------------------------------- cierre de journal (H5)
def _read_journal(store: Any, txid: str) -> dict[str, Any] | None:
    j = tx._journal(store, txid)
    return None if j is None or j.get("corrupt") else dict(j)


def close_committed_journal(store: Any, txid: str) -> dict[str, Any]:
    """Cierra como ``committed`` un journal cuyo candidato ya es CURRENT/ancestro.

    Sigue el patrón de ``compaction._reconcile_committed_journal`` (aislado de
    ``CompactionError``/``planning``): reescribe ``stage``, completa
    ``observed_log`` y **nunca fabrica recibos**: sólo enlaza los que existen y
    validan en disco (el corte entre ``_replace_current`` y ``write_receipt``
    deja el recibo ``current-durable`` sin escribir: el journal queda
    ``committed`` con ``current_receipt: None`` y ``inspect_transaction`` lo
    informa ``durability_incomplete``).
    """
    info = tx.inspect_transaction(store, txid)
    if info.get("committed") is not True:
        raise DrainAbort("transaction_not_committed", str(info.get("state")))
    journal = _read_journal(store, txid)
    candidate = info["candidate_revision"]
    if journal is None:
        # el journal falta/corrupto pero hay stage inmutable: se reconstruye
        stage = tx._stage_evidence(store, txid, candidate)
        if stage is None:
            raise DrainAbort("transaction_evidence_missing_or_invalid")
        journal = {
            "stage": "candidate_prepared",
            "parent": stage["parent"],
            "candidate": candidate,
            "attempt": stage["attempt"],
            "candidate_receipt": None,
            "current_receipt": None,
        }
        if "write_policy" in stage:
            journal["write_policy"] = stage["write_policy"]
    attempt = tx.validate_attempt(journal["attempt"])
    if journal.get("stage") == "committed" and isinstance(journal.get("observed_log"), str):
        return {"closed": False, "reason": "already_committed", "state": info["state"]}
    parent = journal.get("parent") or attempt.get("base_revision")
    # enlazar sólo recibos reales y válidos
    for rid in tx._receipt_ids(store, txid):
        ident = "sha256:" + rid.removeprefix("sha256:")
        for kind, field in (("candidate-data-durable", "candidate_receipt"),
                            ("current-durable", "current_receipt")):
            if journal.get(field) is None or not tx._valid_receipt(
                    store, txid, journal.get(field), attempt, candidate, kind):
                if tx._valid_receipt(store, txid, ident, attempt, candidate, kind):
                    journal[field] = ident
    journal["stage"] = "committed"
    if not isinstance(journal.get("observed_log"), str):
        intent_id = store._write_ref_log({
            "schema": "an-kla/ref-log-v1", "kind": "intent",
            "transaction_id": txid, "parent": parent, "candidate": candidate,
        })
        journal["observed_log"] = store._write_ref_log({
            "schema": "an-kla/ref-log-v1", "kind": "observed_commit",
            "transaction_id": txid, "parent": parent, "candidate": candidate,
            "intent": intent_id,
        })
    store._write_transaction(txid, journal)
    after = tx.inspect_transaction(store, txid)
    return {"closed": True, "state": after["state"],
            "durability_state": after["durability_state"]}


def never_started(store: Any, txid: str) -> bool:
    """Evidencia de que la transacción no dejó ningún rastro (rama ``None``).

    ``inspect_transaction`` da ``committed: None`` (``transaction_evidence_
    missing_or_invalid``) cuando el corte ocurre tras escribir el marcador y
    antes del journal ``prepared``. Como el journal ``prepared`` es lo PRIMERO
    que escribe ``commit_locked`` (antes de segmentos, manifiesto y CURRENT), su
    ausencia sin candidato ni ``stages/`` prueba que nada se comprometió.
    """
    if tx._journal(store, txid) is not None:
        return False
    if tx._manifest_candidates(store, txid):
        return False
    return not (Path(store.root) / "transactions" / txid).exists()


# ---------------------------------------------------------------- paso 0
def reconcile_markers(
    store: Any, inbox: Inbox, *, close_mode: str, none_mode: str, report: dict[str, Any]
) -> None:
    """Paso 0. ``close_mode``: ``noop`` (ruta de replay del ADR r4, no escribe)
    | ``write`` (cierre del spike). ``none_mode``: ``drop`` (ADR literal) |
    ``abort`` (prescripción r4) | ``smart`` (spike)."""
    inbox.make()
    for marker in sorted(inbox.inflight.glob("*.json")):
        txid = marker.stem
        try:
            data = json.loads(marker.read_bytes())
        except (OSError, ValueError):
            raise DrainAbort("inflight_marker_unreadable", marker.name)
        info = tx.inspect_transaction(store, txid)
        committed = info.get("committed")
        if committed is True:
            if close_mode in ("write", "write+repair"):
                closed = close_committed_journal(store, txid)
                if close_mode == "write+repair" and closed.get("durability_state") == "incomplete":
                    from an_kla.transaction_repair import repair_durability
                    fixed = repair_durability(store, txid)  # fsync de CURRENT + recibo `repair`
                    closed["after_repair"] = fixed["state"]
                report.setdefault("closed", []).append(closed)
            else:
                # ruta citada por el ADR: _commit_locked retorna sin escribir
                report.setdefault("closed", []).append({"closed": False, "reason": "noop"})
            _delete_entries(inbox, data["entries"])
            marker.unlink()
            _fsync_dir(inbox.inflight)
        elif committed is False:
            marker.unlink()
            _fsync_dir(inbox.inflight)
            report.setdefault("dropped", []).append(txid)
        else:
            code = info.get("operation_error_code")
            if none_mode == "drop":
                marker.unlink()
                _fsync_dir(inbox.inflight)
                report.setdefault("dropped_none", []).append(txid)
            elif none_mode == "smart" and never_started(store, txid):
                marker.unlink()
                _fsync_dir(inbox.inflight)
                report.setdefault("never_started", []).append(txid)
            else:
                raise DrainAbort(f"transaction_{code}", txid)


def _delete_entries(inbox: Inbox, names: list[str]) -> None:
    for i, name in enumerate(names):
        with contextlib.suppress(FileNotFoundError):
            (inbox.pending / name).unlink()
        if i == 0:
            cut("mid_delete")
    _fsync_dir(inbox.pending)


# ---------------------------------------------------------------- lote
def build_batch(
    base: str, entries: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    proposal = {
        "schema": "an-kla/write-proposal-v2",
        "base_revision": base,
        "stream": "facts",
        "operation": "add",
        "requested_representation": "summary",
        "records": [{"id": "f-r-" + e["key"][:24], "text": e["text"]} for e in entries],
        "lineage": {"derived_from_retrieval": False, "refs": []},
    }
    authority = {
        "schema": "an-kla/write-authority-v1",
        "proposal_sha256": digest_json(proposal),
        "base_revision": base,
        "authority_class": "model_derived",
        "issuer": {"kind": "model", "id": "spike-b2", "configuration_fingerprint": DIGEST_B},
        "evidence": [],
        "scope": {"streams": ["facts"], "representations": ["summary"], "operations": ["add"]},
    }
    decision = evaluate_write(proposal, authority)
    plan = build_write_plan(proposal, authority, decision)
    return proposal, authority, decision, plan


def commit_batch_locked(
    store: Any, preflight: Any, observed: str, proposal: Any, authority: Any,
    decision: Any, plan: Any, txid: str,
) -> tuple[str, dict[str, Any]]:
    """Cuerpo bloqueado mínimo de ``commit_write_plan`` (ver docstring del módulo)."""
    store_identity = assert_unchanged(store, preflight.binding, observed)
    plan, proposal, authority, decision = map(deepcopy, (plan, proposal, authority, decision))
    verify_write_plan(plan, proposal, authority, decision)
    if (proposal["base_revision"] != observed or authority["base_revision"] != observed
            or plan["core"]["base_revision"] != observed):
        raise WritePolicyError("write_plan_base_changed")
    if decision["decision"] == "skip":
        return observed, {"committed": False, "state": "skip",
                          "reason_codes": decision["reason_codes"]}
    pending_supersedes = resolve_supersede_targets(store, plan, observed)
    check_subject_ref_binding(plan, preflight.binding)
    pending: dict[str, list[dict[str, Any]]] = {"facts": [], "events": [], "episodes": []}
    for item in plan["records"]:
        pending[item["stream"]].append(deepcopy(item["record"]))
    policy_metadata = {
        "schema": "an-kla/write-policy-transaction-v1",
        "plan_fingerprint": plan["plan_fingerprint"],
        "proposal_sha256": decision["proposal_sha256"],
        "authority_sha256": decision["authority_sha256"],
        "policy_fingerprint": decision["policy_fingerprint"],
        "decision": decision["decision"],
        "reason_codes": deepcopy(decision["reason_codes"]),
    }
    attempt = begin_transaction(
        "write", transaction_id=txid, base_revision=observed,
        plan_fingerprint=plan["plan_fingerprint"],
    )
    return store._commit_locked(
        observed=observed, checkpoint_patch={}, pending=pending, attempt=attempt,
        policy_metadata=policy_metadata, supersedes=pending_supersedes or None,
        store_identity=store_identity, _context=preflight.context,
    )


# ---------------------------------------------------------------- listar
def list_entries(inbox: Inbox, report: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    result = []
    for path in sorted(inbox.pending.iterdir(), key=lambda p: p.name):
        if not NAME_RE.match(path.name):
            continue
        st = os.lstat(path)
        if not (st.st_mode & 0o170000 == 0o100000) or st.st_nlink != 1:
            report.setdefault("rejected", []).append((path.name, "inbox_entry_unsafe"))
            continue
        try:
            entry = json.loads(path.read_bytes())
            assert entry["schema"] == "an-kla/inbox-entry-v1"
        except Exception:
            report.setdefault("rejected", []).append((path.name, "inbox_entry_invalid"))
            continue
        result.append((path.name, entry))
    return result


# ---------------------------------------------------------------- vaciar
def drain_once(
    store: Any,
    *,
    close_mode: str = "write",
    none_mode: str = "smart",
    lock_deadline: float = 0.0,
    max_batch: int = MAX_BATCH,
    collect: bool = True,
) -> dict[str, Any]:
    inbox = Inbox(store)
    inbox.make()
    report: dict[str, Any] = {"state": "idle", "cas_conflicts": 0}
    if collect:
        report["tmp_collected"] = collect_tmp_by_lock(inbox)
    preflight = _mutation_preflight_with_context(store)
    install_cuts(store)
    try:
        with write_lock_deadline(Path(store.root), lock_deadline):
            t_lock = time.perf_counter()
            try:
                reconcile_markers(store, inbox, close_mode=close_mode,
                                  none_mode=none_mode, report=report)
                observed = store.read_current()
                listed = list_entries(inbox, report)[:max_batch]
                if not listed:
                    return report
                # paso 4 mínimo: dedupe por id (clave) conservando la más antigua
                seen: dict[str, str] = {}
                entries, names = [], []
                for name, entry in listed:
                    if entry["key"][:24] in seen:
                        continue
                    seen[entry["key"][:24]] = name
                    entries.append(entry)
                    names.append(name)
                snapshot = store.snapshot(observed)
                known = {str(r["id"]) for r in snapshot.records["facts"]}
                keep = [(n, e) for n, e in zip(names, entries)
                        if "f-r-" + e["key"][:24] not in known]
                already = [n for n, e in zip(names, entries)
                           if "f-r-" + e["key"][:24] in known]
                _delete_entries(inbox, already)  # ya comprometidas (reintento idempotente)
                if not keep:
                    report["state"] = "idle"
                    return report
                names = [n for n, _ in keep]
                entries = [e for _, e in keep]
                proposal, authority, decision, plan = build_batch(observed, entries)
                txid = str(uuid.uuid5(
                    NS_INBOX, observed + "".join(sorted(digest_json(e) for e in entries))))
                marker = inbox.inflight / f"{txid}.json"
                store._atomic_write(marker, canonical_json({
                    "txid": txid, "base_revision": observed, "entries": names}))
                cut("post_marker")
                revision, outcome = commit_batch_locked(
                    store, preflight, observed, proposal, authority, decision, plan, txid)
                report["outcome"] = {k: outcome.get(k) for k in
                                     ("state", "committed", "operation_error_code")}
                if outcome.get("committed") is True:
                    cut("post_journal")
                    _delete_entries(inbox, names)
                    cut("post_entries_deleted")
                    marker.unlink()
                    _fsync_dir(inbox.inflight)
                    report["state"] = "committed"
                    report["committed"] = len(names)
                elif outcome.get("committed") is False and outcome.get("state") != "skip":
                    # no se comprometió y se sabe: el marcador sobra
                    marker.unlink()
                    _fsync_dir(inbox.inflight)
                    report["state"] = "aborted"
                    report["drain_error"] = outcome.get("operation_error_code")
                else:
                    report["state"] = "aborted"
                    report["drain_error"] = outcome.get("operation_error_code")
                    report["outcome_unknown"] = outcome.get("committed") is None
            except DrainAbort as exc:
                report["state"] = "aborted"
                report["drain_error"] = exc.code
            except WritePolicyError as exc:
                if exc.code == "write_plan_base_changed":
                    report["cas_conflicts"] += 1
                report["state"] = "aborted"
                report["drain_error"] = exc.code
            except Exception as exc:  # error de E/S o de store: aborta, no rechaza
                report["state"] = "aborted"
                report["drain_error"] = getattr(exc, "code", type(exc).__name__)
            finally:
                report["lock_hold"] = time.perf_counter() - t_lock
    except LockBusyError:
        report["state"] = "queued"
        report["lock_busy"] = True
    return report
