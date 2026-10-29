"""Local immutable revisions for the AN-KLA beta.

The implementation intentionally supports one local memory.  CURRENT is the
only commit authority; ref-log entries are diagnostic objects only.
"""

from __future__ import annotations

from .revision_walk import _OperationContext

from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import uuid
from typing import Any, Iterable, Iterator, Mapping

from . import attest as attest_module
from .canonical import bare_digest, canonical_json, digest_bytes, digest_json
from .checkpoint_policy import CheckpointPolicyError, validate_working_state
from .compaction_store_mixin import CompactionStoreMixin
from .context_package import context_status
from .custody import (
    POINTER_NAME, CustodyError, clear_bind_intent, project_local_vault_present,
    read_bind_intent, read_pointer, write_bind_intent,
)
from .custody import write_pointer as write_custody_pointer
from .identity import (
    assert_unchanged,
    bootstrap_initialize,
    identity_status,
    _mutation_preflight_with_context,
    read_binding,
    verify_current_binding,
    verify_manifest_link,
)
from .initialization import existing_initialization
from .storage_primitives import atomic_write, fsync_directory, write_immutable
from .refute_store_mixin import RefuteStoreMixin
from .reader_gate import shared_reader_gate, shared_reader_gate_bounded
from .record_text import record_text
from .plan_guard import guard_plan_against_snapshot
from .store_errors import (
    ConcurrentUpdateError,
    IntegrityError,
    LockBusyError,
    StoreError,
)
from .store_locks import LockResult, write_lock as _write_lock_under_root
from .store_recovery import doctor_report, recover_report
from .subject_binding import check_subject_ref_binding
from .supersede import resolve_supersede_targets
from .transactions import begin_transaction, commit_locked
from .write_commit import commit_write_plan as _commit_write_plan_flow
from .vigency import is_canonical_vigency
from .write_policy import (
    WritePolicyError,
    build_write_plan,
    evaluate_write,
    verify_write_plan,
)


STREAMS = ("facts", "events", "episodes")
ID_FIELDS = {"facts": "id", "events": "id", "episodes": "id"}
PREFIXES = {"facts": "f", "events": "e", "episodes": "ep"}


@dataclass(frozen=True)
class Snapshot:
    revision_id: str
    manifest: Mapping[str, Any]
    checkpoint: Mapping[str, Any]
    records: Mapping[str, tuple[Mapping[str, Any], ...]]
    raw_records: Mapping[str, tuple[Mapping[str, Any], ...]]


def _validate_checkpoint_v2(
    checkpoint: Mapping[str, Any], manifest_revision: Any
) -> None:
    if checkpoint.get("schema") != "an-kla/checkpoint-v2":
        return
    if set(checkpoint) != {"schema", "revision", "working_state"}:
        raise IntegrityError("checkpoint_v2_invalid")
    revision = checkpoint["revision"]
    if (
        not isinstance(revision, int)
        or isinstance(revision, bool)
        or not isinstance(manifest_revision, int)
        or isinstance(manifest_revision, bool)
        or not 1 <= revision <= manifest_revision
    ):
        raise IntegrityError("checkpoint_v2_invalid")
    try:
        validate_working_state(checkpoint["working_state"])
    except CheckpointPolicyError as exc:
        raise IntegrityError("checkpoint_v2_invalid") from exc


class MemoryStore(CompactionStoreMixin, RefuteStoreMixin):
    """Owns ``<store_root>/memory``; ``store_root`` defaults to ``.an-kla``.

    ``store_root`` is the custody root (ADR-0048 §1).  Callers resolve it
    (flag > env > pointer > project-local) with ``custody.resolve_store_root``;
    the constructor never reads the environment or the pointer.
    """

    def __init__(
        self,
        project_root: str | Path,
        *,
        store_root: str | Path | None = None,
        refute_authority_resolver: Any | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        default_root = self.project_root / ".an-kla"
        self.store_root = (
            default_root if store_root is None else Path(store_root).resolve()
        )
        self.store_external = self.store_root != default_root
        if self.store_external and (
            self.store_root == self.project_root
            or self.store_root in self.project_root.parents
            or default_root in self.store_root.parents
        ):
            raise StoreError("store_root_invalid")
        # Identity symlink walks stop here: project_root by default (ADR-0048
        # Enmienda 1 §4), so the legacy layout keeps its exact checks.
        self.custody_walk_root = self.store_root.parent
        self._opened_under_pointer = self.store_external and self._pointer_names_root()
        self.root = self.store_root / "memory"
        self.refute_authority_resolver = refute_authority_resolver
        self._refute_resolver_descriptor: Mapping[str, Any] | None = None
        if refute_authority_resolver is not None:
            from .refute_contracts import RefutePolicyError, validate_descriptor

            if isinstance(refute_authority_resolver, Mapping) or not callable(
                getattr(refute_authority_resolver, "resolve", None)
            ) or not callable(getattr(refute_authority_resolver, "verify", None)):
                raise RefutePolicyError("invalid_refute_attestation", "resolver_capability")
            self._refute_resolver_descriptor = validate_descriptor(
                deepcopy(getattr(refute_authority_resolver, "descriptor", None))
            )

    @property
    def custody_pointer_present(self) -> bool:
        """A pointer means custody is external: reading the project-local
        root would serve a twin (ADR-0048 §1, R1a fail-closed reads).

        Re-checked on every access (one ``lstat``) so a long-lived process
        opened before a ``relocate`` stops serving the origin (#147, m4).
        """

        if not self.store_external:
            return os.path.lexists(self.project_root / ".an-kla" / POINTER_NAME)
        # An external root the pointer named when this object was opened
        # stops serving once the pointer no longer names it, e.g. after
        # ``relocate back`` (release round 7, R7-01).  Roots opened without
        # such a pointer (flag, env, a relocation's own destination) keep
        # their checks at open and mutation time.
        if not self._opened_under_pointer:
            return False
        return not self._pointer_names_root()

    def _pointer_names_root(self) -> bool:
        try:
            pointer = read_pointer(self.project_root)
        except CustodyError:
            return False
        return pointer is not None and Path(pointer["store_root"]).resolve() == self.store_root

    @property
    def current_path(self) -> Path:
        return self.root / "refs" / "CURRENT"

    @property
    def durability_profile(self) -> str:
        return "windows-no-dir-fsync/v1" if os.name == "nt" else "posix-fsync-dir/v1"

    def initialize(self) -> str:
        """Create an empty root revision, or return the existing revision."""

        result = self.initialize_with_outcome()
        if result["outcome"] is not None and result["outcome"]["committed"] is not True:
            raise StoreError(f"initialize_failed:{result['outcome']['state']}")
        return str(result["revision"])

    def initialize_with_outcome(
        self, *, transaction_id: str | None = None, store_identity: str | None = None
    ) -> dict[str, Any]:
        """Bootstrap ADR-0022 identity, then create/reconcile the ADR-0024 root."""

        if store_identity is not None:
            raise StoreError("external_store_identity_not_allowed")
        if self.store_external and project_local_vault_present(self.project_root):
            # A project-local vault already exists: an external ``init``
            # would fork it (ADR-0048 §1).  Move it with ``relocate``.
            raise CustodyError("store_root_divergence")
        pending = read_bind_intent(self.project_root)
        if self.store_external and read_pointer(self.project_root) is None:
            self._require_same_project_for_binding()
            # #147 (m1): mark the binding before bootstrapping the vault, so a
            # crash before the pointer cannot let a bare ``init`` fork it.
            write_bind_intent(self.project_root, self.store_root)
        elif not self.store_external and pending is not None:
            raise CustodyError("store_root_bind_pending")
        result = bootstrap_initialize(self, transaction_id)
        if self.store_external and result["identity"]["identity_state"] == "complete":
            # ADR-0048 Enmienda 1 §4: an external vault leaves its pointer
            # so a later bare invocation cannot fork it (H1).
            write_custody_pointer(self, read_binding(self))
            clear_bind_intent(self.project_root, self.store_root)
        try:
            # F0-B: attest material lives under the custody root.
            result["attestation"] = attest_module.ensure_attest_files(
                self.project_root, store=self
            )
        except OSError:
            # Issue #115/T2: el init ya committeó; un fallo operacional
            # de attest no puede ocultar el outcome (degradación visible).
            result["attestation"] = {
                "schema": "an-kla/attest-init-result-v1",
                "created": [],
                "existed": [],
                "error": "attest_init_unwritable",
            }
        # ADR-0020 pattern, extended to init (issue #87): a best-effort
        # context snapshot so a bare ``init`` surfaces ``installed: false``
        # instead of a clean commit that hides the missing agent entry
        # point.  Computed outside any lock; never masks the outcome.
        result["context_diagnostics"] = self._context_diagnostics()
        return result

    def _require_same_project_for_binding(self) -> None:
        """An existing vault is bound only by the project it was created for.

        ``init`` without a pointer writes one: binding another project's
        vault that way would let two projects share it silently (G3 R3
        adversarial round, M3).  A vault created elsewhere is bound with
        ``relocate attach``, whose receipt moves the bound root here
        (ADR-0048 Enmienda 5).
        """

        from .relocate_attach import bound_project_root

        if identity_status(self)["identity_status"] != "complete":
            return
        if bound_project_root(self, read_binding(self)) != str(self.project_root):
            raise CustodyError("store_root_project_mismatch")

    def read_current(self) -> str:
        """Read and close CURRENT before doing any other I/O."""
        if self.custody_pointer_present:
            raise CustodyError("store_root_divergence")
        try:
            with self.current_path.open("rb") as handle:
                raw = handle.read()
        except FileNotFoundError as exc:
            raise IntegrityError("current_missing") from exc
        if len(raw) != 72 or not raw.endswith(b"\n"):
            raise IntegrityError("current_invalid_length")
        try:
            value = raw[:-1].decode("ascii")
            bare_digest(value)
        except (UnicodeDecodeError, ValueError) as exc:
            raise IntegrityError("current_invalid_syntax") from exc
        return value

    def snapshot(
        self, revision_id: str | None = None, *, use_watermark: bool = True
    ) -> Snapshot:
        if self.custody_pointer_present:
            # An explicit revision skips read_current(); the twin check must
            # not (beta.30 release round, H-03).
            raise CustodyError("store_root_divergence")
        with shared_reader_gate(self):
            return self._snapshot_under_gate(revision_id, use_watermark=use_watermark)

    def _snapshot_under_gate(
        self, revision_id: str | None = None, *, use_watermark: bool = True
    ) -> Snapshot:
        from .watermark import usable_watermark

        revision_id = revision_id or self.read_current()
        try:
            manifest = self._read_json_object("revisions", revision_id)
        except IntegrityError as original:
            from .compaction import archived_revision_link_under_gate

            try:
                archived = archived_revision_link_under_gate(self, revision_id)
            except Exception as exc:
                raise IntegrityError("compaction_catalog_invalid") from exc
            if archived is not None:
                raise IntegrityError("revision_archived_by_compaction") from original
            raise
        if digest_json(manifest) != revision_id:
            raise IntegrityError("revision_hash_mismatch")
        self._validate_manifest(manifest)
        self._validate_revision_chain(
            revision_id, manifest,
            stop=usable_watermark(self) if use_watermark else None,
        )
        verify_manifest_link(self, manifest)
        checkpoint_id = str(manifest.get("checkpoint", ""))
        checkpoint = self._read_json_object("checkpoints", checkpoint_id)
        _validate_checkpoint_v2(checkpoint, manifest.get("revision"))
        records: dict[str, tuple[Mapping[str, Any], ...]] = {}
        for stream in STREAMS:
            rows: list[Mapping[str, Any]] = []
            seen: set[str] = set()
            for segment_id in manifest.get(f"{stream}_segments", []):
                segment_rows = self._read_segment(stream, str(segment_id))
                for row in segment_rows:
                    record_id = str(row.get(ID_FIELDS[stream], ""))
                    if not record_id or record_id in seen:
                        raise IntegrityError(f"duplicate_or_missing_{stream}_id")
                    seen.add(record_id)
                    rows.append(row)
            records[stream] = tuple(rows)
        raw_records = records
        self._validate_lifecycle(manifest, raw_records)
        # ADR-0019 (PR-B): vigencia observable por overlay. ``supersedes_map`` is
        # cumulative (inherited from the parent revision); each target is marked
        # ``status="sustituida"`` in memory without rewriting the immutable
        # segment (``O_EXCL``). Old revisions without the field read as ``[]``
        # -> no-op overlay (backwards-compatible: byte-identical to today).
        targets: set[tuple[str, str]] = set()
        for entry in manifest.get("supersedes_map", []):
            stream = entry.get("stream") if isinstance(entry, dict) else None
            target_id = entry.get("target_id") if isinstance(entry, dict) else None
            if stream in STREAMS and isinstance(target_id, str) and target_id:
                targets.add((stream, target_id))
        if targets:
            overlaid: dict[str, tuple[Mapping[str, Any], ...]] = {}
            for stream, rows in records.items():
                overlaid[stream] = tuple(
                    {**row, "status": "sustituida"}
                    if (stream, str(row.get("id", ""))) in targets
                    else row
                    for row in rows
                )
            records = overlaid
        refuted = {
            (entry["stream"], entry["target_record_sha256"])
            for entry in manifest.get("refutations_map", [])
        }
        if refuted:
            overlaid = {}
            for stream, rows in records.items():
                overlaid[stream] = tuple(
                    {**row, "status": "refutada"}
                    if (stream, digest_json(raw)) in refuted
                    else row
                    for row, raw in zip(rows, raw_records[stream])
                )
            records = overlaid
        return Snapshot(revision_id, manifest, checkpoint, records, raw_records)

    def commit(
        self,
        *,
        expected_current_hash: str,
        checkpoint_patch: Mapping[str, Any],
        facts: Iterable[Mapping[str, Any]] = (),
        events: Iterable[Mapping[str, Any]] = (),
        episodes: Iterable[Mapping[str, Any]] = (),
    ) -> str:
        """Internal, unsupported primitive for an unguarded child commit.

        New agent-facing integrations should use :meth:`plan_write` followed by
        :meth:`commit_write_plan`.  This method remains available for internal
        maintenance and tests; accessibility is not a public compatibility
        promise.
        """
        if checkpoint_patch:
            raise StoreError("governed_checkpoint_update_required")
        preflight = _mutation_preflight_with_context(self)
        binding = preflight.binding
        self._make_layout()
        pending = {
            "facts": [dict(row) for row in facts],
            "events": [dict(row) for row in events],
            "episodes": [dict(row) for row in episodes],
        }
        with self.write_lock() as lock_result:
            observed = self.read_current()
            if observed != expected_current_hash:
                raise ConcurrentUpdateError(
                    f"current_changed:expected={expected_current_hash}:actual={observed}"
                )
            store_identity = assert_unchanged(self, binding, observed)
            candidate, outcome = self._commit_locked(
                observed=observed,
                checkpoint_patch=checkpoint_patch,
                pending=pending,
                store_identity=store_identity,
                _context=preflight.context,
            )
            if outcome["committed"] is not True:
                raise StoreError(f"commit_failed:{outcome['state']}")
        self._maybe_reindex(observed, candidate)
        return candidate

    def writer_gate(self) -> Iterator[None]:
        """ADR-0059: gate compartido acotado para el camino de escritura.

        Espera ``LOCK_SH`` con la constante única
        ``WRITE_LOCK_DEADLINE_SECONDS``; al vencer levanta
        ``LockBusyError("writer_gate_busy")`` (reintentable).
        """

        return shared_reader_gate_bounded(self)

    def plan_write(
        self,
        proposal: Mapping[str, Any],
        authority: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Build a policy decision and exact plan without mutating the store.

        ADR-0060: el par ``read_current``+``snapshot`` es coherente bajo
        una sola adquisición del gate (acotada por ADR-0059).
        """

        with self.writer_gate():
            observed = self.read_current()
            decision = evaluate_write(proposal, authority)
            if proposal["base_revision"] != observed:
                raise WritePolicyError("write_plan_base_changed")
            if decision["decision"] != "skip":
                # Issue #103 (H1): fail-closed temprano (TOCTOU cerrado en
                # commit). Bajo el gate sostenido la base no puede ser
                # archivada a mitad de planificación (ADR-0060).
                guard_plan_against_snapshot(self.snapshot(observed).records, proposal)
            plan = build_write_plan(proposal, authority, decision)
        return {
            "schema": "an-kla/write-planning-result-v1",
            "current_revision": observed,
            "decision": decision,
            "plan": plan,
        }

    def commit_write_plan(
        self,
        *,
        expected_current_hash: str,
        plan: Mapping[str, Any],
        proposal: Mapping[str, Any],
        authority: Mapping[str, Any],
        decision: Mapping[str, Any],
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        """Revalidate and commit one exact write plan under the store lock.

        Delegates to :mod:`an_kla.write_commit` (partición #117), que
        incluye el replay de ADR-0024 §API/CLI (issue #115/T1).
        """
        return _commit_write_plan_flow(
            self,
            expected_current_hash=expected_current_hash,
            plan=plan,
            proposal=proposal,
            authority=authority,
            decision=decision,
            transaction_id=transaction_id,
        )

    def _context_diagnostics(self) -> dict[str, Any]:
        """Best-effort contract-health snapshot (ADR-0020).

        Computed OUTSIDE the write lock on the commit path; always returns a
        dict so it never masks a successful commit. Degrades to a
        ``context_status_unavailable`` marker if ``context_status`` raises.
        Objective status data, not instructions (trust boundary).
        """

        try:
            return dict(context_status(str(self.project_root)))
        except Exception as exc:  # best-effort diagnostic surface, never fatal
            code = getattr(exc, "code", None) or type(exc).__name__
            return {
                "schema": "an-kla/context-status/v1",
                "ok": None,
                "diagnostics": ["context_status_unavailable"],
                "error": str(code),
            }

    def _commit_locked(
        self,
        *,
        observed: str,
        checkpoint_patch: Mapping[str, Any],
        pending: Mapping[str, list[dict[str, Any]]],
        attempt: Mapping[str, Any] | None = None,
        policy_metadata: Mapping[str, Any] | None = None,
        supersedes: list[dict[str, str]] | None = None,
        refute_objects: Mapping[str, Any] | None = None,
        store_identity: str | None = None,
        _context: _OperationContext | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Write a child revision while the caller holds ``write_lock``."""

        if attempt is None:
            mutation = {
                "base_revision": observed,
                "checkpoint_patch": checkpoint_patch,
                "pending": pending,
                "policy_metadata": policy_metadata,
                "supersedes": supersedes,
            }
            if refute_objects is not None:
                mutation["refute_objects"] = refute_objects
            attempt = begin_transaction(
                "internal_commit",
                base_revision=observed,
                mutation_fingerprint=digest_json(mutation),
            )
        return commit_locked(
            self,
            observed=observed,
            checkpoint_patch=checkpoint_patch,
            pending=pending,
            attempt=attempt,
            policy_metadata=policy_metadata,
            supersedes=supersedes,
            refute_objects=refute_objects,
            store_identity=store_identity,
            _context=_context,
        )

    def verify(self) -> dict[str, Any]:
        # Auditoría completa (ADR-0053 §1): verify ignora el watermark y
        # recorre toda la cadena.
        snapshot = self.snapshot(use_watermark=False)
        binding = verify_current_binding(self, snapshot.manifest, snapshot.revision_id)
        result = {
            "ok": True,
            "revision": snapshot.revision_id,
            "revision_number": snapshot.manifest["revision"],
            "counts": {stream: len(snapshot.records[stream]) for stream in STREAMS},
            "durability_profile": self.durability_profile,
            "identity_status": identity_status(self)["identity_status"],
            "root_relocated": binding["root_relocated"],
        }
        # #179: records con status/nu no escalares (lotes de b31/b32). La
        # integridad no se ve afectada: se informa, sólo cuando existen.
        noncanonical = {
            stream: sum(1 for row in snapshot.raw_records[stream]
                        if not is_canonical_vigency(row))
            for stream in STREAMS
        }
        if any(noncanonical.values()):
            result["noncanonical_vigency"] = noncanonical
        return result

    def recover(self) -> dict[str, Any]:
        """Diagnose interrupted work without guessing a replacement CURRENT."""
        with shared_reader_gate(self):
            return recover_report(self)

    def doctor(self) -> dict[str, Any]:
        with shared_reader_gate(self):
            return doctor_report(self)

    def write_lock(self) -> Iterator[LockResult]:
        """Adquiere el lock de escritura (deadline 10s; issue #111/P2)."""
        self._make_layout()
        return _write_lock_under_root(self.root)

    def _make_layout(self) -> None:
        for relative in (
            "refs/ref-log/sha256",
            "revisions/sha256",
            "checkpoints/sha256",
            "segments/facts/sha256",
            "segments/events/sha256",
            "segments/episodes/sha256",
            "transactions",
            "indexes",
            "leases",
            "quarantine",
            "identities/sha256",
            "authority-claims/sha256",
            "authority-attestations/sha256",
            "refutations/sha256",
        ):
            (self.root / relative).mkdir(parents=True, exist_ok=True)

    def _path_for(self, kind: str, identifier: str, suffix: str = ".json") -> Path:
        return self.root / kind / "sha256" / (bare_digest(identifier) + suffix)

    def _write_json_object(self, kind: str, value: Mapping[str, Any]) -> str:
        payload = canonical_json(value)
        identifier = digest_bytes(payload)
        self._write_immutable(self._path_for(kind, identifier), payload)
        return identifier

    def _read_json_object(self, kind: str, identifier: str) -> Mapping[str, Any]:
        path = self._path_for(kind, identifier)
        try:
            payload = path.read_bytes()
        except FileNotFoundError as exc:
            raise IntegrityError(f"object_missing:{kind}") from exc
        if digest_bytes(payload) != identifier:
            raise IntegrityError(f"object_hash_mismatch:{kind}")
        try:
            value = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise IntegrityError(f"object_json_invalid:{kind}") from exc
        if canonical_json(value) != payload:
            raise IntegrityError(f"object_not_canonical:{kind}")
        return value

    def _write_segment(self, stream: str, rows: list[Mapping[str, Any]]) -> str:
        payload = b"".join(canonical_json(row) + b"\n" for row in rows)
        identifier = digest_bytes(payload)
        path = self.root / "segments" / stream / "sha256" / (bare_digest(identifier) + ".jsonl")
        self._write_immutable(path, payload)
        return identifier

    def _read_segment(self, stream: str, identifier: str) -> list[Mapping[str, Any]]:
        path = self.root / "segments" / stream / "sha256" / (bare_digest(identifier) + ".jsonl")
        try:
            payload = path.read_bytes()
        except FileNotFoundError as exc:
            raise IntegrityError(f"segment_missing:{stream}") from exc
        # ADR-0057: digest ancla los bytes originales (content-addressed);
        # la forma canónica se garantiza por construcción al escribir, no se
        # re-deriva en cada lectura (64,7 % del coste de lectura, medido).
        if digest_bytes(payload) != identifier or not payload.endswith(b"\n"):
            raise IntegrityError(f"segment_hash_or_framing_invalid:{stream}")
        return [json.loads(line) for line in payload.decode("utf-8").splitlines()]

    def _write_ref_log(self, entry: Mapping[str, Any]) -> str:
        return self._write_json_object("refs/ref-log", entry)

    def _write_transaction(self, txid: str, body: Mapping[str, Any]) -> None:
        self._atomic_write(self.root / "transactions" / f"{txid}.json", canonical_json(body))

    def _write_immutable(self, target: Path, payload: bytes) -> None:
        write_immutable(
            target,
            payload,
            conflict=self._quarantine_conflict,
            fsync_directory=self._fsync_directory,
        )

    def _quarantine_conflict(self, target: Path) -> None:
        """Move an unreferenced conflicting object out of every lookup path."""
        quarantine = self.root / "quarantine"
        quarantine.mkdir(parents=True, exist_ok=True)
        existing = [path for path in quarantine.rglob("*") if path.is_file()]
        used = sum(path.stat().st_size for path in existing)
        if len(existing) >= 128 or used + target.stat().st_size > 64 * 1024 * 1024:
            raise StoreError("quarantine_quota_exceeded")
        destination = quarantine / f"{uuid.uuid4().hex}-{target.name}"
        os.replace(target, destination)
        self._fsync_directory(quarantine)

    def _atomic_write(self, target: Path, payload: bytes) -> None:
        atomic_write(target, payload, fsync_directory=self._fsync_directory)

    def _replace_current(self, identifier: str) -> None:
        bare_digest(identifier)
        self._atomic_write(self.current_path, (identifier + "\n").encode("ascii"))

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        fsync_directory(path)

    def _assign_records(
        self, base: Snapshot, pending: Mapping[str, list[dict[str, Any]]]
    ) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        for stream in STREAMS:
            field = ID_FIELDS[stream]
            existing = {str(row[field]) for row in base.records[stream]}
            rows: list[dict[str, Any]] = []
            for row in pending[stream]:
                value = row.get(field)
                if not isinstance(value, str) or not value:
                    raise StoreError(f"missing_{stream}_id")
                if value in existing:
                    raise StoreError(f"duplicate_{stream}_id")
                existing.add(value)
                rows.append(row)
            result[stream] = rows
        return result

    @staticmethod
    def _validate_manifest(manifest: Mapping[str, Any]) -> None:
        from .revision_validation import validate_manifest

        validate_manifest(manifest, IntegrityError)

    def _validate_revision_chain(
        self, revision_id: str, manifest: Mapping[str, Any],
        *, stop: Mapping[str, Any] | None = None,
    ) -> None:
        from .revision_validation import validate_revision_chain

        validate_revision_chain(self, revision_id, manifest, IntegrityError, stop=stop)

    def _validate_lifecycle(
        self, manifest: Mapping[str, Any], raw_records: Mapping[str, tuple[Mapping[str, Any], ...]]
    ) -> None:
        from .revision_validation import validate_lifecycle

        validate_lifecycle(self, manifest, raw_records, IntegrityError)

    def _maybe_reindex(self, parent_revision: str, candidate_revision: str) -> None:
        from .index_refresh import maybe_reindex

        maybe_reindex(self, parent_revision, candidate_revision)
