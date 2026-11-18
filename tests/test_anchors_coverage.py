"""C3 coverage vectors: 63 of fact-checks-rules/v1 and the 6 of ``cobertura``."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from an_kla.anchors_coverage import check_elements, coverage, coverage_from_elements

FIXTURES = Path(__file__).parent / "fixtures" / "anchors-c3"
PINNED = {
    "fact-checks-v1-vectors.json": "3ef67fa54dae313d0112cb7cf6ba10fc948d15cc42204323e68a91f4fdcc3bbc",
    "vectores.json": "948a11305fe2c6a8c1640538c6460efafd14bd6a89da43c8e69ee74d7e3032a9",
}


def _load(name: str) -> dict:
    raw = (FIXTURES / name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == PINNED[name], name
    return json.loads(raw)


class CoverageVectorsTest(unittest.TestCase):
    def test_fact_checks_vectors(self) -> None:
        cases = _load("fact-checks-v1-vectors.json")["cases"]
        self.assertEqual(len(cases), 63)
        for case in cases:
            with self.subTest(case["id"]):
                elements = check_elements(case["text"], case["quotes"])
                self.assertEqual(elements, case["elements"])
                missing = [{"type": e["type"], "value": e["value"]}
                           for e in elements if not e["present"]]
                self.assertEqual(
                    sorted(missing, key=lambda m: ["identifier", "path", "version", "number"].index(m["type"])),
                    sorted(case["missing"], key=lambda m: ["identifier", "path", "version", "number"].index(m["type"])),
                )

    def test_cobertura_vectors(self) -> None:
        cases = _load("vectores.json")["cobertura"]
        self.assertEqual(len(cases), 6)
        for case in cases:
            with self.subTest(case["id"]):
                self.assertEqual(coverage_from_elements(case["elements"]), case["expect"])

    def test_port_example(self) -> None:
        out = coverage("el servidor usa el puerto 8080", ["el servidor usa el puerto 8081"])
        self.assertEqual(out["coverage"]["level"], "none")
        self.assertEqual(out["missing"], [{"type": "number", "value": "8080"}])


if __name__ == "__main__":
    unittest.main()
