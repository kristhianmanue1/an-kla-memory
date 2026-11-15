"""Resumen de la matriz de cortes: ``python -m spikes.e1a_recovery.summarize <dir>``."""
import json, sys
from collections import Counter, defaultdict
from pathlib import Path

rows = []
for f in sorted(Path(sys.argv[1]).glob("cuts-*.json")):
    rows += json.loads(f.read_text())
agg = defaultdict(list)
for r in rows:
    agg[(r["config"], r["point"])].append(r)
print("config | punto | n | matados | perdidos(acked) | duplicados | verify!ok | journal abierto con candidato CURRENT | committed sin recibo current | marcadores | pending | tmp | huérfanos tmp antes | atascado(3.º drain != idle)")
for (cfg, pt), rs in agg.items():
    print(" | ".join(map(str, [
        cfg, pt, len(rs), sum(r["killed"] for r in rs),
        sum(len(r["lost"]) for r in rs), sum(r["duplicates"] for r in rs),
        sum(not r["verify_ok"] for r in rs),
        sum(r["journals_open_but_committed"] for r in rs),
        sum(r["committed_without_current_receipt"] for r in rs),
        sum(r["markers"] for r in rs), sum(r["pending"] for r in rs), sum(r["tmp"] for r in rs),
        sum(r["before_second_drain"]["tmp"] for r in rs),
        sum(r["third_state"] not in ("idle",) for r in rs),
    ])))
