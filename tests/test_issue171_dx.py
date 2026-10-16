"""test_issue171_dx.py — DX del consumidor (#171, PR A).

1. ``budget_too_small_for_resume_snapshot`` informa el presupuesto mínimo
   exacto (``minimum_budget_bytes``), medido sobre la proyección completa y
   correcto en la frontera de ancho decimal.
2. ``invalid_transaction_id`` declara el formato esperado, con el mismo exit
   code en todos los caminos (``init`` incluido) y sin repetir el valor.
3. ``check-updates`` nombra ambas formas de instalación (uv tool / venv pip).
4. ``status`` expone qué instalación respondió, sin rutas.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from an_kla.canonical import canonical_json
from an_kla.checkpoints import commit_checkpoint, plan_checkpoint
from an_kla.resume import ResumeBudgetError, _minimum_budget, resume
from an_kla.store import MemoryStore
from an_kla.transaction_attempts import TRANSACTION_ID_HINT, is_canonical_uuid
from an_kla.update_check import _build_notice
from an_kla.version import VERSION

from tests.test_checkpoints import _authority, _state

ROOT = Path(__file__).resolve().parents[1]
BAD_IDS = ("cp-20261016T000000-auditoria", "6F9619FF-8B86-D011-B42D-00C04FC964FF")


def _cli(root: Path, args: list) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ["PATH"], "AN_KLA_NO_UPDATE_CHECK": "1"}
    return subprocess.run(
        [sys.executable, "-m", "an_kla", "--project-root", str(root)] + args,
        capture_output=True, text=True, cwd=str(ROOT), env=env,
    )


class ResumeMinimumBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MemoryStore(self.temp.name)
        self.store.initialize()
        # Checkpoint mayor que el ejemplo `--budget 4096` del contrato, como
        # en el consumidor que reportó #171.
        state = _state(self.store.snapshot().manifest["checkpoint"], "x" * 5000)
        planning = plan_checkpoint(self.store, state, _authority(self.store, state))
        commit_checkpoint(
            self.store, planning, self.store.read_current(),
            transaction_id=str(uuid.uuid4()),
        )

    def _assert_minimum_is_exact(self, provided: int, query: str | None) -> int:
        with self.assertRaises(ResumeBudgetError) as caught:
            resume(self.store, provided, query=query)
        exc = caught.exception
        self.assertEqual(str(exc), "budget_too_small_for_resume_snapshot")
        minimum = exc.minimum_budget_bytes
        self.assertIsInstance(minimum, int)
        self.assertGreater(minimum, provided)
        self.assertEqual(exc.provided_budget_bytes, provided)
        fitted = resume(self.store, minimum, query=query)
        self.assertLessEqual(fitted["used_bytes"], minimum)
        self.assertEqual(fitted["used_bytes"], len(canonical_json(fitted)))
        if minimum - 1 > provided:
            with self.assertRaises(ResumeBudgetError):
                resume(self.store, minimum - 1, query=query)
        return minimum

    def test_minimum_is_exact_from_several_starting_budgets(self) -> None:
        for query in (None, "estado actual"):
            for provided in (0, 1, 999, 4096):
                with self.subTest(query=query, provided=provided):
                    minimum = self._assert_minimum_is_exact(provided, query)
                    self.assertGreater(minimum, 4096)

    def test_minimum_accounts_for_budget_decimal_width(self) -> None:
        # Tamaño = 9998 + ancho decimal del budget: el ingenuo 10002 (medido a
        # 9999) no cabe a 10002; el mínimo real es 10003.
        def project(limit: int):
            return None, 9998 + len(str(limit))

        self.assertEqual(_minimum_budget(project, 1), 10003)
        self.assertEqual(_minimum_budget(project, 10003), 10004)

    def test_cli_reports_minimum_without_paths(self) -> None:
        project_root = Path(self.temp.name)
        with self.assertRaises(ResumeBudgetError) as caught:
            resume(self.store, 1)
        minimum = caught.exception.minimum_budget_bytes
        result = _cli(project_root, ["resume", "--budget", "1"])
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stderr,
            "an-kla error: budget_too_small_for_resume_snapshot "
            f"(minimum_budget_bytes={minimum}, provided_budget_bytes=1)\n",
        )
        self.assertNotIn(self.temp.name, result.stderr)


class TransactionIdHintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def _assert_hinted(self, result: subprocess.CompletedProcess, bad: str) -> None:
        self.assertEqual(result.returncode, 2)
        self.assertEqual(
            result.stderr,
            f"an-kla error: invalid_transaction_id ({TRANSACTION_ID_HINT})\n",
        )
        self.assertNotIn(bad, result.stderr)

    def test_predicate_requires_lowercase_canonical_form(self) -> None:
        self.assertTrue(is_canonical_uuid(str(uuid.uuid4())))
        for bad in BAD_IDS + ("{%s}" % uuid.uuid4(), None, 7):
            with self.subTest(bad=bad):
                self.assertFalse(is_canonical_uuid(bad))

    def test_init_and_transaction_inspect_share_hint_and_exit_code(self) -> None:
        for bad in BAD_IDS:
            with self.subTest(command="init", bad=bad):
                self._assert_hinted(_cli(self.root, ["init", "--transaction-id", bad]), bad)
        self.assertEqual(_cli(self.root, ["init"]).returncode, 0)
        for bad in BAD_IDS:
            with self.subTest(command="transaction inspect", bad=bad):
                self._assert_hinted(
                    _cli(self.root, ["transaction", "inspect", bad]), bad)

    def test_help_declares_format(self) -> None:
        for command in (["checkpoint", "commit"], ["init"], ["commit-write-plan"]):
            with self.subTest(command=command):
                result = _cli(self.root, command + ["--help"])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("RFC 4122", " ".join(result.stdout.split()))


class InstallAndRuntimeTests(unittest.TestCase):
    def test_update_notice_names_both_install_forms(self) -> None:
        notice = _build_notice("0.1.0b31", "v0.1.0-beta.32", None)
        self.assertIn("uv tool install --force", notice)
        self.assertIn("-m pip install --upgrade", notice)
        self.assertNotIn("python -m pip", notice)
        self.assertEqual(notice.count("@v0.1.0-beta.32"), 2)

    def test_status_reports_runtime_without_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(_cli(root, ["init"]).returncode, 0)
            result = _cli(root, ["status"])
            self.assertEqual(result.returncode, 0, result.stderr)
            runtime = json.loads(result.stdout)["runtime"]
            self.assertEqual(
                runtime, {"entrypoint": "module", "package_version": VERSION})


if __name__ == "__main__":
    unittest.main()
