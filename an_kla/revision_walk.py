"""Private, operation-scoped revision traversal (ADR-0061).

No payload cache or authority: callers still validate bytes on each opening.
Only bounded discovery metadata may survive the traversal, for one operation.
"""
from __future__ import annotations

from typing import Any, Iterator, Mapping

from .canonical import bare_digest
from .transaction_attempts import is_canonical_uuid

_SCHEMAS = ("an-kla/revision-v1", "an-kla/revision-v2", "an-kla/revision-v3")


class RevisionWalkError(ValueError):
    pass


class _OperationContext:
    def __init__(self) -> None:
        self.__projections: dict[str, tuple[str, str]] = {}

    def _remember(self, identifier: str, manifest: Any) -> None:
        # Called only after _read_json_object validated the original bytes.
        if not isinstance(manifest, dict):
            return
        schema, txid = manifest.get("schema"), manifest.get("transaction_id")
        if (
            isinstance(schema, str) and schema in _SCHEMAS
            and isinstance(txid, str) and len(txid) == 36
            and is_canonical_uuid(txid)
        ):
            bare_digest(identifier)
            self.__projections[identifier] = (schema, txid)

    def _candidate(self, identifier: str) -> tuple[str, str] | None:
        return self.__projections.get(identifier)


def walk_revisions(
    store: Any, current: str, *, context: _OperationContext | None = None,
) -> Iterator[tuple[str, Mapping[str, Any]]]:
    """Visit a finite, strictly decreasing chain; never truncate at 10k.

    This checks traversal structure, not the full transition/epoch contract.
    The full v3 audit remains the responsibility of identity_status/verify.
    """
    cursor = current
    seen: set[str] = set()
    child_revision: int | None = None
    while True:
        bare_digest(cursor)
        if cursor in seen:
            raise RevisionWalkError("revision_transition_invalid")
        seen.add(cursor)
        manifest = store._read_json_object("revisions", cursor)
        if not isinstance(manifest, Mapping):
            raise RevisionWalkError("revision_transition_invalid")
        revision, parent = manifest.get("revision"), manifest.get("parent")
        schema = manifest.get("schema")
        if (
            not isinstance(revision, int) or isinstance(revision, bool)
            or revision < 0 or not isinstance(schema, str) or schema not in _SCHEMAS
            or (child_revision is not None and revision != child_revision - 1)
        ):
            raise RevisionWalkError("revision_transition_invalid")
        if parent is None:
            if not (
                (schema == "an-kla/revision-v1" and revision == 0)
                or (schema == "an-kla/revision-v3" and revision > 0)
            ):
                raise RevisionWalkError("revision_transition_invalid")
        else:
            if not isinstance(parent, str) or revision == 0:
                raise RevisionWalkError("revision_transition_invalid")
            bare_digest(parent)
        if context is not None:
            context._remember(cursor, manifest)
        yield cursor, manifest
        if parent is None:
            return
        child_revision, cursor = revision, parent


class _LineageSummary:
    """One disk traversal, bounded metadata per revision and no manifests."""

    def __init__(
        self, store: Any, current: str, identity: str,
        *, context: _OperationContext | None = None,
    ) -> None:
        self.current, self.identity = current, identity
        # strict prefix including this node; legacy exception only at this node.
        self.__points: dict[str, tuple[bool, bool]] = {}
        prefix_ok = True
        self.root_schema: str | None = None
        for identifier, manifest in walk_revisions(store, current, context=context):
            linked = manifest.get("store_identity")
            strict = prefix_ok and linked == identity
            legacy = prefix_ok and linked is None
            self.__points[identifier] = (strict, legacy)
            prefix_ok = strict
            self.root_schema = manifest["schema"]

    def contains(self, identifier: str) -> bool:
        return identifier in self.__points

    def bound(self, identifier: str, *, allow_legacy: bool = False) -> bool:
        strict, legacy = self.__points.get(identifier, (False, False))
        return strict or (allow_legacy and legacy)
