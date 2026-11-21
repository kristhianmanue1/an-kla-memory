"""ci_local.py — gate local vigente; no hay workflow remoto de PR.

Ejecuta importabilidad + unittest + la matriz `kill -9` de la bandeja (lenta, con
AN_KLA_SLOW_KILL9=1; ADR-0063 criterio 3) +
check_sizes + check_plans + registro ADR sin consumir GitHub Actions.
La simulación local no acredita ejecución en otros sistemas operativos.

Bandera --simulate-ci: exporta GITHUB_ACTIONS=true y CI=true antes de los tests
para reproducir el entorno del runner y atrapar tests no deterministas (categoría
del bug fixeado en PR #25).

Desde beta.22 añade dos pasos locales (issue #112 e issue #111/P5):
- el selftest G-3 de `redteam_consistent_rewrite.py` corre como gate
  automático (camino completo: guard + copia desechable + ataque +
  verificación post-ataque; ADR-0043 §Test de regresión). Requiere un
  store canónico local (`.an-kla/`): en clones frescos o worktrees sin
  store el paso declara SKIP honesto;
- la matriz de intérpretes soportados emite estado por versión y falla si
  una versión soportada disponible no pasa la suite. Coste: cada
  intérprete disponible distinto del principal corre la suite completa
  anidada (~45-90s por intérprete según skips criptográficos); un host
  con varios intérpretes en PATH puede tardar 10-15 min. Define
  AN_KLA_CI_LOCAL_MATRIX=0 para saltar la matriz (SKIP declarado).

ADR-0062 incorpora scripts/ci_audit.py como perfil optativo en verificación;
no sustituye este gate hasta aceptación explícita de la transición.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import load_guard  # noqa: E402  (ADR-0074: el freno por carga de cada paso pesado)

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
CHECK_SIZES = ROOT / "scripts" / "check_sizes.py"
CHECK_PLANS = ROOT / "scripts" / "check_plans.py"
CHECK_ADRS = ROOT / "scripts" / "check_adr_registry.py"
REDTEAM = ROOT / "scripts" / "redteam_consistent_rewrite.py"
KILL9_TEST = ROOT / "tests" / "test_inbox_crash.py"
SUPPORTED_VERSIONS = ("3.9", "3.12", "3.13")


ABORTED: list[dict] = []  # los motivos de los pasos que el vigilante abortó por carga: ``main`` sale con 75


def run_step(argv: list[str], *, cwd=ROOT, env=None, **guard) -> str:
    """Un paso pesado (ADR-0074 §2): en su propia sesión, con su vigilante, que muere con el paso. ``ci_local`` queda fuera de esa sesión.

    ``OK``, ``FAIL`` (rc distinto de 0 o ``children_left``: quedó algún proceso de la corrida y se mató) o ``ABORT`` (por carga)."""
    outcome = load_guard.run_guarded(argv, cwd=str(cwd), env=env, **guard)
    if outcome.aborted:
        ABORTED.append(outcome.reason)
        print(f"    ABORT: abortada por carga (umbral {outcome.reason.get('threshold')}); muestras: {outcome.reason.get('samples')}")
        print(f"    matados: {outcome.reason.get('killed')}")
        return "ABORT"
    if outcome.left:
        print(f"    FAIL: children_left: {[{'pid': p, 'command': n} for p, n in outcome.left]} (se mataron)")
        return "FAIL"
    return "OK" if outcome.rc == 0 else "FAIL"


def paso_import() -> str:
    print("==> [1/8] importabilidad de an_kla", flush=True)
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
    print(f"==> [2/8] unittest discover{etiqueta}", flush=True)
    env = dict(os.environ)
    if simulate_ci:
        env["GITHUB_ACTIONS"] = "true"
        env["CI"] = "true"
    estado = run_step([PYTHON, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"], env=env)
    print(f"    {estado}")
    return estado


def paso_redteam_selftest() -> str:
    print("==> [3/8] selftest G-3 (redteam_consistent_rewrite)", flush=True)
    if not REDTEAM.exists():
        print("    SKIP: scripts/redteam_consistent_rewrite.py no existe")
        return "SKIP"
    if not (ROOT / ".an-kla").exists():
        print(
            "    SKIP: no hay store canónico local (.an-kla/); el selftest "
            "copia el store del checkout (clone fresco o worktree sin memoria)"
        )
        return "SKIP"
    result = subprocess.run(
        [PYTHON, str(REDTEAM), "--selftest"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print("    OK")
        return "OK"
    print(f"    FAIL: exit {result.returncode} (esperado 0; 5 = frontera ADR-0043 cambiada)")
    if result.stderr.strip():
        print("    stderr:", result.stderr.strip())
    return "FAIL"


def _interprete_para(version: str) -> str | None:
    """Resuelve un intérprete para la versión, o None si no hay."""
    encontrado = shutil.which(f"python{version}")
    if encontrado:
        return encontrado
    mayor, menor = (int(parte) for parte in version.split("."))
    if sys.version_info[:2] == (mayor, menor):
        return sys.executable
    return None


def paso_matriz() -> str:
    print("==> [4/8] matriz de intérpretes soportados", flush=True)
    if os.environ.get("AN_KLA_CI_LOCAL_MATRIX") == "0":
        print("    SKIP (AN_KLA_CI_LOCAL_MATRIX=0)")
        return "SKIP"
    estados: dict[str, str] = {}
    for version in SUPPORTED_VERSIONS:
        interprete = _interprete_para(version)
        if interprete is None:
            estados[version] = "SKIP (intérprete no disponible en PATH)"
            continue
        if Path(interprete).resolve() == Path(PYTHON).resolve():
            estados[version] = (
                f"OK ({Path(interprete).name}: cubierto por el paso unittest)"
            )
            continue
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT)
        estado = run_step([interprete, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"], env=env)
        estados[version] = "OK" if estado == "OK" else f"{estado} ({Path(interprete).name})"
    for version, estado in estados.items():
        print(f"    python{version}: {estado}")
    if any(estado.startswith("FAIL") for estado in estados.values()):
        return "FAIL"
    return "OK"


def paso_kill9_bandeja() -> str:
    """Matriz ``kill -9`` real de la bandeja (ADR-0063, criterio 3): 8 puntos + último recurso × 20.

    Es lenta, así que no corre en el ``unittest discover`` normal (la prueba se salta sin
    ``AN_KLA_SLOW_KILL9=1``): este paso la ejecuta aparte, con esa variable. Define
    AN_KLA_CI_LOCAL_KILL9=0 para saltarlo (SKIP declarado); lo hace la prueba que corre
    ``ci_local`` anidado.
    """

    print("==> [5/8] kill -9 de la bandeja (criterio 3)", flush=True)
    if os.environ.get("AN_KLA_CI_LOCAL_KILL9") == "0":
        print("    SKIP (AN_KLA_CI_LOCAL_KILL9=0)")
        return "SKIP"
    if not KILL9_TEST.exists():
        print("    SKIP: tests/test_inbox_crash.py no existe")
        return "SKIP"
    env = dict(os.environ)
    env["AN_KLA_SLOW_KILL9"] = "1"
    estado = run_step([PYTHON, "-m", "unittest", "tests.test_inbox_crash.Kill9MatrixTests"], env=env)
    print(f"    {estado}")
    return estado


def paso_sizes() -> str:
    print("==> [6/8] check_sizes", flush=True)
    if not CHECK_SIZES.exists():
        print("    SKIP: scripts/check_sizes.py no existe (ver issue #21 / PR #24)")
        return "SKIP"
    result = subprocess.run([PYTHON, str(CHECK_SIZES)], cwd=ROOT)
    estado = "OK" if result.returncode == 0 else "FAIL"
    print(f"    {estado}")
    return estado


def paso_plans() -> str:
    print("==> [7/8] check_plans", flush=True)
    if not CHECK_PLANS.exists():
        print("    SKIP: scripts/check_plans.py no existe")
        return "SKIP"
    result = subprocess.run([PYTHON, str(CHECK_PLANS)], cwd=ROOT)
    estado = "OK" if result.returncode == 0 else "FAIL"
    print(f"    {estado}")
    return estado


def paso_adrs() -> str:
    print("==> [8/8] check_adr_registry", flush=True)
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
        "redteam_selftest": paso_redteam_selftest(),
        "matriz_interpretes": paso_matriz(),
        "kill9_bandeja": paso_kill9_bandeja(),
        "check_sizes": paso_sizes(),
        "check_plans": paso_plans(),
        "check_adr_registry": paso_adrs(),
    }

    print("\nResumen:")
    for nombre, estado in resultados.items():
        print(f"  {nombre}: {estado}")

    if ABORTED:
        print("\nci_local: ABORTADA POR CARGA (rc 75); no es un fallo de las pruebas")
        return load_guard.EXIT_ABORTED
    fallos = [n for n, e in resultados.items() if e == "FAIL"]
    if not fallos:
        print("\nci_local: OK")
        return 0
    print(f"\nci_local: FAIL — pasos fallidos: {', '.join(fallos)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
