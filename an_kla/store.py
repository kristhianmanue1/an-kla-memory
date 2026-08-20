"""Local immutable revisions for the AN-KLA beta.

The implementation intentionally supports one local memory.  CURRENT is the
only commit authority; ref-log entries are diagnostic objects only.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import time
import uuid
from typing import Any, Iterable, Iterator, Mapping

from .canonical import bare_digest, canonical_json, digest_bytes, digest_json
from .checkpoint_policy import CheckpointPolicyError, validate_working_state
from .compaction_store_mixin import CompactionStoreMixin
from .context_package import context_status
from .identity import (
    assert_unchanged,
    bootstrap_initialize,
    identity_status,
    mutation_preflight,
    read_binding,
    verify_current_binding,
    verify_manifest_link,
)
from .initialization import existing_initialization
from .storage_primitives import atomic_write, fsync_directory, write_immutable
from .refute_store_mixin import RefuteStoreMixin
from .reader_gate import shared_reader_gate
from .subject_binding import check_subject_ref_binding
from .supersede import resolve_supersede_targets
from .transactions import (
    begin_transaction,
    commit_locked,
)
from .write_policy import (
    WritePolicyError,
    build_write_plan,
    evaluate_write,
    verify_write_plan,
)


STREAMS = ("facts", "events", "episodes")
ID_FIELDS = {"facts": "id", "events": "id", "episodes": "id"}
PREFIXES = {"facts": "f", "events": "e", "episodes": "ep"}


class StoreError(RuntimeError):
    pass


class ConcurrentUpdateError(StoreError):
    pass


class IntegrityError(StoreError):
    pass


class LockBusyError(StoreError):
    pass


@dataclass(frozen=True)
class Snapshot:
    revision_id: str
    manifest: Mapping[str, Any]
    checkpoint: Mapping[str, Any]
    records: Mapping[str, tuple[Mapping[str, Any], ...]]
    raw_records: Mapping[str, tuple[Mapping[str, Any], ...]]


@dataclass
class LockResult:
    release_error: str | None = None


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
    """Owns `.an-kla/memory` below a project root."""

    def __init__(
        self, project_root: str | Path, *, refute_authority_resolver: Any | None = None
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.root = self.project_root / ".an-kla" / "memory"
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
        result = bootstrap_initialize(self, transaction_id)
        # ADR-0020 pattern, extended to init (issue #87): a best-effort
        # context snapshot so a bare ``init`` surfaces ``installed: false``
        # instead of a clean commit that hides the missing agent entry
        # point.  Computed outside any lock; never masks the outcome.
        result["context_diagnostics"] = self._context_diagnostics()
        return result

    def read_current(self) -> str:
        """Read and close CURRENT before doing any other I/O."""
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

    def snapshot(self, revision_id: str | None = None) -> Snapshot:
        with shared_reader_gate(self):
            return self._snapshot_under_gate(revision_id)

    def _snapshot_under_gate(self, revision_id: str | None = None) -> Snapshot:
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
        self._validate_revision_chain(revision_id, manifest)
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
        binding = mutation_preflight(self)
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
            )
            if outcome["committed"] is not True:
                raise StoreError(f"commit_failed:{outcome['state']}")
        self._maybe_reindex(observed, candidate)
        return candidate

    def plan_write(
        self,
        proposal: Mapping[str, Any],
        authority: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Build a policy decision and exact plan without mutating the store."""

        observed = self.read_current()
        decision = evaluate_write(proposal, authority)
        if proposal["base_revision"] != observed:
            raise WritePolicyError("write_plan_base_changed")
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
        """Revalidate and commit one exact write plan under the store lock."""

        binding = mutation_preflight(self)
        self._make_layout()
        with self.write_lock() as lock_result:
            observed = self.read_current()
            if observed != expected_current_hash:
                raise WritePolicyError("write_plan_base_changed")
            store_identity = assert_unchanged(self, binding, observed)

            # Callers retain their dictionaries and may share them with other
            # threads.  Snapshot every object while holding the store lock and
            # use only those detached values after verification; otherwise a
            # mutation between verify_write_plan() and pending construction
            # could change the bytes that reach the segment.
            checked_plan = deepcopy(plan)
            checked_proposal = deepcopy(proposal)
            checked_authority = deepcopy(authority)
            checked_decision = deepcopy(decision)

            # All policy validation intentionally occurs again inside the same
            # critical section that can move CURRENT.  The pure module remains
            # the only implementation of the policy.
            verify_write_plan(
                checked_plan,
                checked_proposal,
                checked_authority,
                checked_decision,
            )
            if (
                checked_proposal["base_revision"] != observed
                or checked_authority["base_revision"] != observed
                or checked_plan["core"]["base_revision"] != observed
            ):
                raise WritePolicyError("write_plan_base_changed")

            if checked_decision["decision"] == "skip":
                return {
                    "schema": "an-kla/write-commit-result-v1",
                    "committed": False,
                    "revision": observed,
                    "decision": "skip",
                    "reason_codes": deepcopy(checked_decision["reason_codes"]),
                    "plan_fingerprint": checked_plan["plan_fingerprint"],
                    "context_diagnostics": self._context_diagnostics(),
                }

            # ADR-0019 (PR-B): resolve supersede targets against the authoritative
            # snapshot under the lock, before any object/journal is written. A
            # failure here raises invalid_supersede_target (terminal) with no
            # side effects (no orphan objects, no prepared journal).
            pending_supersedes = resolve_supersede_targets(self, checked_plan, observed)

            # ADR-0033 §Decisión 5 (issue #59 Fase B): validate subject_ref
            # namespaces against the bound project identity, still under the
            # write lock and before any object/journal is written. ``binding``
            # is the snapshot captured by mutation_preflight and revalidated by
            # assert_unchanged; the guard never re-reads project identity.
            check_subject_ref_binding(checked_plan, binding)

            pending: dict[str, list[dict[str, Any]]] = {
                "facts": [],
                "events": [],
                "episodes": [],
            }
            for item in checked_plan["records"]:
                # The policy core (write_policy.py) is the only implementation of
                # the policy; refute/decay never reach here (they skip). add and
                # supersede both append the new record to its stream; supersede
                # additionally records the target's vigency flip above.
                op = item["operation"]
                if op == "add":
                    pending[item["stream"]].append(deepcopy(item["record"]))
                elif op == "supersede":
                    pending[item["stream"]].append(deepcopy(item["record"]))
                else:
                    raise WritePolicyError(
                        "invalid_write_plan",
                        "records[]:operation:not_committable",
                    )

            policy_metadata = {
                "schema": "an-kla/write-policy-transaction-v1",
                "plan_fingerprint": checked_plan["plan_fingerprint"],
                "proposal_sha256": checked_decision["proposal_sha256"],
                "authority_sha256": checked_decision["authority_sha256"],
                "policy_fingerprint": checked_decision["policy_fingerprint"],
                "decision": checked_decision["decision"],
                "reason_codes": deepcopy(checked_decision["reason_codes"]),
            }
            attempt = begin_transaction(
                "write",
                transaction_id=transaction_id,
                base_revision=observed,
                plan_fingerprint=checked_plan["plan_fingerprint"],
            )
            revision, outcome = self._commit_locked(
                observed=observed,
                checkpoint_patch={},
                pending=pending,
                attempt=attempt,
                policy_metadata=policy_metadata,
                supersedes=pending_supersedes or None,
                store_identity=store_identity,
            )
        if lock_result.release_error is not None:
            outcome = deepcopy(outcome)
            outcome["audit_state"] = "incomplete"
            outcome["warnings"] = sorted(
                set([*outcome["warnings"], lock_result.release_error])
            )
            if outcome["committed"] is True:
                outcome["state"] = "committed_audit_incomplete"
                outcome["operation_error_code"] = "lock_release_incomplete"
        if outcome["committed"] is True and revision != observed:
            self._maybe_reindex(observed, revision)
        return {
            "schema": "an-kla/write-commit-result-v1",
            "committed": outcome["committed"] is True,
            "revision": revision,
            "decision": checked_decision["decision"],
            "reason_codes": deepcopy(checked_decision["reason_codes"]),
            "plan_fingerprint": checked_plan["plan_fingerprint"],
            "context_diagnostics": self._context_diagnostics(),
            "outcome": outcome,
        }

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
        )

    def verify(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        binding = verify_current_binding(self, snapshot.manifest, snapshot.revision_id)
        return {
            "ok": True,
            "revision": snapshot.revision_id,
            "revision_number": snapshot.manifest["revision"],
            "counts": {stream: len(snapshot.records[stream]) for stream in STREAMS},
            "durability_profile": self.durability_profile,
            "identity_status": identity_status(self)["identity_status"],
            "root_relocated": binding["root_relocated"],
        }

    def recover(self) -> dict[str, Any]:
        """Diagnose interrupted work without guessing a replacement CURRENT."""
        with shared_reader_gate(self):
            return self._recover_under_gate()

    def _recover_under_gate(self) -> dict[str, Any]:
        current = self.read_current()
        # A valid CURRENT is authoritative even if its operational transaction
        # record is stale.  Prepared journals are retained for inspection.
        prepared = []
        for path in sorted((self.root / "transactions").glob("*.json")):
            try:
                entry = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                prepared.append({"path": path.name, "status": "invalid_journal"})
                continue
            if entry.get("stage") != "committed":
                prepared.append({"path": path.name, "status": str(entry.get("stage", "unknown"))})
        return {
            "schema": "an-kla/recovery-report-v1",
            "current": current,
            "action": "none_current_authoritative",
            "pending_transactions": prepared,
        }

    def doctor(self) -> dict[str, Any]:
        with shared_reader_gate(self):
            return self._doctor_under_gate()

    def _doctor_under_gate(self) -> dict[str, Any]:
        try:
            status = self.verify()
            current_error = None
        except IntegrityError as exc:
            status = None
            current_error = str(exc)
        quarantine = self.root / "quarantine"
        objects = [path for path in quarantine.rglob("*") if path.is_file()] if quarantine.exists() else []
        return {
            "schema": "an-kla/doctor-v1",
            "current_ok": current_error is None,
            "current_error": current_error,
            "status": status,
            "quarantine_objects": len(objects),
            "quarantine_bytes": sum(path.stat().st_size for path in objects),
            "durability_profile": self.durability_profile,
            "index_orphan_temporaries": sum(1 for path in (self.root / "indexes").rglob(".build-*.sqlite") if path.is_file()) if (self.root / "indexes").exists() else 0,
        }

    @contextmanager
    def write_lock(self) -> Iterator[LockResult]:
        self._make_layout()
        result = LockResult()
        try:
            import fcntl  # type: ignore
        except ImportError:
            try:
                import msvcrt  # type: ignore
            except ImportError:
                lock_dir = self.root / ".write.lock-dir"
                try:
                    lock_dir.mkdir()
                except FileExistsError as exc:
                    raise LockBusyError("write_lock_busy") from exc
                try:
                    yield result
                finally:
                    try:
                        lock_dir.rmdir()
                    except OSError:
                        result.release_error = "lock_release_incomplete"
                return
            lock_path = self.root / ".write.lock"
            with lock_path.open("a+b") as handle:
                if handle.seek(0, os.SEEK_END) == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                deadline = time.monotonic() + 10.0
                while True:
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError as exc:
                        if time.monotonic() >= deadline:
                            raise LockBusyError("write_lock_busy") from exc
                        time.sleep(0.05)
                try:
                    yield result
                finally:
                    try:
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    except OSError:
                        result.release_error = "lock_release_incomplete"
            return
        lock_path = self.root / ".write.lock"
        with lock_path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield result
            finally:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    result.release_error = "lock_release_incomplete"

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
        if digest_bytes(payload) != identifier or not payload.endswith(b"\n"):
            raise IntegrityError(f"segment_hash_or_framing_invalid:{stream}")
        rows = [json.loads(line) for line in payload.decode("utf-8").splitlines()]
        if b"".join(canonical_json(row) + b"\n" for row in rows) != payload:
            raise IntegrityError(f"segment_not_canonical:{stream}")
        return rows

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
        self, revision_id: str, manifest: Mapping[str, Any]
    ) -> None:
        from .revision_validation import validate_revision_chain

        validate_revision_chain(self, revision_id, manifest, IntegrityError)

    def _validate_lifecycle(
        self, manifest: Mapping[str, Any], raw_records: Mapping[str, tuple[Mapping[str, Any], ...]]
    ) -> None:
        from .revision_validation import validate_lifecycle

        validate_lifecycle(self, manifest, raw_records, IntegrityError)

    def _maybe_reindex(self, parent_revision: str, candidate_revision: str) -> None:
        from .index_refresh import maybe_reindex

        maybe_reindex(self, parent_revision, candidate_revision)
