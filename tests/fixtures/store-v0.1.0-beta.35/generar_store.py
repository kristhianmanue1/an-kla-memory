#!/usr/bin/env python3
"""Genera el store del fixture `store-v0.1.0-beta.35` con el código de `main`.

Uso: generar_store.py <directorio-proyecto-vacio>

Crea `<proyecto>/.an-kla/` con la CLI (init + plan-write + commit-write-plan),
con ids de transacción fijos y `verified_at` fijo. No es una prueba: se ejecuta
una vez, con el código de la beta.35, y su resultado se versiona. Los
`project_uuid` y las claves de atestación sí son aleatorios por ejecución, por
eso el store se versiona y no se regenera en cada corrida.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PYTHON = sys.executable
ENV = {**os.environ, "AN_KLA_NO_UPDATE_CHECK": "1", "PYTHONDONTWRITEBYTECODE": "1"}
LINEAGE = {"derived_from_retrieval": False, "refs": []}
TX = "00000000-0000-4000-8000-{:012d}"


def cli(project: Path, *args: str) -> str:
    done = subprocess.run(
        [PYTHON, "-m", "an_kla", "--project-root", str(project), *args],
        capture_output=True, text=True, env=ENV, check=True,
    )
    return done.stdout


def commit(project: Path, work: Path, n: int, rev: str, proposal: dict) -> str:
    """Escribe una propuesta por el camino gobernado y devuelve la revisión nueva."""
    proposal = {**proposal, "base_revision": rev}
    paths = {k: work / f"{k}-{n}.json" for k in ("proposal", "authority", "plan")}
    paths["proposal"].write_text(json.dumps(proposal))
    paths["authority"].write_text(cli(project, "plan-write", "--proposal", str(paths["proposal"]),
                                      "--emit-authority-template"))
    paths["plan"].write_text(cli(project, "plan-write", "--proposal", str(paths["proposal"]),
                                 "--authority", str(paths["authority"])))
    out = cli(project, "commit-write-plan", "--expected-current", rev,
              "--proposal", str(paths["proposal"]), "--authority", str(paths["authority"]),
              "--planning-result", str(paths["plan"]), "--transaction-id", TX.format(n))
    return json.loads(out)["revision"]


def main(argv: list[str]) -> int:
    project = Path(argv[1]).resolve()
    rev = json.loads(cli(project, "init", "--transaction-id", TX.format(1)))["revision"]
    steps = [
        {"stream": "facts", "operation": "add", "record": {
            "id": "f-golden-1", "text": "golden alpha decision on retrieval budget",
            "summary": "golden alpha", "verified_at": "2026-01-01T00:00:00Z"}},
        {"stream": "facts", "operation": "add", "record": {
            "id": "f-golden-2", "text": "golden beta fact about the write lock",
            "summary": "golden beta", "verified_at": "2026-01-02T00:00:00Z"}},
        {"stream": "events", "operation": "add", "record": {
            "id": "e-golden-1", "text": "golden event closed the alpha review",
            "summary": "golden event", "verified_at": "2026-01-03T00:00:00Z"}},
        {"stream": "episodes", "operation": "add", "record": {
            "id": "ep-golden-1", "text": "golden episode about the beta migration",
            "summary": "golden episode", "verified_at": "2026-01-04T00:00:00Z"}},
        {"stream": "facts", "operation": "supersede", "supersedes": "f-golden-2", "record": {
            "id": "f-golden-3", "text": "golden gamma fact replaces the beta one",
            "summary": "golden gamma", "verified_at": "2026-01-05T00:00:00Z"}},
    ]
    with tempfile.TemporaryDirectory(prefix="golden-gen-") as tmp:
        for n, step in enumerate(steps, start=2):
            proposal = {"schema": "an-kla/write-proposal-v1", "requested_representation": "summary",
                        "lineage": LINEAGE, **step}
            rev = commit(project, Path(tmp), n, rev, proposal)
    print(rev)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
