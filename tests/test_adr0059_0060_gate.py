"""test_adr0059_0060_gate.py — gate del escritor acotado y planificación coherente.

ADR-0059: toda espera de escritor sobre el reader gate (`plan_write`,
`writer_gate`) vence con `LockBusyError("writer_gate_busy")` a la constante
única `WRITE_LOCK_DEADLINE_SECONDS`; los lectores siguen bloqueando.
ADR-0060: los pares `read_current`+`snapshot` de planificación son
coherentes bajo una sola adquisición del gate (el EX de una compactación
simulada no puede entrar a medio par).
"""

from __future__ import annotations

import threading
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from an_kla.canonical import digest_json
from an_kla.reader_gate import (
    ReaderGateError,
    exclusive_reader_gate,
    reader_gate_mode,
)
from an_kla.store import LockBusyError, MemoryStore

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "agent-integration" / "ankla_agent.py"


def _proposal_authority(store: MemoryStore, record_id: str = "f-gate"):
    expected = store.read_current()
    proposal = {
        "schema": "an-kla/write-proposal-v1",
        "base_revision": expected,
        "stream": "facts",
        "operation": "add",
        "requested_representation": "summary",
        "record": {"id": record_id, "payload": {"text": "texto gate"}},
        "lineage": {"derived_from_retrieval": False, "refs": []},
    }
    authority = {
        "schema": "an-kla/write-authority-v1",
        "proposal_sha256": digest_json(proposal),
        "base_revision": expected,
        "authority_class": "model_derived",
        "issuer": {
            "kind": "model",
            "id": "test",
            "configuration_fingerprint": "sha256:" + "0" * 64,
        },
        "evidence": [],
        "scope": {
            "streams": ["facts"],
            "representations": ["summary"],
            "operations": ["add"],
        },
    }
    return proposal, authority, expected


class _ExclusiveHolder:
    """Sostiene LOCK_EX en un hilo propio hasta `release()`."""

    def __init__(self, store: MemoryStore) -> None:
        self.store = store
        self.acquired = threading.Event()
        self.release = threading.Event()
        self.error: list[Exception] = []
        self.thread = threading.Thread(target=self._hold, daemon=True)

    def _hold(self) -> None:
        try:
            with exclusive_reader_gate(self.store):
                self.acquired.set()
                self.release.wait(10)
        except Exception as exc:  # pragma: no cover - diagnóstico
            # Sólo se marca adquirido tras un EX real; un fallo aquí debe
            # verse en __enter__, no como exclusión fingida.
            self.error.append(exc)

    def __enter__(self) -> "_ExclusiveHolder":
        self.thread.start()
        if not self.acquired.wait(5):
            raise AssertionError(f"EX no adquirida: {self.error}")
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.release.set()
        self.thread.join(5)


class WriterGateBoundedTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="ankla-adr59-")
        self.addCleanup(self._tmp.cleanup)
        self.store = MemoryStore(Path(self._tmp.name))
        self.store.initialize()

    def test_plan_write_vences_writer_gate_busy_bajo_exclusion(self) -> None:
        proposal, authority, _ = _proposal_authority(self.store)
        with _ExclusiveHolder(self.store):
            with mock.patch(
                "an_kla.reader_gate.WRITE_LOCK_DEADLINE_SECONDS", 0.15
            ):
                start = time.monotonic()
                with self.assertRaises(LockBusyError) as caught:
                    self.store.plan_write(proposal, authority)
                elapsed = time.monotonic() - start
        self.assertIn("writer_gate_busy", str(caught.exception))
        self.assertGreaterEqual(elapsed, 0.1)

    def test_writer_gate_primitive_vence_igual(self) -> None:
        # El primitivo que usan plan_write y plan_refute (ADR-0059).
        with _ExclusiveHolder(self.store):
            with mock.patch(
                "an_kla.reader_gate.WRITE_LOCK_DEADLINE_SECONDS", 0.15
            ):
                with self.assertRaises(LockBusyError) as caught:
                    with self.store.writer_gate():
                        pass
        self.assertIn("writer_gate_busy", str(caught.exception))

    def test_lector_sigue_bloqueando_y_exito_al_liberar(self) -> None:
        verified: dict[str, object] = {}
        errors: list[Exception] = []

        def reader() -> None:
            try:
                verified["ok"] = self.store.verify()["ok"]
            except Exception as exc:  # pragma: no cover - diagnóstico
                errors.append(exc)

        with _ExclusiveHolder(self.store):
            reader_thread = threading.Thread(target=reader, daemon=True)
            reader_thread.start()
            time.sleep(0.3)
            self.assertTrue(reader_thread.is_alive())  # bloqueado, no fallado
            self.assertEqual(errors, [])
        reader_thread.join(5)
        self.assertFalse(reader_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(verified.get("ok"))


class PlanificationCoherentTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="ankla-adr60-")
        self.addCleanup(self._tmp.cleanup)
        self.store = MemoryStore(Path(self._tmp.name))
        self.store.initialize()

    def test_exclusion_no_entra_durante_el_par_de_plan_write(self) -> None:
        import an_kla.store as store_module

        proposal, authority, _ = _proposal_authority(self.store)
        original = store_module.guard_plan_against_snapshot
        probe: dict[str, str | None] = {"mode": None}

        def slow_guard(records, checked_proposal) -> None:
            probe["mode"] = reader_gate_mode(self.store)
            time.sleep(0.4)
            original(records, checked_proposal)

        ex_outcome: list[str] = []

        def ex_attempt() -> None:
            time.sleep(0.1)  # entra cuando la planificación ya sostiene SH
            try:
                with exclusive_reader_gate(self.store, timeout=0.2):
                    ex_outcome.append("obtained")
            except ReaderGateError as exc:
                ex_outcome.append(str(exc))

        ex_thread = threading.Thread(target=ex_attempt, daemon=True)
        with mock.patch.object(
            store_module, "guard_plan_against_snapshot", slow_guard
        ):
            ex_thread.start()
            plan = self.store.plan_write(proposal, authority)
            ex_thread.join(5)
        self.assertEqual(probe["mode"], "shared")
        self.assertEqual(len(ex_outcome), 1)
        self.assertIn("compaction_readers_active", ex_outcome[0])
        self.assertEqual(plan["current_revision"], self.store.read_current())
        # Liberado el par, la exclusión sí es obtenible.
        with exclusive_reader_gate(self.store, timeout=1.0):
            pass

    def test_plan_refute_usa_el_gate_del_escritor(self) -> None:
        import an_kla.refutations as refutations_module

        source = Path(refutations_module.__file__).read_text()
        self.assertIn("store.writer_gate()", source)

    def test_evaluation_bajo_exclusion_bloquea_y_luego_exito(self) -> None:
        from an_kla.evaluation_strategies import OVERLAP, evaluate_strategy

        expected = self.store.read_current()
        self.store.commit(
            expected_current_hash=expected,
            checkpoint_patch={},
            facts=[{"id": "f-q", "payload": {"text": "aguja unica needle"}}],
        )
        result: dict[str, object] = {}
        errors: list[Exception] = []

        def evaluator() -> None:
            try:
                result["report"] = evaluate_strategy(
                    self.store,
                    [{
                        "schema": "an-kla/retrieval-eval-query-v2",
                        "id": "q-gate",
                        "category": "synthetic",
                        "query": "needle",
                        "relevant": ["f-q"],
                        "streams": ["facts"],
                    }],
                    [1000],
                    [5],
                    OVERLAP,
                )
            except Exception as exc:  # pragma: no cover - diagnóstico
                errors.append(exc)

        with _ExclusiveHolder(self.store):
            eval_thread = threading.Thread(target=evaluator, daemon=True)
            eval_thread.start()
            time.sleep(0.3)
            self.assertEqual(errors, [])  # murió por validación, no por el gate
            self.assertTrue(eval_thread.is_alive())  # bloqueado, no fallado
        eval_thread.join(5)
        self.assertFalse(eval_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertIsNotNone(result.get("report"))


class DeclarationDriftTests(unittest.TestCase):
    """El código nuevo debe estar declarado donde lo consume la casa."""

    def test_agent_example_retries_writer_gate_busy(self) -> None:
        source = EXAMPLE.read_text()
        self.assertIn('"writer_gate_busy"', source)

    def test_capabilities_declare_lock_error_codes(self) -> None:
        from an_kla.capabilities import capabilities

        codes = capabilities()["write_policy"]["lock_error_codes"]
        self.assertIn("write_lock_busy", codes)
        self.assertIn("writer_gate_busy", codes)

    def test_single_deadline_constant_source(self) -> None:
        from an_kla.reader_gate import WRITE_LOCK_DEADLINE_SECONDS
        from an_kla.store_locks import (
            WRITE_LOCK_DEADLINE_SECONDS as CANONICAL,
        )

        self.assertEqual(WRITE_LOCK_DEADLINE_SECONDS, CANONICAL)
        self.assertEqual(CANONICAL, 10.0)


if __name__ == "__main__":
    unittest.main()
