"""Resumen de las configuraciones F/G (N-02): ``python -m spikes.e1a_recovery.summarize_n02 <cuts.json>...``."""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict


def main() -> None:
    for path in sys.argv[1:]:
        rows = json.loads(open(path).read())
        by_point: dict[str, list] = defaultdict(list)
        for r in rows:
            by_point[r["point"]].append(r)
        print(f"== {path}")
        print("punto | n | muertos | perdidos | dupl. | verify≠ok | drain_error 2.º | estados finales del paso 0 | "
              "avisos | marcadores/pending tras 3.ª | 3.ª")
        for point, rs in by_point.items():
            finals: Counter = Counter()
            errors: Counter = Counter()
            warnings = 0
            for r in rs:
                second = r["second"]
                for c in second.get("closed", []) or []:
                    f = c.get("final")
                    if f:
                        finals[f"{f['state']}/{f['durability_state']}/{f['audit_state']}"] += 1
                if second.get("drain_error"):
                    errors[second["drain_error"]] += 1
                warnings += len(second.get("warnings", []) or [])
            print(" | ".join(str(x) for x in (
                point, len(rs), sum(r["killed"] for r in rs), sum(len(r["lost"]) for r in rs),
                sum(r["duplicates"] for r in rs), sum(not r["verify_ok"] for r in rs),
                dict(errors) or 0, dict(finals) or "-", warnings,
                f"{sum(r['markers'] for r in rs)}/{sum(r['pending'] for r in rs)}",
                dict(Counter(r["third_state"] for r in rs)))))


if __name__ == "__main__":
    main()
