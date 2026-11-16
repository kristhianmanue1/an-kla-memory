"""Apoyo de las pruebas de ``remember`` de extremo a extremo: la orden real en un subproceso del CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from tests.inbox_support import AGENT_ENV, GIT_ENV

ROOT = Path(__file__).resolve().parents[1]


def cli_env(extra: dict[str, str | None] | None = None, *, agent: bool = True) -> dict[str, str]:
    """Entorno de un lanzador: sin ninguna ``AN_KLA_*`` del desarrollador; ``None`` en ``extra`` borra la variable."""

    env = {k: v for k, v in os.environ.items() if not k.startswith("AN_KLA_")}
    env.update(GIT_ENV)
    env.update({"AN_KLA_NO_UPDATE_CHECK": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    if agent:
        env.update(AGENT_ENV)
    for key, value in (extra or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def cli(
    project: Path, *args: str, env: dict[str, str | None] | None = None, stdin: str | None = None,
    store_root: Path | None = None, agent: bool = True, timeout: float = 180,
) -> subprocess.CompletedProcess:
    """``python -m an_kla --project-root <p> [--store-root <r>] <args>``; stdout y stderr como texto."""

    command = [sys.executable, "-m", "an_kla", "--project-root", str(project)]
    if store_root is not None:
        command += ["--store-root", str(store_root)]
    return subprocess.run(
        [*command, *args], cwd=ROOT, input=stdin, capture_output=True, text=True, timeout=timeout,
        env=cli_env(env, agent=agent),
    )


def remember(project: Path, text: str, *args: str, **options: Any) -> tuple[int, dict]:
    """``remember --text-file -`` (la forma recomendada): ``(rc, resultado JSON)``."""

    done = cli(project, "remember", "--text-file", "-", *args, stdin=text, **options)
    try:
        return done.returncode, json.loads(done.stdout)
    except ValueError:
        raise AssertionError(f"salida no JSON (rc={done.returncode}): {done.stdout[-300:]!r} {done.stderr[-300:]!r}") from None
