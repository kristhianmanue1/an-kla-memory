"""ADR-0040: explicit baseline adoption (plan -> commit)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from an_kla.canonical import digest_json
from an_kla.context_package import (
    CONTRACT_RELATIVE,
    ContextConcurrentUpdate,
    ContextPackageError,
    MANIFEST_RELATIVE,
    _atomic_write,
    _canonical_payload,
    _context_lock,
    _contract_equivalent,
    _desired_contract_bytes,
    _known_template_equivalent,
    _load_manifest,
    _observed_sha,
    _project_root,
    _read_utf8,
    _sha,
    _target_path,
    parse_managed_block,
)

ADOPTION_PLAN_SCHEMA = "an-kla/context-baseline-adoption-plan/v1"
ADOPTION_RESULT_SCHEMA = "an-kla/context-baseline-adoption-result/v1"


def _baseline_adoption_preconditions(
    root: Path,
    target: str,
    *,
    manifest: dict[str, Any] | None,
    target_bytes: bytes | None,
    contract_bytes: bytes | None,
    contract_text: str | None,
    block: Any,
) -> dict[str, Any]:
    """Verify ADR-0040 §4 preconditions; raise closed on any violation."""

    if manifest is None:
        raise ContextPackageError("context_manifest_missing")
    if target_bytes is None:
        raise ContextPackageError("context_baseline_target_missing")
    # Canonical managed state: parseable block with consistent self-hash and
    # manifest template_version matching the block metadata (known-outdated
    # templates remain adoptable; ADR-0040 §4, ronda pre-code H2).
    if block is None:
        raise ContextPackageError("context_baseline_managed_state_invalid")
    if str(block.metadata.get("version")) != str(manifest.get("template_version")):
        raise ContextPackageError("context_baseline_managed_state_invalid")
    # El hash del manifiesto es canónico (LF): el payload observado se
    # normaliza igual, porque un editor con CRLF (Windows) no altera el
    # contenido gestionado — misma semántica que aplica
    # parse_managed_block a su self-hash interno.
    observed_block_payload = _sha(
        _canonical_payload(block.payload).encode("utf-8")
    )
    # Semantic conformance for the contract (raw bytes may differ by encoding);
    # the manifest fields must match observation where equality is semantic.
    if manifest.get("managed_content_sha256") != observed_block_payload:
        raise ContextPackageError("context_baseline_semantic_mismatch")
    # Contract sanity: current template (equivalent) or KNOWN historical
    # template. Anything else (hand-modified) is never adoptable.
    known_outdated = _known_template_equivalent(block, contract_text)
    if not known_outdated and not _contract_equivalent(contract_text):
        raise ContextPackageError("context_baseline_managed_state_invalid")
    # Contract validation is SEMANTIC (ADR-0040 §4, enmienda v2): the observed
    # contract must be the current template or a known historical one (checked
    # above). manifest.contract_sha256 may legitimately describe bytes that
    # no longer exist on disk (e.g. the contract was restored to canonical
    # outside an update flow) — the same state context_status reports healthy
    # and update reconciles. The hash is used for CAS concurrency detection,
    # not as a corruption invariant; a hand-modified contract is already
    # rejected by the equivalence check above.
    return {
        "observed_target_sha256": _sha(target_bytes),
        "contract_sha256": _observed_sha(contract_bytes),
    }


def plan_baseline_adoption(
    project_root: str | Path, target: str = "AGENTS.md"
) -> dict[str, Any]:
    """Read-only adoption plan (ADR-0040 §2). Never mutates anything."""

    root = _project_root(project_root)
    target_path = _target_path(root, target)
    target_bytes, target_text = _read_utf8(target_path)
    contract_bytes, contract_text = _read_utf8(root / CONTRACT_RELATIVE)
    manifest = _load_manifest(root)
    manifest_path = root / MANIFEST_RELATIVE
    manifest_bytes = manifest_path.read_bytes() if manifest_path.exists() else None
    block = parse_managed_block(target_text or "")
    observed = _baseline_adoption_preconditions(
        root,
        target,
        manifest=manifest,
        target_bytes=target_bytes,
        contract_bytes=contract_bytes,
        contract_text=contract_text,
        block=block,
    )
    before = str(manifest.get("target_sha256"))
    will_update = before != observed["observed_target_sha256"]
    plan = {
        "schema": ADOPTION_PLAN_SCHEMA,
        "operation": "adopt-baseline",
        "target": target,
        "template_version": str(block.metadata.get("version")),
        "base_manifest_sha256": _observed_sha(manifest_bytes),
        "manifest_target_sha256_before": before,
        "observed_target_sha256": observed["observed_target_sha256"],
        "managed_content_sha256": _sha(
            _canonical_payload(block.payload).encode("utf-8")
        ),
        "contract_sha256": observed["contract_sha256"],
        "will_update_manifest": will_update,
    }
    plan["plan_fingerprint"] = digest_json(plan)
    return plan


def apply_baseline_adoption(
    project_root: str | Path, plan: dict[str, Any]
) -> dict[str, Any]:
    """Adopt the observed target bytes as manifest baseline (ADR-0040 §5).

    Under ``.install.lock``: reread everything, re-verify preconditions,
    rebuild the plan and demand exact equality (CAS), then atomically
    rewrite ONLY the manifest with ``target_sha256 = observed``.
    """

    root = _project_root(project_root)
    if not isinstance(plan, dict) or plan.get("schema") != ADOPTION_PLAN_SCHEMA:
        raise ContextPackageError("invalid_context_plan")
    target = plan.get("target")
    target_path = _target_path(root, target)

    with _context_lock(root):
        target_bytes, target_text = _read_utf8(target_path)
        contract_bytes, contract_text = _read_utf8(root / CONTRACT_RELATIVE)
        manifest = _load_manifest(root)
        manifest_path = root / MANIFEST_RELATIVE
        manifest_bytes = manifest_path.read_bytes() if manifest_path.exists() else None
        block = parse_managed_block(target_text or "")
        observed = _baseline_adoption_preconditions(
            root,
            target,
            manifest=manifest,
            target_bytes=target_bytes,
            contract_bytes=contract_bytes,
            contract_text=contract_text,
            block=block,
        )
        rebuilt = plan_baseline_adoption(root, target)
        if rebuilt != plan:
            if rebuilt.get("base_manifest_sha256") != plan.get("base_manifest_sha256"):
                raise ContextConcurrentUpdate(
                    "context_manifest_concurrent_update"
                )
            if rebuilt.get("contract_sha256") != plan.get("contract_sha256"):
                raise ContextConcurrentUpdate(
                    "context_contract_concurrent_update"
                )
            if rebuilt.get("observed_target_sha256") != plan.get(
                "observed_target_sha256"
            ):
                raise ContextConcurrentUpdate("context_file_concurrent_update")
            raise ContextPackageError("context_plan_mismatch")
        before = str(manifest.get("target_sha256"))
        after = observed["observed_target_sha256"]
        if before == after:
            return {
                "schema": ADOPTION_RESULT_SCHEMA,
                "operation": "adopt-baseline",
                "target": target,
                "action": "noop",
                "manifest_target_sha256_before": before,
                "manifest_target_sha256_after": after,
            }
        adopted = {**manifest, "target_sha256": after}
        _atomic_write(
            root / MANIFEST_RELATIVE,
            (
                json.dumps(adopted, ensure_ascii=False, sort_keys=True, indent=2)
                + "\n"
            ).encode("utf-8"),
            0o600,
        )
        return {
            "schema": ADOPTION_RESULT_SCHEMA,
            "operation": "adopt-baseline",
            "target": target,
            "action": "adopted",
            "manifest_target_sha256_before": before,
            "manifest_target_sha256_after": after,
        }
