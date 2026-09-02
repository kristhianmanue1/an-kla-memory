from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CiMetadataTests(unittest.TestCase):
    def test_no_remote_ci_workflows_local_only_policy(self) -> None:
        """beta.20 (decisión del operador, issue #102 §3.8): el repo no
        define workflows remotos; la verificación canónica es local
        (``scripts/ci_local.py --simulate-ci`` + gates de tamaños y
        registro). Si se reintroduce un workflow, este test obliga a
        re-congelar el pineo de acciones a commits revisados (la versión
        anterior de este test congelaba ``actions/checkout`` y
        ``actions/setup-python`` pineados en ``test.yml``).
        """

        workflows = ROOT / ".github" / "workflows"
        self.assertFalse(
            workflows.exists() and any(workflows.iterdir()),
            "workflows remotos retirados en beta.20; si se reintroducen, "
            "re-establece el pineo a commit revisado (test_ci_metadata)",
        )


if __name__ == "__main__":
    unittest.main()
