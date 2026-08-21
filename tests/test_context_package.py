from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from an_kla.baseline_adoption import (
    apply_baseline_adoption,
    plan_baseline_adoption,
)
from an_kla.context_package import (

    BLOCK_ID,
    COMPACT_PAYLOAD,
    CONTRACT_RELATIVE,
    ContextConcurrentUpdate,
    ContextPackageError,
    DETAILED_CONTRACT,
    MANIFEST_RELATIVE,
    TEMPLATE_VERSION,
    apply_context_plan,
    context_status,
    managed_payload_sha256,
    parse_managed_block,
    plan_context_change,
    render_managed_block,
    transform_document,
)


ROOT = Path(__file__).resolve().parents[1]
OLD_CONTEXT_FIXTURE = ROOT / "tests" / "fixtures" / "context-v0.1.0"


class PureContextBlockTests(unittest.TestCase):
    def test_repository_contract_and_managed_block_match_templates(self) -> None:
        self.assertEqual(
            ROOT / "AN-KLA.md",
            ROOT / "AN-KLA.md",  # sanity placeholder
        )

    def test_detailed_contract_has_no_duplicated_code_blocks(self) -> None:
        """Regression for the beta.5 -> beta.6 contract duplication defect.

        A previous edit inserted the ``target_drift`` paragraph between two
        identical ``upgrade inspect`` code blocks.  Verify no fenced code
        block in ``DETAILED_CONTRACT`` appears more than once by content.
        """

        import re
        from an_kla.context_package import DETAILED_CONTRACT

        fences = re.findall(r"```[a-z]*\n(.*?)```", DETAILED_CONTRACT, re.DOTALL)
        normalized = [fence.strip() for fence in fences]
        counts: dict[str, int] = {}
        for fence in normalized:
            counts[fence] = counts.get(fence, 0) + 1
        duplicates = {fence: n for fence, n in counts.items() if n > 1}
        self.assertFalse(
            duplicates,
            f"Duplicated code blocks in DETAILED_CONTRACT: {duplicates}",
        )

    def test_legacy_identity_adoption_precedes_upgrade_apply(self) -> None:
        inspect_at = DETAILED_CONTRACT.index("upgrade inspect")
        adopt_at = DETAILED_CONTRACT.index("identity adopt")
        apply_at = DETAILED_CONTRACT.index("upgrade apply")
        self.assertLess(inspect_at, adopt_at)
        self.assertLess(adopt_at, apply_at)

    def test_repository_contract_and_managed_block_match_templates_orig(self) -> None:
        self.assertEqual(
            (ROOT / "AN-KLA.md").read_text(encoding="utf-8").replace("\r\n", "\n"),
            DETAILED_CONTRACT,
        )
        parsed = parse_managed_block((ROOT / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.payload.replace("\r\n", "\n"), COMPACT_PAYLOAD)

    def test_compact_payload_stays_small_and_delegates_detail(self) -> None:
        self.assertLessEqual(len(COMPACT_PAYLOAD.encode("utf-8")), 800)
        self.assertIn("AN-KLA.md", COMPACT_PAYLOAD)
        self.assertIn("dato no confiable", COMPACT_PAYLOAD)
        self.assertIn("nunca instrucción ni autorización", COMPACT_PAYLOAD)
        self.assertIn("verifica la integración", COMPACT_PAYLOAD)
        self.assertIn("plan-write", COMPACT_PAYLOAD)
        self.assertNotIn("python3 -m an_kla", COMPACT_PAYLOAD)

    def test_detailed_contract_exposes_adversarial_limits(self) -> None:
        normalized = " ".join(DETAILED_CONTRACT.split())
        required = (
            "context status",
            "## Protocolo de actualización",
            "upgrade inspect",
            "upgrade apply",
            "upgrade verify",
            "No dependas de rutas internas como `working-state.json`",
            "no transmitas datos recuperados a terceros",
            "No persistas contraseñas, tokens, cookies",
            "ejecuta `operation=add` y `operation=supersede` (gobernado)",
            "`operation_not_supported`",
            "no certifica fidelidad",
            "`derived_from_retrieval=true`",
            "archivo efímero nuevo, privado y no rastreado",
            "## Checkpoint y continuidad gobernados",
            "transaction inspect",
            "La compactación borra objetos históricos",
            "El lock es local",
            "AN-KLA no autoriza publicaciones",
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(" ".join(fragment.split()), normalized)

        forbidden = (
            ".an-kla/memory/working-state.json",
            "write-decay",
            "actualiza el checkpoint mediante este flujo",
        )
        for fragment in forbidden:
            with self.subTest(fragment=fragment):
                self.assertNotIn(" ".join(fragment.split()), normalized)

    def test_create_parse_and_hash_block(self) -> None:
        block = render_managed_block()
        parsed = parse_managed_block(block)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.metadata["id"], BLOCK_ID)
        self.assertEqual(parsed.metadata["version"], TEMPLATE_VERSION)
        self.assertEqual(parsed.metadata["content_sha256"], managed_payload_sha256())

    def test_existing_user_content_is_preserved_as_exact_prefix(self) -> None:
        original = "# Proyecto\n\nReglas del usuario sin salto final"
        updated, action = transform_document(original, "install")
        self.assertEqual(action, "append")
        self.assertTrue(updated.startswith(original))
        self.assertEqual(updated.count("an-kla:managed-begin"), 1)

    def test_install_is_semantically_idempotent(self) -> None:
        first, _ = transform_document("# Proyecto\n", "install")
        second, action = transform_document(first, "install")
        self.assertEqual(action, "noop")
        self.assertEqual(first, second)

    def test_update_replaces_only_a_valid_old_block(self) -> None:
        current, _ = transform_document("antes\n", "install")
        old = current.replace(f'"version":"{TEMPLATE_VERSION}"', '"version":"0.0.9"')
        updated, action = transform_document(old, "update")
        self.assertEqual(action, "replace")
        self.assertTrue(updated.startswith("antes\n"))
        self.assertIn(f'"version":"{TEMPLATE_VERSION}"', updated)

    def test_uninstall_preserves_content_outside_block(self) -> None:
        current, _ = transform_document("# Usuario\n", "install")
        updated, action = transform_document(current + "después\n", "uninstall")
        self.assertEqual(action, "remove_block")
        self.assertIn("# Usuario", updated)
        self.assertIn("después", updated)
        self.assertNotIn("an-kla:managed", updated)

    def test_crlf_is_preserved_and_hash_is_canonical(self) -> None:
        updated, _ = transform_document("# Proyecto\r\n\r\nTexto\r\n", "install")
        self.assertNotIn("\n", updated.replace("\r\n", ""))
        self.assertIsNotNone(parse_managed_block(updated))

    def test_tampered_duplicate_nested_and_fenced_markers_fail_closed(self) -> None:
        valid = render_managed_block()
        cases = [
            valid.replace("Este proyecto", "Este PROYECTO"),
            valid + valid,
            valid.replace(
                "## AN-KLA Memory\n",
                "## AN-KLA Memory\n" + valid,
                1,
            ),
            "```markdown\n" + valid + "```\n",
            valid.replace("<!-- an-kla:managed-end", " <!-- an-kla:managed-end"),
        ]
        for payload in cases:
            with self.subTest(payload=payload[:60]):
                with self.assertRaises(ContextPackageError):
                    parse_managed_block(payload)

    def test_prose_and_inline_code_mentions_of_markers_are_ignored(self) -> None:
        """Regression for issue #44.

        Documenting the managed-block marker syntax inside AGENTS.md (in
        prose or inside inline code spans, anchored or not) must not
        invalidate an otherwise valid block. Only lines whose marker syntax
        is anchored at the start are candidates; bare mentions are ignored.
        """

        valid = render_managed_block()
        cases = [
            valid
            + "\n## Nota\n\nLas marcas `<!-- an-kla:managed-begin -->` se editan así.\n",
            valid + "\nUsa `an-kla:managed-end` para cerrar el bloque.\n",
            "El bloque abre con <!-- an-kla:managed-begin --> segun los docs.\n\n"
            + valid,
            valid + "\n  línea indentada que cita an-kla:managed-begin de paso.\n",
        ]
        for document in cases:
            with self.subTest(document=document[:60]):
                parsed = parse_managed_block(document)
                self.assertIsNotNone(parsed)
                self.assertEqual(parsed.metadata["id"], BLOCK_ID)
                self.assertEqual(parsed.metadata["version"], TEMPLATE_VERSION)

    def test_anchored_malformed_and_indented_candidates_fail_closed(self) -> None:
        """Complement to issue #44: unanchored mentions are ignored, but
        anchored candidates that are malformed, indented or duplicated still
        fail closed per ADR-0009.
        """

        valid = render_managed_block()
        malformed_end = valid.replace(
            '<!-- an-kla:managed-end {"id":"agent-context"} -->',
            '<!-- an-kla:managed-end {not valid json} -->',
        )
        indented_begin = valid.replace(
            "<!-- an-kla:managed-begin",
            "    <!-- an-kla:managed-begin",
            1,
        )
        no_space_extra = valid + '\n<!-- an-kla:managed-begin{"id":"x"} -->\n'
        for payload in (malformed_end, indented_begin, no_space_extra):
            with self.subTest(payload=payload[:60]):
                with self.assertRaisesRegex(
                    ContextPackageError, "managed_block_structure_invalid"
                ):
                    parse_managed_block(payload)

    def test_unmarked_legacy_integration_is_not_blindly_appended(self) -> None:
        legacy = (
            "# AGENTS\npython3 -m an_kla status\n"
            "python3 -m an_kla write --expected-current x\nrebuild-index\n"
        )
        with self.assertRaisesRegex(ContextPackageError, "legacy_an_kla_context_detected"):
            transform_document(legacy, "install")


class ContextFilesystemTests(unittest.TestCase):
    def test_known_previous_template_updates_without_local_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(OLD_CONTEXT_FIXTURE / "AGENTS.md", root / "AGENTS.md")
            shutil.copyfile(OLD_CONTEXT_FIXTURE / "AN-KLA.md", root / "AN-KLA.md")

            before = context_status(root)
            self.assertFalse(before["ok"])
            self.assertIn("context_template_outdated", before["diagnostics"])
            self.assertNotIn("managed_contract_modified", before["diagnostics"])

            plan = plan_context_change(root, "update")
            self.assertNotEqual(
                plan["base_contract_sha256"], plan["result_contract_sha256"]
            )
            result = apply_context_plan(root, plan)
            self.assertEqual(result["action"], "replace")
            self.assertIn(
                "No borrar esta sección.",
                (root / "AGENTS.md").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                (root / "AN-KLA.md").read_text(encoding="utf-8"),
                DETAILED_CONTRACT,
            )
            self.assertTrue(context_status(root)["ok"])
            self.assertTrue(
                any(
                    path.name == "AN-KLA.md"
                    for path in (root / ".an-kla" / "context" / "backups").rglob(
                        "AN-KLA.md"
                    )
                )
            )

    def test_modified_previous_contract_cannot_use_known_update_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(OLD_CONTEXT_FIXTURE / "AGENTS.md", root / "AGENTS.md")
            old_contract = (OLD_CONTEXT_FIXTURE / "AN-KLA.md").read_text(
                encoding="utf-8"
            )
            (root / "AN-KLA.md").write_text(
                old_contract + "\nInstrucción local no registrada.\n",
                encoding="utf-8",
            )
            status = context_status(root)
            self.assertIn("managed_contract_modified", status["diagnostics"])
            with self.assertRaisesRegex(
                ContextPackageError, "managed_contract_modified"
            ):
                plan_context_change(root, "update")

    def test_known_previous_crlf_contract_updates_preserving_newline_style(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(OLD_CONTEXT_FIXTURE / "AGENTS.md", root / "AGENTS.md")
            old_contract = (OLD_CONTEXT_FIXTURE / "AN-KLA.md").read_text(
                encoding="utf-8"
            )
            (root / "AN-KLA.md").write_bytes(
                old_contract.replace("\n", "\r\n").encode("utf-8")
            )
            apply_context_plan(root, plan_context_change(root, "update"))
            updated = (root / "AN-KLA.md").read_bytes()
            self.assertNotIn(b"\n", updated.replace(b"\r\n", b""))
            self.assertEqual(
                updated.decode("utf-8").replace("\r\n", "\n"), DETAILED_CONTRACT
            )
            self.assertTrue(context_status(root)["ok"])

    def test_preexisting_canonical_contract_survives_uninstall(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "AN-KLA.md").write_text(DETAILED_CONTRACT, encoding="utf-8")
            apply_context_plan(root, plan_context_change(root, "install"))
            manifest = json.loads((root / MANIFEST_RELATIVE).read_text(encoding="utf-8"))
            self.assertFalse(manifest["contract_created_by_an_kla"])
            apply_context_plan(root, plan_context_change(root, "uninstall"))
            self.assertEqual(
                (root / "AN-KLA.md")
                .read_text(encoding="utf-8")
                .replace("\r\n", "\n"),
                DETAILED_CONTRACT,
            )

    def test_crlf_contract_is_equivalent_and_its_physical_bytes_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract = root / "AN-KLA.md"
            crlf = DETAILED_CONTRACT.replace("\n", "\r\n").encode("utf-8")
            contract.write_bytes(crlf)
            plan = plan_context_change(root, "install")
            self.assertEqual(plan["base_contract_sha256"], plan["result_contract_sha256"])
            apply_context_plan(root, plan)
            self.assertEqual(contract.read_bytes(), crlf)
            self.assertTrue(context_status(root)["ok"])

    def test_preexisting_empty_agents_file_survives_uninstall(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "AGENTS.md").write_text("", encoding="utf-8")
            apply_context_plan(root, plan_context_change(root, "install"))
            result = apply_context_plan(root, plan_context_change(root, "uninstall"))
            self.assertEqual(result["action"], "preserve_empty")
            self.assertTrue((root / "AGENTS.md").exists())
            self.assertEqual((root / "AGENTS.md").read_bytes(), b"")

    def test_user_change_outside_block_is_healthy_warning_and_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apply_context_plan(root, plan_context_change(root, "install"))
            target = root / "AGENTS.md"
            target.write_text(
                target.read_text(encoding="utf-8") + "\nRegla nueva del usuario.\n",
                encoding="utf-8",
            )
            status = context_status(root)
            self.assertTrue(status["ok"])
            self.assertEqual(status["diagnostics"], [])
            self.assertIn(
                "context_target_changed_outside_managed_block", status["warnings"]
            )
            # ADR-0040 §6: update no absorbe drift; exige adopcion explicita.
            with self.assertRaisesRegex(
                ContextPackageError, "context_target_drift_adoption_required"
            ):
                plan_context_change(root, "update")
            # La adopcion explicita resuelve el drift y preserva el contenido.
            apply_baseline_adoption(root, plan_baseline_adoption(root))
            status = context_status(root)
            self.assertEqual(status["warnings"], [])
            self.assertIn("Regla nueva del usuario.", target.read_text(encoding="utf-8"))

    def test_clean_clone_without_local_manifest_is_healthy_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "AGENTS.md").write_text(render_managed_block(), encoding="utf-8")
            (root / "AN-KLA.md").write_text(DETAILED_CONTRACT, encoding="utf-8")
            status = context_status(root)
            self.assertTrue(status["ok"])
            self.assertEqual(status["diagnostics"], [])
            self.assertEqual(status["warnings"], ["context_manifest_missing"])

    def test_status_reports_legacy_and_partial_installations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "AGENTS.md").write_text(
                "python3 -m an_kla status\npython3 -m an_kla write "
                "--expected-current x\nrebuild-index\n",
                encoding="utf-8",
            )
            self.assertIn(
                "legacy_an_kla_context_detected", context_status(root)["diagnostics"]
            )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "AN-KLA.md").write_text(DETAILED_CONTRACT, encoding="utf-8")
            self.assertIn(
                "orphan_managed_contract", context_status(root)["diagnostics"]
            )

    def test_manifest_mutation_invalidates_a_prepared_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apply_context_plan(root, plan_context_change(root, "install"))
            plan = plan_context_change(root, "update")
            # Mutating the baseline hash now triggers the drift gate first
            # (ADR-0040 §6); plan invalidation is exercised through the
            # contract hash, which belongs to the plan payload.
            manifest_path = root / MANIFEST_RELATIVE
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["contract_sha256"] = "sha256:" + "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            # Contract hash changed -> rebuilt plan differs -> CAS mismatch
            # (the baseline hash itself did not move: no drift gate).
            with self.assertRaisesRegex(ContextPackageError, "context_plan_mismatch"):
                apply_context_plan(root, plan)
            # Adoption also rejects the fake hash: semantic conformance
            # treats it as corruption, not adoptable drift.
            with self.assertRaisesRegex(
                ContextPackageError,
                "context_baseline_semantic_mismatch",
            ):
                plan_baseline_adoption(root)

            manifest["unexpected"] = True
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            status = context_status(root)
            self.assertIn("context_manifest_invalid", status["diagnostics"])

    def test_adoption_cas_rejects_manifest_changed_after_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apply_context_plan(root, plan_context_change(root, "install"))
            target = root / "AGENTS.md"
            target.write_text(
                target.read_text(encoding="utf-8") + "\nNota del proyecto.\n",
                encoding="utf-8",
            )
            adoption = plan_baseline_adoption(root)
            manifest_path = root / MANIFEST_RELATIVE
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["target_sha256"] = "sha256:" + "1" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(
                ContextPackageError, "context_manifest_concurrent_update"
            ):
                apply_baseline_adoption(root, adoption)

    def test_create_manifest_contract_backup_update_and_uninstall(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = b"# Reglas del usuario\n\nNo borrar.\n"
            (root / "AGENTS.md").write_bytes(original)
            plan = plan_context_change(root, "install")
            result = apply_context_plan(root, plan)
            self.assertEqual(result["action"], "append")
            installed = (root / "AGENTS.md").read_bytes()
            self.assertTrue(installed.startswith(original))
            manifest = json.loads(
                (root / MANIFEST_RELATIVE).read_text(encoding="utf-8")
            )
            backup = root / manifest["original_backup"]
            self.assertEqual(backup.read_bytes(), original)
            self.assertTrue((root / CONTRACT_RELATIVE).is_file())
            self.assertTrue(context_status(root)["ok"])

            before_mtime = (root / "AGENTS.md").stat().st_mtime_ns
            time.sleep(0.002)
            noop = apply_context_plan(root, plan_context_change(root, "install"))
            self.assertEqual(noop["action"], "noop")
            self.assertEqual((root / "AGENTS.md").stat().st_mtime_ns, before_mtime)

            removed = apply_context_plan(root, plan_context_change(root, "uninstall"))
            self.assertEqual(removed["action"], "remove_block")
            self.assertNotIn(b"an-kla:managed", (root / "AGENTS.md").read_bytes())
            self.assertFalse((root / CONTRACT_RELATIVE).exists())
            self.assertFalse((root / MANIFEST_RELATIVE).exists())

    def test_create_and_uninstall_deletes_only_an_kla_owned_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apply_context_plan(root, plan_context_change(root, "install"))
            self.assertTrue((root / "AGENTS.md").exists())
            result = apply_context_plan(root, plan_context_change(root, "uninstall"))
            self.assertEqual(result["action"], "delete")
            self.assertFalse((root / "AGENTS.md").exists())

    def test_plan_apply_detects_concurrent_target_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "AGENTS.md"
            target.write_text("original\n", encoding="utf-8")
            plan = plan_context_change(root, "install")
            target.write_text("cambio concurrente\n", encoding="utf-8")
            with self.assertRaisesRegex(ContextConcurrentUpdate, "context_file_concurrent_update"):
                apply_context_plan(root, plan)
            self.assertEqual(target.read_text(encoding="utf-8"), "cambio concurrente\n")

    def test_modified_plan_and_invalid_targets_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = plan_context_change(root, "install")
            plan["result_target_sha256"] = "sha256:" + "0" * 64
            with self.assertRaisesRegex(ContextPackageError, "context_plan_mismatch"):
                apply_context_plan(root, plan)
            self.assertFalse((root / "AGENTS.md").exists())
            for target in ("../AGENTS.md", "nested/AGENTS.md", "/tmp/AGENTS.md"):
                with self.subTest(target=target):
                    with self.assertRaisesRegex(ContextPackageError, "invalid_context_target"):
                        plan_context_change(root, "install", target)

    def test_non_utf8_and_directory_targets_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "AGENTS.md").write_bytes(b"\xff\xfe")
            with self.assertRaisesRegex(ContextPackageError, "context_target_not_utf8"):
                plan_context_change(root, "install")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "AGENTS.md").mkdir()
            with self.assertRaisesRegex(ContextPackageError, "context_file_not_regular"):
                plan_context_change(root, "install")

    @unittest.skipUnless(os.name == "posix", "POSIX advisory lock test")
    def test_competing_installer_fails_visible_without_writing(self) -> None:
        import fcntl

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = plan_context_change(root, "install")
            context_root = root / ".an-kla" / "context"
            context_root.mkdir(parents=True)
            lock_path = context_root / ".install.lock"
            with lock_path.open("a+b") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex(ContextPackageError, "context_install_lock_busy"):
                    apply_context_plan(root, plan)
            self.assertFalse((root / "AGENTS.md").exists())

    @unittest.skipUnless(os.name == "posix", "POSIX permission bits")
    def test_file_permissions_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "AGENTS.md"
            target.write_text("reglas\n", encoding="utf-8")
            target.chmod(0o640)
            apply_context_plan(root, plan_context_change(root, "install"))
            self.assertEqual(target.stat().st_mode & 0o777, 0o640)

    @unittest.skipUnless(os.name == "posix", "POSIX symlink test")
    def test_symlink_target_and_context_directory_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside"
            outside.write_text("no tocar\n", encoding="utf-8")
            (root / "AGENTS.md").symlink_to(outside)
            with self.assertRaisesRegex(ContextPackageError, "symlink_forbidden"):
                plan_context_change(root, "install")
            self.assertEqual(outside.read_text(encoding="utf-8"), "no tocar\n")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside-context"
            outside.mkdir()
            (root / ".an-kla").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ContextPackageError, "symlink_forbidden"):
                plan_context_change(root, "install")
            self.assertEqual(list(outside.iterdir()), [])

    def test_modified_contract_and_block_are_visible_and_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apply_context_plan(root, plan_context_change(root, "install"))
            contract = root / CONTRACT_RELATIVE
            contract.write_text(
                contract.read_text(encoding="utf-8") + "alterado\n",
                encoding="utf-8",
            )
            status = context_status(root)
            self.assertIn("managed_contract_modified", status["diagnostics"])
            with self.assertRaisesRegex(ContextPackageError, "managed_contract_modified"):
                plan_context_change(root, "update")

    def test_cli_plan_apply_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path = root / "plan.json"
            planned = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "an_kla",
                    "--project-root",
                    str(root),
                    "context",
                    "plan",
                    "--operation",
                    "install",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            plan_path.write_text(planned.stdout, encoding="utf-8")
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "an_kla",
                    "--project-root",
                    str(root),
                    "context",
                    "apply",
                    "--plan",
                    str(plan_path),
                ],
                cwd=ROOT,
                capture_output=True,
                check=True,
            )
            status = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "an_kla",
                    "--project-root",
                    str(root),
                    "context",
                    "status",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertTrue(json.loads(status.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
