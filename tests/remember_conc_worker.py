"""Proceso del criterio 2 con la orden real: ``python -m tests.remember_conc_worker <proyecto> <prefijo> <n> <salida.jsonl>``.

Lanza ``n`` invocaciones SUCESIVAS de ``python -m an_kla remember --text-file -`` (cada una, un proceso
nuevo) con texto único y registra el resultado y la latencia de cada una; y ``drain_loop`` vacía en bucle
con ``inbox drain`` hasta que existe el archivo de parada.
"""

from __future__ import annotations

import json
import os
import sys
import time

from tests.remember_support import cli


def main(argv: list[str]) -> int:
    if argv[0] == "drain_loop":
        project, out, stop = argv[1], argv[2], argv[3]
        with open(out, "a", buffering=1) as handle:
            while not os.path.exists(stop):
                done = cli(project, "inbox", "drain")
                try:
                    result = json.loads(done.stdout)
                    row = {"state": result["state"], "drain_error": result.get("drain_error"),
                           "batches": len(result["batches"]), "rc": done.returncode}
                except ValueError:
                    row = {"state": "error", "stderr": done.stderr[-200:], "rc": done.returncode}
                handle.write(json.dumps(row) + "\n")
                time.sleep(0.01)
        return 0
    project, prefix, count, out = argv[0], argv[1], int(argv[2]), argv[3]
    with open(out, "a", buffering=1) as handle:
        for index in range(count):
            text = f"{prefix}-{index}"
            started = time.perf_counter()
            done = cli(project, "remember", "--text-file", "-", stdin=text)
            elapsed = time.perf_counter() - started
            try:
                result = json.loads(done.stdout)
                row = {"text": text, "state": result["state"], "drain_error": result.get("drain_error"),
                       "code": result.get("code"), "rc": done.returncode}
            except ValueError:
                row = {"text": text, "state": "error", "code": done.stderr[-200:], "rc": done.returncode}
            row["elapsed"] = elapsed
            handle.write(json.dumps(row) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
