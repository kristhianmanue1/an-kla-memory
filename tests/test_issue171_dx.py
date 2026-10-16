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
from unittest import mock

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
        base = self.store.initialize()
        # Registros reales que casan con la query: en el mínimo entra evidence
        # y el resto cuenta en excluded_summary.budget.
        self.store.commit(
            expected_current_hash=base,
            checkpoint_patch={},
            facts=[
                {
                    "id": f"f-{i:02d}",
                    "schema": "an-kla/fact-v1",
                    "payload": {"text": f"estado actual del frente {i} " * 8},
                }
                for i in range(12)
            ],
        )
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

    def test_query_minimum_exercises_real_evidence(self) -> None:
        minimum = self._assert_minimum_is_exact(4096, "estado actual")
        fitted = resume(self.store, minimum, query="estado actual")
        self.assertGreater(
            len(fitted["retrieved_evidence"]) + fitted["excluded_summary"]["budget"], 0)
        roomy = resume(self.store, minimum + 4000, query="estado actual")
        self.assertGreater(len(roomy["retrieved_evidence"]), 0)

    def test_error_path_cost_is_bounded(self) -> None:
        # Regresión de la ronda post-implementación: sin salida temprana cada
        # proyección del error probaba todos los candidatos aunque el snapshot
        # no cupiera.  Con ella hay a lo sumo dos proyecciones completas (la
        # cota base y, si el contador excluded_summary.budget gana un dígito,
        # una más); las demás miden sólo el base.  Verificado: el mutante sin
        # salida temprana excede la cota.
        import an_kla.resume as resume_module

        with tempfile.TemporaryDirectory() as temp:
            store = MemoryStore(temp)
            base = store.initialize()
            store.commit(
                expected_current_hash=base,
                checkpoint_patch={},
                facts=[
                    {"id": f"f-{i:03d}", "schema": "an-kla/fact-v1",
                     "payload": {"text": "estado actual"}}
                    for i in range(200)
                ],
            )
            state = _state(store.snapshot().manifest["checkpoint"], "x" * 5000)
            planning = plan_checkpoint(store, state, _authority(store, state))
            commit_checkpoint(
                store, planning, store.read_current(),
                transaction_id=str(uuid.uuid4()),
            )
            calls = {"retrieve": 0, "size": 0}
            real_retrieve = resume_module.retrieve
            real_size = resume_module._size_at_fixed_point

            def counting_retrieve(*args, **kwargs):
                calls["retrieve"] += 1
                return real_retrieve(*args, **kwargs)

            def counting_size(value):
                calls["size"] += 1
                return real_size(value)

            with mock.patch.object(resume_module, "retrieve", counting_retrieve), \
                    mock.patch.object(resume_module, "_size_at_fixed_point", counting_size):
                with self.assertRaises(ResumeBudgetError) as caught:
                    resume(store, 4096, query="estado actual")
            minimum = caught.exception.minimum_budget_bytes
            selected = len(resume_module.retrieve(
                store, "estado actual", minimum,
                streams=("facts", "events", "episodes"))["selected"])
            self.assertGreater(selected, 100)
            self.assertLessEqual(calls["retrieve"], 8)
            self.assertLessEqual(calls["size"], calls["retrieve"] + 2 * (selected + 2))

    def test_minimum_band_search_handles_non_monotone_sizes(self) -> None:
        # Tamaño que salta al cruzar la banda de 4 dígitos: dentro de ella
        # nunca cabe (12000 > 9999); en 5 dígitos cabe desde 12000.  El punto
        # fijo sin bandas desde 10000 también da 12000, pero el salto exige
        # abandonar la banda en vez de iterar dentro de ella.
        def project(limit: int):
            return None, (9000 + limit // 1000) if limit < 9000 else 12000

        self.assertEqual(_minimum_budget(project, 1), 12000)

        # No monótono (el tamaño baja al subir el budget): la garantía es un
        # budget verificado que cabe, no necesariamente el mínimo absoluto —
        # misma regla que ADR-0034.  En resume el régimen de error es
        # monótono (ronda post-implementación #171).
        def bumpy(limit: int):
            return None, 13000 if 10000 <= limit < 12000 else 12000

        found = _minimum_budget(bumpy, 1)
        self.assertLessEqual(bumpy(found)[1], found)

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
            env = {"PATH": os.environ["PATH"], "AN_KLA_NO_UPDATE_CHECK": "1",
                   "PYTHONPATH": str(ROOT)}
            for argv0, expected in (("/opt/bin/an-kla", "console_script"),
                                    ("embedder", "embedded")):
                with self.subTest(argv0=argv0):
                    code = ("import sys; sys.argv=[%r,'--project-root',%r,'status'];"
                            "from an_kla.__main__ import main; main()" % (argv0, temp))
                    out = subprocess.run([sys.executable, "-c", code],
                                         capture_output=True, text=True, env=env)
                    self.assertEqual(out.returncode, 0, out.stderr)
                    self.assertEqual(
                        json.loads(out.stdout)["runtime"]["entrypoint"], expected)


if __name__ == "__main__":
    unittest.main()
