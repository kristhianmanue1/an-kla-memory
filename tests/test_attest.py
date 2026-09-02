"""ADR-0046 — attest: receipts firmados, verificación y anti-replay.

Cubre el test de regresión del ADR (§Test de regresión): E2E con receipt
válido, manipulaciones fail-closed, replay del tombstone, huecos
(CLI sin receipt, v1 sin kind nuevo, refute resolver-gated), whitelist
editada, binding cruzado, fingerprint viejo, export→restore fallando
cerrado, y la frontera honesta del modelo de amenaza.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from an_kla import attest
from an_kla.canonical import digest_json
from an_kla.store import MemoryStore
from an_kla.write_policy import (
    WritePolicyError,
    policy_fingerprint,
    validate_write_authority,
)

PYTHON = sys.executable.replace("\\", "/")


def _make_store() -> MemoryStore:
    return MemoryStore(tempfile.TemporaryDirectory().name)


class AttestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = MemoryStore(self.root)
        self.root_revision = self.store.initialize()
        self._tmp_to_clean = self.temp

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _whitelist_with_python_dash_c(self) -> None:
        document = {
            "schema": "an-kla/attest-whitelist-v1",
            "entries": [
                {"argv": ["git", "rev-parse", "HEAD"]},
                {"argv_prefix": [PYTHON, "-c"], "deny_flags": []},
                {
                    "argv_prefix": ["git", "diff"],
                    "deny_flags": ["--ext-diff", "--textconv", "--output", "-o"],
                },
            ],
        }
        (self.root / ".an-kla" / "attest-whitelist.json").write_text(
            (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"),
            encoding="utf-8",
        )

    def _attest(self, argv: list[str], **kwargs) -> dict:
        return attest.attest_run(self.root, argv, **kwargs)

    def _authority_v2(self, candidate: dict, receipt_result: dict) -> dict:
        receipt = receipt_result["receipt"]
        return {
            "schema": "an-kla/write-authority-v2",
            "proposal_sha256": digest_json(candidate),
            "base_revision": candidate["base_revision"],
            "authority_class": "tool_observed",
            "issuer": {
                "kind": "tool",
                "id": "an-kla-attest",
                "configuration_fingerprint": "sha256:" + "b" * 64,
            },
            "evidence": [
                {
                    "kind": "attestation_receipt",
                    "id": receipt["receipt_id"],
                    "sha256": receipt_result["receipt_digest"],
                    "resolution": "verified",
                }
            ],
            "scope": {
                "streams": [candidate["stream"]],
                "representations": [candidate["requested_representation"]],
                "operations": [candidate["operation"]],
            },
        }

    def _plan_and_commit(
        self,
        candidate: dict,
        authority: dict,
        *,
        expect_commit_error: str | None = None,
    ) -> dict | None:
        planning = self.store.plan_write(candidate, authority)
        if expect_commit_error is None:
            return self.store.commit_write_plan(
                expected_current_hash=candidate["base_revision"],
                proposal=candidate,
                authority=authority,
                decision=planning["decision"],
                plan=planning["plan"],
            )
        with self.assertRaises(WritePolicyError) as caught:
            self.store.commit_write_plan(
                expected_current_hash=candidate["base_revision"],
                proposal=candidate,
                authority=authority,
                decision=planning["decision"],
                plan=planning["plan"],
            )
        self.assertEqual(caught.exception.code, expect_commit_error)
        return None

    def _candidate(
        self, record_id: str, representation: str = "summary"
    ) -> dict:
        return {
            "schema": "an-kla/write-proposal-v1",
            "base_revision": self.store.read_current(),
            "stream": "facts",
            "operation": "add",
            "requested_representation": representation,
            "record": {"id": record_id, "text": "observado por el motor"},
            "lineage": {"derived_from_retrieval": False, "refs": []},
        }


class InitAndWhitelistTests(AttestBase):
    def test_init_creates_key_0600_and_whitelist(self) -> None:
        key = self.root / ".an-kla" / "attest.key"
        self.assertTrue(key.exists())
        self.assertEqual(key.stat().st_mode & 0o777, 0o600)
        self.assertTrue((self.root / ".an-kla" / "attest-whitelist.json").exists())

    def test_attest_init_is_idempotent(self) -> None:
        result = attest.ensure_attest_files(self.root)
        self.assertEqual(result["created"], [])
        self.assertEqual(
            sorted(result["existed"]), ["attest-whitelist.json", "attest.key"]
        )

    def test_whitelist_matching_exact_prefix_and_deny(self) -> None:
        document = attest.load_whitelist(self.root)
        self.assertFalse(attest.command_allowed(document, ["git", "push"]))
        self.assertFalse(attest.command_allowed(document, ["git"]))
        self.assertTrue(attest.command_allowed(document, ["git", "rev-parse", "HEAD"]))
        diff = {
            "schema": document["schema"],
            "entries": [document["entries"][1]],
        }
        self.assertTrue(
            attest.command_allowed(diff, ["git", "diff", "--stat"])
        )
        self.assertFalse(
            attest.command_allowed(diff, ["git", "diff", "--output=/tmp/x"])
        )
        self.assertFalse(
            attest.command_allowed(diff, ["git", "diff", "--ext-diff"])
        )

    def test_run_without_whitelisted_command_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            WritePolicyError, "attest_command_not_allowed"
        ):
            self._attest([PYTHON, "-c", "print('nope')"])

    def test_run_without_key_fails_closed(self) -> None:
        (self.root / ".an-kla" / "attest.key").unlink()
        with self.assertRaisesRegex(WritePolicyError, "attest_not_initialized"):
            self._attest(["git", "rev-parse", "HEAD"])


class ReceiptLifecycleTests(AttestBase):
    def setUp(self) -> None:
        super().setUp()
        self._whitelist_with_python_dash_c()

    def test_happy_path_receipt_is_signed_and_addressed(self) -> None:
        result = self._attest(
            [PYTHON, "-c", "print('ok')"],
            now="2026-09-01T00:00:00Z",
            nonce="nonce-1",
        )
        receipt = result["receipt"]
        self.assertEqual(receipt["exit_code"], 0)
        self.assertFalse(receipt["truncated"])
        self.assertTrue(
            (self.root / result["receipt_path"]).exists()
        )
        path = attest.receipt_path(self.root, result["receipt_digest"])
        self.assertTrue(path.exists())

    def test_output_cap_marks_truncated(self) -> None:
        result = self._attest(
            [PYTHON, "-c", "print('x' * 1000)"],
            output_cap_bytes=8,
        )
        self.assertTrue(result["receipt"]["truncated"])

    def test_nonzero_exit_receipt_has_no_authority(self) -> None:
        result = self._attest([PYTHON, "-c", "raise SystemExit(3)"])
        self.assertEqual(result["receipt"]["exit_code"], 3)
        candidate = self._candidate("f-e1")
        authority = self._authority_v2(candidate, result)
        # Plan (engine, caller-trusted) produce decisión; el engine en
        # commit verifica exit_code==0 → receipt_invalid.
        self._plan_and_commit(
            candidate, authority, expect_commit_error="receipt_invalid"
        )

    def test_timeout_yields_attest_timeout_without_receipt(self) -> None:
        with self.assertRaisesRegex(WritePolicyError, "attest_timeout"):
            self._attest(
                [PYTHON, "-c", "import time; time.sleep(30)"],
                timeout_seconds=0.5,
            )
        self.assertEqual(
            list((self.root / ".an-kla" / "receipts" / "receipts" / "sha256").glob("*")),
            [],
        )

    def test_fingerprint_change_kills_receipt(self) -> None:
        with patch(
            "an_kla.attest.policy_fingerprint",
            return_value="sha256:" + "0" * 64,
        ):
            result = self._attest([PYTHON, "-c", "print('ok')"])
        candidate = self._candidate("f-e2")
        authority = self._authority_v2(candidate, result)
        self._plan_and_commit(
            candidate, authority, expect_commit_error="receipt_invalid"
        )

    def test_whitelist_edit_between_mint_and_verify(self) -> None:
        result = self._attest([PYTHON, "-c", "print('ok')"])
        # Edición real: se añade una entrada → el digest cambia aunque el
        # comando del receipt siga permitido.
        document = attest.load_whitelist(self.root)
        document["entries"].append({"argv_prefix": ["sha256sum"], "deny_flags": []})
        (self.root / ".an-kla" / "attest-whitelist.json").write_text(
            json.dumps(document, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        candidate = self._candidate("f-e3")
        authority = self._authority_v2(candidate, result)
        self._plan_and_commit(
            candidate, authority, expect_commit_error="receipt_whitelist_changed"
        )


class ToolObservedAuthorityTests(AttestBase):
    def setUp(self) -> None:
        super().setUp()
        self._whitelist_with_python_dash_c()
        self.receipt_result = self._attest(
            [PYTHON, "-c", "print('ok')"],
            now="2026-09-01T00:00:00Z",
            nonce="nonce-e2e",
        )

    def test_e2e_full_representation_commit_and_retrieval(self) -> None:
        candidate = self._candidate("f-observado", representation="full")
        authority = self._authority_v2(candidate, self.receipt_result)
        result = self._plan_and_commit(candidate, authority)
        assert result is not None
        self.assertTrue(result["committed"])
        self.assertEqual(result["decision"], "write-full")
        self.assertIn("tool_evidence_verified", result["reason_codes"])
        tombstones = list(
            (self.root / ".an-kla" / "receipts" / "nonces" / "sha256").glob("*")
        )
        self.assertEqual(len(tombstones), 1)

    def test_replay_same_receipt_on_second_commit(self) -> None:
        first = self._candidate("f-a", representation="full")
        self._plan_and_commit(first, self._authority_v2(first, self.receipt_result))
        second = self._candidate("f-b", representation="full")
        self._plan_and_commit(
            second, self._authority_v2(second, self.receipt_result),
            expect_commit_error="receipt_replayed",
        )
        snapshot = self.store.snapshot()
        ids = [row["id"] for row in snapshot.records["facts"]]
        self.assertIn("f-a", ids)
        self.assertNotIn("f-b", ids)

    def test_forged_receipt_without_file_fails_at_engine(self) -> None:
        # API Python es caller-trusted en plan (frontera ADR-0046 §4):
        # plan_write no verifica; el engine re-verifica bajo lock.
        candidate = self._candidate("f-forged", representation="full")
        authority = {
            "schema": "an-kla/write-authority-v2",
            "proposal_sha256": digest_json(candidate),
            "base_revision": candidate["base_revision"],
            "authority_class": "tool_observed",
            "issuer": {
                "kind": "tool",
                "id": "an-kla-attest",
                "configuration_fingerprint": "sha256:" + "b" * 64,
            },
            "evidence": [
                {
                    "kind": "attestation_receipt",
                    "id": "fabricado",
                    "sha256": "sha256:" + "c" * 64,
                    "resolution": "verified",
                }
            ],
            "scope": {
                "streams": ["facts"],
                "representations": ["full"],
                "operations": ["add"],
            },
        }
        planning = self.store.plan_write(candidate, authority)
        self.assertEqual(planning["decision"]["decision"], "write-full")
        self._plan_and_commit(
            candidate, authority, expect_commit_error="receipt_invalid"
        )
        self.assertEqual(self.store.read_current(), candidate["base_revision"])

    def test_cross_store_binding_fails_closed(self) -> None:
        import shutil

        with tempfile.TemporaryDirectory() as other_dir:
            other_root = Path(other_dir)
            other = MemoryStore(other_root)
            other.initialize()
            # Se copian clave + whitelist + receipt: aísla el check de
            # binding — otro store = otro project_uuid/store_identity
            # (todo lo demás verifica; el binding es la única diferencia).
            shutil.copy(
                self.root / ".an-kla" / "attest.key",
                other_root / ".an-kla" / "attest.key",
            )
            shutil.copy(
                self.root / ".an-kla" / "attest-whitelist.json",
                other_root / ".an-kla" / "attest-whitelist.json",
            )
            receipt_src = attest.receipt_path(
                self.root, self.receipt_result["receipt_digest"]
            )
            receipt_dst = attest.receipt_path(
                other_root, self.receipt_result["receipt_digest"]
            )
            receipt_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(receipt_src, receipt_dst)
            candidate = self._candidate("f-x", representation="full")
            authority = self._authority_v2(candidate, self.receipt_result)
            with self.assertRaises(WritePolicyError) as caught:
                attest.verify_receipt_for_authority(other, authority)
            self.assertEqual(
                caught.exception.code, "receipt_identity_mismatch"
            )

    def test_tampered_command_digest_breaks_hmac(self) -> None:
        candidate = self._candidate("f-tamper", representation="full")
        authority = self._authority_v2(candidate, self.receipt_result)
        item = authority["evidence"][0]
        target = attest.receipt_path(self.root, item["sha256"])
        receipt = json.loads(target.read_text("utf-8"))
        receipt["command"] = ["evil", "command"]
        target.write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
        self._plan_and_commit(
            candidate, authority, expect_commit_error="receipt_invalid"
        )

    def test_pre_existing_tombstone_blocks_early(self) -> None:
        nonce = self.receipt_result["receipt"]["nonce"]
        tomb_dir = self.root / ".an-kla" / "receipts" / "nonces" / "sha256"
        tomb_dir.mkdir(parents=True, exist_ok=True)
        digest = attest.tombstone_path(self.root, nonce).name
        (tomb_dir / digest).write_text("{}", encoding="utf-8")
        candidate = self._candidate("f-squat", representation="full")
        authority = self._authority_v2(candidate, self.receipt_result)
        self._plan_and_commit(
            candidate, authority, expect_commit_error="receipt_replayed"
        )


class EnforcementBoundaryTests(AttestBase):
    def setUp(self) -> None:
        super().setUp()
        self._whitelist_with_python_dash_c()
        from an_kla.__main__ import _cli_authority

        self._cli_authority = _cli_authority

    def test_tool_observed_without_receipt_rejected_at_cli(self) -> None:
        authority = {
            "schema": "an-kla/write-authority-v2",
            "authority_class": "tool_observed",
            "evidence": [],
        }
        with self.assertRaisesRegex(
            ValueError, "cli_privileged_authority_unresolved"
        ):
            self._cli_authority(authority, self.store)

    def test_channel_confirmed_still_rejected_at_cli(self) -> None:
        with self.assertRaisesRegex(
            ValueError, "cli_privileged_authority_unresolved"
        ):
            self._cli_authority(
                {"schema": "x", "authority_class": "channel_confirmed"},
                self.store,
            )

    def test_tool_observed_with_valid_receipt_passes_cli_gate(self) -> None:
        result = self._attest([PYTHON, "-c", "print('ok')"])
        candidate = self._candidate("f-cli", representation="full")
        authority = self._authority_v2(candidate, result)
        self.assertIs(self._cli_authority(authority, self.store), authority)

    def test_v1_cannot_express_attestation_receipt(self) -> None:
        authority = {
            "schema": "an-kla/write-authority-v1",
            "proposal_sha256": "sha256:" + "a" * 64,
            "base_revision": "sha256:" + "a" * 64,
            "authority_class": "tool_observed",
            "issuer": {
                "kind": "tool",
                "id": "an-kla-attest",
                "configuration_fingerprint": "sha256:" + "b" * 64,
            },
            "evidence": [
                {
                    "kind": "attestation_receipt",
                    "id": "x",
                    "sha256": "sha256:" + "c" * 64,
                    "resolution": "verified",
                }
            ],
            "scope": {
                "streams": ["facts"],
                "representations": ["summary"],
                "operations": ["add"],
            },
        }
        with self.assertRaisesRegex(WritePolicyError, "invalid_write_authority"):
            validate_write_authority(authority)

    def test_schema_v2_published_and_validates(self) -> None:
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema no instalado (extra test)")
        schema = json.loads(
            (Path(__file__).parents[1] / "an_kla" / "schemas" / "write-authority-v2.schema.json")
            .read_text("utf-8")
        )
        jsonschema.Draft202012Validator.check_schema(schema)


class ExportRestoreTests(AttestBase):
    def test_receipts_survive_bundle_but_not_verification(self) -> None:
        from an_kla.export_restore import create_export, restore_export

        self._whitelist_with_python_dash_c()
        result = self._attest([PYTHON, "-c", "print('ok')"])
        bundle = self.root / "bundle.tar.gz"
        create_export(self.store, bundle)
        with tempfile.TemporaryDirectory() as target:
            restored = MemoryStore(Path(target))
            restore_export(bundle, Path(target))
            candidate = self._candidate("f-r", representation="full")
            authority = self._authority_v2(candidate, result)
            planning = self.store.plan_write(candidate, authority)
            # La clave no viaja en el export: verificación falla cerrada.
            with self.assertRaises(WritePolicyError) as caught:
                restored.commit_write_plan(
                    expected_current_hash=candidate["base_revision"],
                    proposal=candidate,
                    authority=authority,
                    decision=planning["decision"],
                    plan=planning["plan"],
                )
            self.assertEqual(caught.exception.code, "attest_not_initialized")


class CliSurfaceTests(AttestBase):
    """Ronda de fase S2 (BLOCKER): el parser real y el CLI ejecutable."""

    def test_parser_keeps_command_and_attest_argv_separate(self) -> None:
        from an_kla.cli_parser import build_parser

        args = build_parser().parse_args(
            ["attest", "run", "--", "git", "rev-parse", "HEAD"]
        )
        self.assertEqual(args.command, "attest")
        self.assertEqual(args.attest_command, "run")
        self.assertEqual(args.attest_argv, ["--", "git", "rev-parse", "HEAD"])

    def test_cli_attest_run_e2e_mints_receipt(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "an_kla", "--no-update-check",
             "--project-root", str(self.root),
             "attest", "run", "--", "git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        # Repo temporal sin Git: exit 128 acuña receipt de diagnóstico,
        # pero el comando `attest run` en sí termina 0.
        self.assertEqual(payload["receipt"]["exit_code"], 128)
        self.assertTrue(
            (self.root / payload["receipt_path"]).exists()
        )

    def test_cli_refute_with_receipt_stays_resolver_gated(self) -> None:
        """ADR-0046 §7: los receipts attest NO alimentan refute en v1."""
        from an_kla.refute_contracts import RefutePolicyError

        target_sha = "sha256:" + "d" * 64
        proposal = {
            "schema": "an-kla/refute-proposal-v1",
            "base_revision": self.store.read_current(),
            "stream": "facts",
            "target_record_sha256": target_sha,
            "reason": "evidence_contradicts_record",
        }
        claim = {
            "schema": "an-kla/refute-authority-claim-v1",
            "proposal_sha256": digest_json(proposal),
            "base_revision": proposal["base_revision"],
            "requested_authority_class": "tool_observed",
            "issuer_claim": {
                "kind": "tool",
                "subject_sha256": "sha256:" + "1" * 64,
                "configuration_fingerprint": "sha256:" + "2" * 64,
            },
            "evidence": [
                {"kind": "attestation_receipt", "id": "x", "resolution": "verified"}
            ],
            "scope": {
                "operation": "refute",
                "stream": "facts",
                "target_record_sha256": target_sha,
            },
        }
        try:
            planning = self.store.plan_refute(proposal, claim)
        except RefutePolicyError as exc:
            # Fail-closed por validación del claim (evidence.kind fuera del
            # enum v1 del claim): igual de cerrado.
            self.assertEqual(exc.code, "invalid_refute_authority_claim")
            return
        self.assertEqual(planning["decision"]["decision"], "skip")
        self.assertEqual(
            planning["decision"]["reason"],
            "refute_authority_resolver_unavailable",
        )


if __name__ == "__main__":
    unittest.main()
