"""Procesos del criterio 2 (concurrencia): ``python -m tests.inbox_conc_worker <orden> ...``.

``enqueue <proyecto> <prefijo> <n> <salida.jsonl>`` encola ``n`` textos únicos y registra cada
resultado con su latencia; ``drain_loop <proyecto> <salida.jsonl> <archivo-stop> [plazo]`` vacía en bucle
con plazo 0 hasta que existe el archivo de parada, o vence su plazo propio (900 s por defecto: rc 3), o desaparece el proyecto (rc 4), una línea de resumen por llamada.
"""

from __future__ import annotations

import json
import os
import sys
import time

from an_kla import inbox, inbox_drain
from an_kla.store import MemoryStore


def main(argv: list[str]) -> int:
    command, project = argv[0], argv[1]
    store = MemoryStore(project)
    if command == "enqueue":
        prefix, count, out = argv[2], int(argv[3]), argv[4]
        with open(out, "a", buffering=1) as handle:
            for index in range(count):
                text = f"{prefix}-{index}"
                started = time.perf_counter()
                try:
                    result = inbox.enqueue(store, text)
                    row = {"text": text, "state": result["state"], "entry": result["entry"]}
                except Exception as exc:  # noqa: BLE001 - se registra, el test cuenta los errores
                    row = {"text": text, "state": "error", "code": str(exc)}
                row["elapsed"] = time.perf_counter() - started
                handle.write(json.dumps(row) + "\n")
        return 0
    if command == "drain_loop":
        out, stop = argv[2], argv[3]
        deadline = time.monotonic() + (float(argv[4]) if len(argv) > 4 else 900.0)
        with open(out, "a", buffering=1) as handle:
            while not os.path.exists(stop):
                if not os.path.isdir(argv[1]):
                    return 4
                if time.monotonic() > deadline:
                    return 3
                result = inbox_drain.drain(store, lock_wait_seconds=0.0)
                handle.write(json.dumps({
                    "state": result["state"], "drain_error": result.get("drain_error"),
                    "committed": result["committed"]["count"], "rejected": result["rejected"]["count"],
                    "queued": result["queued"], "batches": len(result["batches"]),
                    "max_lock": result["metrics"]["max_write_lock_seconds"],
                }) + "\n")
                if result["state"] in ("drained", "queued") and not result["batches"]:
                    time.sleep(0.01)
        return 0
    raise SystemExit(f"orden desconocida: {command}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
