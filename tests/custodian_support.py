"""Support for the ``memoria/ancla/v2`` tests (ADR-0071): the pinned vectors and a custodian that is a real process."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from an_kla.custodian_adapter import Adapters

FIXTURES = Path(__file__).parent / "fixtures" / "anchors-c3-v2"
FAKE = Path(__file__).parent / "fixtures" / "custodian_adapter_fake.py"
PINNED = {  # the sha256 of the frozen contract's files (README + errata 1 to 4)
    "vectores.json": "11917a3fa91acd40cbb89bf44b4e01c6a4e2c4b52fa43ac80a771918501588c5",
    "vectores-errata-1.json": "0841347035cbbd714498a8dc14de3e3b8278de5a779a9986df8fbae275560d46",
    "vectores-errata-2.json": "3cde0a009a113d7e129544ba2366b007e87397637f6c13558c72fa1ca5fabd67",
}
NOT_EXIGIBLE = {"X14"}  # replaced by E11 (erratum 2)


def load_vectors(name: str) -> list[dict[str, Any]]:
    raw = (FIXTURES / name).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != PINNED[name]:
        raise AssertionError(f"{name}: sha256 {digest} is not the one the contract froze")
    return json.loads(raw)["document"]


def exigible_cases() -> list[dict[str, Any]]:
    """The 61 cases: the 49 frozen ones, the 10 of erratum 1 and the 3 of erratum 2, without X14."""
    cases = [case for name in PINNED for case in load_vectors(name)]
    return [case for case in cases if case["id"] not in NOT_EXIGIBLE]


class FakeCustodian:
    """A table entry that runs ``custodian_adapter_fake.py`` with a scenario; ``log()`` says what the process saw."""

    def __init__(self, testcase: unittest.TestCase, name: str = "skopos") -> None:
        scratch = tempfile.TemporaryDirectory(prefix="custodio-")
        testcase.addCleanup(scratch.cleanup)
        self.dir, self.name = Path(scratch.name), name
        self._count = 0

    def table(self, scenario: dict[str, Any]) -> dict[str, tuple[str, ...]]:
        self._count += 1
        path = self.dir / f"escenario-{self._count}.json"
        path.write_text(json.dumps(scenario), encoding="utf-8")
        (self.dir / "llamada.json").unlink(missing_ok=True)
        return {self.name: (sys.executable, "-B", str(FAKE), "--scenario", str(path), "--log", str(self.dir / "llamada.json"))}

    def adapters(self, scenario: dict[str, Any] | None, timeout: float = 10.0) -> Adapters:
        return Adapters(self.table(scenario) if scenario else {}, None, timeout)

    def install(self, store_root: Any, scenario: dict[str, Any]) -> None:
        """The custodian in the store's ``config.json`` (``custodians``), with a scenario file that ``set`` can rewrite."""
        self.scenario_path = self.dir / "escenario.json"
        self.scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
        argv = [sys.executable, "-B", str(FAKE), "--scenario", str(self.scenario_path), "--log", str(self.dir / "llamada.json")]
        Path(store_root, "config.json").write_text(json.dumps({"custodians": {self.name: {"argv": argv}}}), encoding="utf-8")

    def set(self, scenario: dict[str, Any]) -> None:
        self.scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
        (self.dir / "llamada.json").unlink(missing_ok=True)

    def log(self) -> dict[str, Any] | None:
        path = self.dir / "llamada.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def called(self) -> bool:
        return self.log() is not None
