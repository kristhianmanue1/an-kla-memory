"""Proceso trabajador del arnés ``kill -9`` (criterio 3): ``python -m tests.inbox_crash_worker``.

``drain <proyecto> <punto|-> [plazo]`` vacía con el corte ``punto`` (``-`` = ninguno) que se
ejecuta como ``SIGKILL`` sobre este mismo proceso; ``enqueue <proyecto> <texto> [corte]`` encola y,
con ``corte``, muere tras el fsync del temporal y antes de publicar. Imprime el resultado JSON si
sobrevive. Los cortes los instala ``tests.inbox_cuts`` aquí; ``an_kla`` no sabe de ellos.
"""

from __future__ import annotations

import json
import os
import signal
import sys

from an_kla import inbox, inbox_drain
from an_kla.canonical import canonical_json
from an_kla.store import MemoryStore
from tests import inbox_cuts


def die() -> None:
    os.kill(os.getpid(), signal.SIGKILL)


def main(argv: list[str]) -> int:
    command, project = argv[0], argv[1]
    store = MemoryStore(project)
    if command == "enqueue":
        replace = inbox_cuts.enqueue_replace(die) if len(argv) > 3 else os.replace
        result = inbox.enqueue(store, argv[2], replace=replace)
        sys.stdout.buffer.write(canonical_json(result))
        return 0
    if command == "drain":
        point = argv[2]
        wait = float(argv[3]) if len(argv) > 3 else 5.0
        if point == "-":
            result = inbox_drain.drain(store, lock_wait_seconds=wait)
        else:
            with inbox_cuts.install(store, point, die):
                result = inbox_drain.drain(store, lock_wait_seconds=wait)
        sys.stdout.write(json.dumps(result, default=str))
        return 0
    raise SystemExit(f"orden desconocida: {command}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
