"""run_guarded.py <argv…> — corre una orden en su propia sesión con el vigilante de carga (ADR-0074 §2).

Sale con el rc de la orden; con 75 si el vigilante la abortó por carga (imprime las muestras y lo que se mató); con 70 si la orden salió
bien pero dejó procesos vivos de su corrida (``children_left``: se matan y se listan).

El umbral es ``AN_KLA_CI_LOAD_ABORT`` (por defecto 30). Todo guion o prueba dirigida que pueda cargar la máquina se corre así.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from load_guard import EXIT_ABORTED, run_guarded  # noqa: E402

EXIT_CHILDREN_LEFT = 70


def report(outcome) -> None:
    if outcome.aborted:
        print(f"run_guarded: abortada por carga (umbral {outcome.reason.get('threshold')}); muestras: {outcome.reason.get('samples')}", file=sys.stderr)
        print(f"run_guarded: matados: {outcome.reason.get('killed')}", file=sys.stderr)
    if outcome.left:
        print(f"run_guarded: children_left: {[{'pid': p, 'command': n} for p, n in outcome.left]}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--"]:
        argv = argv[1:]
    if not argv:
        print("uso: run_guarded.py <orden> [args…]", file=sys.stderr)
        return 2
    outcome = run_guarded(argv)
    report(outcome)
    if outcome.aborted:
        return EXIT_ABORTED
    if outcome.rc == 0 and outcome.left:
        return EXIT_CHILDREN_LEFT
    return outcome.rc


if __name__ == "__main__":
    sys.exit(main())
