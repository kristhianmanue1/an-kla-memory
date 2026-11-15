"""Procesos hijo del spike: ``python -m spikes.e1a_recovery.worker <orden> ...``."""

from __future__ import annotations

import json
import sys
import time

from an_kla.store import MemoryStore

from . import inbox as ib


def main(argv: list[str]) -> int:
    cmd, project = argv[0], argv[1]
    store = MemoryStore(project)
    if cmd == "enqueue":  # <project> <prefijo> <n> <salida.jsonl> [modo]
        prefix, n, out = argv[2], int(argv[3]), argv[4]
        mode = argv[5] if len(argv) > 5 else "replace"
        with open(out, "a", buffering=1) as fh:
            for i in range(n):
                text = f"{prefix}-{i}"
                r = ib.enqueue(store, text, publish_mode=mode)
                fh.write(json.dumps({"text": text, **r}) + "\n")
        return 0
    if cmd == "enqueue1":  # <project> <texto>
        r = ib.enqueue(store, argv[2])
        print(json.dumps(r))
        return 0
    if cmd == "drain":  # <project> [close_mode none_mode]
        close_mode = argv[2] if len(argv) > 2 else "write"
        none_mode = argv[3] if len(argv) > 3 else "smart"
        r = ib.drain_once(store, close_mode=close_mode, none_mode=none_mode, lock_deadline=2.0)
        print(json.dumps(r, default=str))
        return 0
    if cmd == "drain_loop":  # <project> <salida.jsonl> <stop-file>
        out, stop = argv[2], argv[3]
        import os
        with open(out, "a", buffering=1) as fh:
            while not os.path.exists(stop):
                r = ib.drain_once(store, lock_deadline=0.0)
                fh.write(json.dumps({"t": time.time(), **r}, default=str) + "\n")
                if r.get("state") in ("idle", "queued"):
                    time.sleep(0.01)
        return 0
    raise SystemExit(f"orden desconocida: {cmd}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
