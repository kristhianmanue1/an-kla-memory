"""ci_local.py — replica local de .github/workflows/test.yml.

Ejecuta los mismos pasos que el CI remoto (importabilidad + unittest +
check_sizes + registro ADR) sin gastar minutos de GitHub Actions. Portable a
los 3 SO de la matriz del workflow. Determinista: sin red, sin reloj real.

Bandera --simulate-ci: exporta GITHUB_ACTIONS=true y CI=true antes de los tests
para reproducir el entorno del runner y atrapar tests no deterministas (categoría
del bug fixeado en PR #25).

Complementa, no reemplaza, el CI remoto: éste valida 3 SO x 2 Python reales,
cosa que el CI local no hace.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
CHECK_SIZES = ROOT / "scripts" / "check_sizes.py"
CHECK_ADRS = ROOT / "scripts" / "check_adr_registry.py"


def paso_import() -> str:
    print("==> [1/4] importabilidad de an_kla", flush=True)
    try:
        result = subprocess.run(
            [PYTHON, "-c", "import an_kla"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        print(f"    FAIL: no se pudo invocar el interprete: {exc}")
        return "FAIL"
    if result.returncode != 0:
        print("    FAIL: an_kla no es importable por este interprete.")
        print("    Instala en modo desarrollo:  pip install -e .")
        if result.stderr.strip():
            print("    stderr:", result.stderr.strip())
        return "FAIL"
    print("    OK")
    return "OK"


def paso_tests(simulate_ci: bool) -> str:
    etiqueta = " (simulate-ci)" if simulate_ci else ""
    print(f"==> [2/4] unittest discover{etiqueta}", flush=True)
    env = dict(os.environ)
    if simulate_ci:
        env["GITHUB_ACTIONS"] = "true"
        env["CI"] = "true"
    result = subprocess.run(
        [PYTHON, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
        cwd=ROOT,
        env=env,
    )
    estado = "OK" if result.returncode == 0 else "FAIL"
    print(f"    {estado}")
    return estado


def paso_sizes() -> str:
    print("==> [3/4] check_sizes", flush=True)
    if not CHECK_SIZES.exists():
        print("    SKIP: scripts/check_sizes.py no existe (ver issue #21 / PR #24)")
        return "SKIP"
    result = subprocess.run([PYTHON, str(CHECK_SIZES)], cwd=ROOT)
    estado = "OK" if result.returncode == 0 else "FAIL"
    print(f"    {estado}")
    return estado


def paso_adrs() -> str:
    print("==> [4/4] check_adr_registry", flush=True)
    result = subprocess.run([PYTHON, str(CHECK_ADRS)], cwd=ROOT)
    estado = "OK" if result.returncode == 0 else "FAIL"
    print(f"    {estado}")
    return estado


def main() -> int:
    parser = argparse.ArgumentParser(description="CI local portable.")
    parser.add_argument(
        "--simulate-ci",
        action="store_true",
        help="exporta GITHUB_ACTIONS=true y CI=true antes de los tests",
    )
    args = parser.parse_args()

    resultados = {
        "importabilidad": paso_import(),
        "unittest": paso_tests(args.simulate_ci),
        "check_sizes": paso_sizes(),
        "check_adr_registry": paso_adrs(),
    }

    print("\nResumen:")
    for nombre, estado in resultados.items():
        print(f"  {nombre}: {estado}")

    fallos = [n for n, e in resultados.items() if e == "FAIL"]
    if not fallos:
        print("\nci_local: OK")
        return 0
    print(f"\nci_local: FAIL — pasos fallidos: {', '.join(fallos)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
