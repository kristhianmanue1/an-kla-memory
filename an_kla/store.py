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


def _deep_merge(base: Mapping[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(base))
    for key, value in patch.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


class MemoryStore:
    """Owns `.an-kla/memory` below a project root."""

    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).resolve()
        self.root = self.project_root / ".an-kla" / "memory"

    @property
    def current_path(self) -> Path:
        return self.root / "refs" / "CURRENT"

    @property
    def durability_profile(self) -> str:
        return "windows-no-dir-fsync/v1" if os.name == "nt" else "posix-fsync-dir/v1"

    def initialize(self) -> str:
        """Create an empty root revision, or return the existing revision."""
        if self.current_path.exists():
            return self.read_current()
        self._make_layout()
        with self.write_lock():
            if self.current_path.exists():
                return self.read_current()
            checkpoint = {
                "schema": "an-kla/checkpoint-v1",
                "revision": 0,
                "goal": None,
                "next": None,
                "decisions": [],
                "blockers": [],
            }
            checkpoint_id = self._write_json_object("checkpoints", checkpoint)
            manifest = {
                "schema": "an-kla/revision-v1",
                "revision": 0,
                "parent": None,
                "facts_segments": [],
                "events_segments": [],
                "episodes_segments": [],
                "checkpoint": checkpoint_id,
                "transaction_id": "root",
                "canonicalization": "canonical-json/v1",
                "integrity_claim": "content_identity_not_truth_or_authorship",
            }
            revision_id = self._write_json_object("revisions", manifest)
            self._replace_current(revision_id)
            return revision_id

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
        revision_id = revision_id or self.read_current()
        manifest = self._read_json_object("revisions", revision_id)
        if digest_json(manifest) != revision_id:
            raise IntegrityError("revision_hash_mismatch")
        if manifest.get("schema") != "an-kla/revision-v1":
            raise IntegrityError("revision_schema_invalid")
        checkpoint_id = str(manifest.get("checkpoint", ""))
        checkpoint = self._read_json_object("checkpoints", checkpoint_id)
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
        return Snapshot(revision_id, manifest, checkpoint, records)

    def commit(
        self,
        *,
        expected_current_hash: str,
        checkpoint_patch: Mapping[str, Any],
        facts: Iterable[Mapping[str, Any]] = (),
        events: Iterable[Mapping[str, Any]] = (),
        episodes: Iterable[Mapping[str, Any]] = (),
    ) -> str:
        """Commit a child revision through the compatible unguarded API.

        New agent-facing integrations should use :meth:`plan_write` followed by
        :meth:`commit_write_plan`.  This method remains available for internal
        maintenance and compatibility with the alpha API.
        """
        self._make_layout()
        pending = {
            "facts": [dict(row) for row in facts],
            "events": [dict(row) for row in events],
            "episodes": [dict(row) for row in episodes],
        }
        with self.write_lock():
            observed = self.read_current()
            if observed != expected_current_hash:
                raise ConcurrentUpdateError(
                    f"current_changed:expected={expected_current_hash}:actual={observed}"
                )
            candidate = self._commit_locked(
                observed=observed,
                checkpoint_patch=checkpoint_patch,
                pending=pending,
            )
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
    ) -> dict[str, Any]:
        """Revalidate and commit one exact write plan under the store lock."""

        self._make_layout()
        with self.write_lock():
            observed = self.read_current()
            if observed != expected_current_hash:
                raise WritePolicyError("write_plan_base_changed")

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
                }

            pending: dict[str, list[dict[str, Any]]] = {
                "facts": [],
                "events": [],
                "episodes": [],
            }
            for item in checked_plan["records"]:
                # verify_write_plan rebuilt this exact list and policy/v1 only
                # supports add.  Keep the check local so a future policy cannot
                # accidentally route lifecycle operations through append.
                if item["operation"] != "add":
                    raise WritePolicyError("invalid_write_plan")
                pending[item["stream"]].append(deepcopy(item["record"]))

            policy_metadata = {
                "schema": "an-kla/write-policy-transaction-v1",
                "plan_fingerprint": checked_plan["plan_fingerprint"],
                "proposal_sha256": checked_decision["proposal_sha256"],
                "authority_sha256": checked_decision["authority_sha256"],
                "policy_fingerprint": checked_decision["policy_fingerprint"],
                "decision": checked_decision["decision"],
                "reason_codes": deepcopy(checked_decision["reason_codes"]),
            }
            revision = self._commit_locked(
                observed=observed,
                checkpoint_patch={},
                pending=pending,
                policy_metadata=policy_metadata,
            )
        self._maybe_reindex(observed, revision)
        return {
            "schema": "an-kla/write-commit-result-v1",
            "committed": True,
            "revision": revision,
            "decision": checked_decision["decision"],
            "reason_codes": deepcopy(checked_decision["reason_codes"]),
            "plan_fingerprint": checked_plan["plan_fingerprint"],
        }

    def _commit_locked(
        self,
        *,
        observed: str,
        checkpoint_patch: Mapping[str, Any],
        pending: Mapping[str, list[dict[str, Any]]],
        policy_metadata: Mapping[str, Any] | None = None,
    ) -> str:
        """Write a child revision while the caller holds ``write_lock``."""

        base = self.snapshot(observed)
        assigned = self._assign_records(base, pending)
        checkpoint = _deep_merge(base.checkpoint, checkpoint_patch)
        checkpoint["revision"] = int(base.manifest["revision"]) + 1
        checkpoint["base_event_id"] = (
            assigned["events"][-1]["id"]
            if assigned["events"]
            else base.checkpoint.get("base_event_id")
        )
        txid = str(uuid.uuid4())
        prepared = {"stage": "prepared", "parent": observed}
        if policy_metadata is not None:
            prepared["write_policy"] = deepcopy(dict(policy_metadata))
        self._write_transaction(txid, prepared)
        segment_ids: dict[str, list[str]] = {}
        for stream in STREAMS:
            existing = list(base.manifest.get(f"{stream}_segments", []))
            if assigned[stream]:
                existing.append(self._write_segment(stream, assigned[stream]))
            segment_ids[stream] = existing
        checkpoint_id = self._write_json_object("checkpoints", checkpoint)
        manifest = {
            "schema": "an-kla/revision-v1",
            "revision": checkpoint["revision"],
            "parent": observed,
            "facts_segments": segment_ids["facts"],
            "events_segments": segment_ids["events"],
            "episodes_segments": segment_ids["episodes"],
            "checkpoint": checkpoint_id,
            "transaction_id": txid,
            "canonicalization": "canonical-json/v1",
            "integrity_claim": "content_identity_not_truth_or_authorship",
        }
        self._validate_manifest(manifest)
        candidate = self._write_json_object("revisions", manifest)
        intent_id = self._write_ref_log(
            {
                "schema": "an-kla/ref-log-v1",
                "kind": "intent",
                "transaction_id": txid,
                "parent": observed,
                "candidate": candidate,
            }
        )
        if self.read_current() != observed:
            raise ConcurrentUpdateError("current_changed_before_commit")
        self._replace_current(candidate)
        committed = {"stage": "committed", "parent": observed, "candidate": candidate}
        if policy_metadata is not None:
            committed["write_policy"] = deepcopy(dict(policy_metadata))
        self._write_transaction(txid, committed)
        try:
            self._write_ref_log(
                {
                    "schema": "an-kla/ref-log-v1",
                    "kind": "observed_commit",
                    "transaction_id": txid,
                    "parent": observed,
                    "candidate": candidate,
                    "intent": intent_id,
                }
            )
        except OSError:
            # The commit is already authoritative.  The missing diagnostic
            # object is visible through doctor, never grounds a rollback.
            pass
        return candidate

    def verify(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        return {
            "ok": True,
            "revision": snapshot.revision_id,
            "revision_number": snapshot.manifest["revision"],
            "counts": {stream: len(snapshot.records[stream]) for stream in STREAMS},
            "durability_profile": self.durability_profile,
        }

    def recover(self) -> dict[str, Any]:
        """Diagnose interrupted work without guessing a replacement CURRENT."""
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
    def write_lock(self) -> Iterator[None]:
        self._make_layout()
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
                    yield
                finally:
                    lock_dir.rmdir()
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
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            return
        lock_path = self.root / ".write.lock"
        with lock_path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

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
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != payload:
                self._quarantine_conflict(target)
            else:
                return
        # Objects are unreferenced until a valid manifest becomes CURRENT.  O_EXCL
        # prevents an existing object from being overwritten.
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            descriptor = os.open(target, flags, 0o644)
        except FileExistsError:
            if target.read_bytes() != payload:
                self._quarantine_conflict(target)
                return self._write_immutable(target, payload)
            return
        try:
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self._fsync_directory(target.parent)

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
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            self._fsync_directory(target.parent)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _replace_current(self, identifier: str) -> None:
        bare_digest(identifier)
        self._atomic_write(self.current_path, (identifier + "\n").encode("ascii"))

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        if os.name == "nt":
            return
        try:
            descriptor = os.open(path, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

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
        if manifest.get("schema") != "an-kla/revision-v1":
            raise IntegrityError("manifest_schema_invalid")
        for key in ("checkpoint", "parent"):
            value = manifest.get(key)
            if key == "parent" and value is None:
                continue
            if not isinstance(value, str):
                raise IntegrityError("manifest_identifier_missing")
            bare_digest(value)
        for stream in STREAMS:
            values = manifest.get(f"{stream}_segments")
            if not isinstance(values, list):
                raise IntegrityError("manifest_segments_invalid")
            for identifier in values:
                bare_digest(str(identifier))

    def _maybe_reindex(self, parent_revision: str, candidate_revision: str) -> None:
        """Best-effort refresh of the derived FTS5 cache after a commit.

        Runs *outside* the write lock because the index is a derived cache
        whose authority is the (revision, hash) pair, never the commit
        pointer.  Failures are silent: a missing or stale index simply
        degrades retrieval to the scan profile.
        """

        try:
            from .index import build_index, index_resolution
        except ImportError:
            return
        try:
            parent = index_resolution(self, parent_revision)
            if parent.path is None:
                return
        except Exception:
            return
        try:
            build_index(self, revision_id=candidate_revision)
        except Exception:
            # The commit is already authoritative.  A failed cache refresh is
            # visible through ``doctor`` and never blocks retrieval.
            pass
