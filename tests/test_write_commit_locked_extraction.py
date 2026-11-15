"""Neutralidad de la extracción de ``_commit_write_plan_locked`` (ADR-0063).

Los goldens de ``tests/fixtures/write-commit-goldens/`` se generaron con el
código previo a la extracción; aquí se recalculan y se exige igualdad byte a
byte (resultado o error, y árbol del store).
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from an_kla.identity import _mutation_preflight_with_context
from an_kla.store import MemoryStore
from an_kla.write_commit import _commit_write_plan_locked, _finish_locked_commit
from tests import write_commit_scenarios as scenarios

GOLDENS = Path(__file__).parent / "fixtures" / "write-commit-goldens"


class WriteCommitGoldenTests(unittest.TestCase):
    def test_every_scenario_has_a_golden_and_vice_versa(self) -> None:
        on_disk = {path.stem for path in GOLDENS.glob("*.json")}
        self.assertEqual(on_disk, set(scenarios.SCENARIOS))

    def test_scenarios_match_goldens_byte_for_byte(self) -> None:
        for name in scenarios.SCENARIOS:
            with self.subTest(scenario=name), tempfile.TemporaryDirectory() as temp:
                actual = scenarios.canonical_bytes(
                    scenarios.run_scenario(name, Path(temp))
                )
                self.assertEqual(actual, (GOLDENS / f"{name}.json").read_bytes())


def _commit_by_hand(store, **kwargs):
    """Lo que haría un llamante futuro que toma el candado por su cuenta."""

    preflight = _mutation_preflight_with_context(store)
    store._make_layout()
    with store.write_lock() as lock_result:
        locked = _commit_write_plan_locked(
            store, lock_result, preflight=preflight, **kwargs
        )
    return _finish_locked_commit(store, lock_result, locked)


class LockedBodyTests(unittest.TestCase):
    def test_locked_body_with_held_lock_matches_goldens_and_never_blocks(self) -> None:
        # Si el cuerpo intentara tomar el candado (no reentrante), el flock de
        # otro descriptor del mismo proceso agotaría el plazo y levantaría
        # LockBusyError, que ``run_scenario`` no captura.
        with patch("an_kla.store._commit_write_plan_flow", _commit_by_hand):
            for name in scenarios.SCENARIOS:
                with self.subTest(scenario=name), tempfile.TemporaryDirectory() as temp:
                    actual = scenarios.canonical_bytes(
                        scenarios.run_scenario(name, Path(temp))
                    )
                    expected = (GOLDENS / f"{name}.json").read_bytes()
                    self.assertEqual(actual, expected)

    def test_locked_body_returns_revision_and_outcome_on_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch(
            "an_kla.store._commit_write_plan_flow", _commit_by_hand
        ):
            store = MemoryStore(temp)
            root = store.initialize()
            candidate = scenarios.proposal_v1(root, "f-forma")
            auth = scenarios.authority_for(candidate)
            planning = store.plan_write(candidate, auth)
            preflight = _mutation_preflight_with_context(store)
            with store.write_lock() as lock_result:
                locked = _commit_write_plan_locked(
                    store,
                    lock_result,
                    expected_current_hash=root,
                    plan=planning["plan"],
                    proposal=candidate,
                    authority=auth,
                    decision=planning["decision"],
                    preflight=preflight,
                )
            self.assertIsNone(locked.final)
            self.assertEqual(locked.observed, root)
            self.assertTrue(locked.outcome["committed"])
            self.assertEqual(locked.revision, store.read_current())


if __name__ == "__main__":
    unittest.main()
