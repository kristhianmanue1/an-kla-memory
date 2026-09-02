#!/usr/bin/env python3
"""Gate estructural de planes de implementación (A-4 de PROP-004, ADR-014).

Comprueba estructura, no vocabulario: cada tarea con Consumes/Produce/Steps,
cada step con su criterio de verificación, cada ruta backtickada existente y
contenida en el repo. Las reglas E1-E5 y sus límites declarados viven en
docs/plans/2026-08-20-a4-gate-de-planes.md.

Los bloques TAREA se reconocen sólo dentro de fences ``` — la prosa que
mencione "TAREA ..." o checklists fuera de un fence no se parsea (ronda
adversarial 2026-08-20: un plan que transcriba salida del gate no debe
autobloquearse).

Fail-closed (ADR-006): sin clave `plans` en skevi-gate.json no comprueba
nada — inactivo, nunca error; clave presente con tipo inválido sí es error.
Codependencia declarada: consume la misma config que check_sizes.py y
espera encontrarlo al lado (claves compartidas); copiar sólo este script
con config mixta es un error de instalación.

Uso:
  python3 scripts/check_plans.py [--root DIR]   # planes de la config
  python3 scripts/check_plans.py FILE...        # archivos explícitos
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_NAME = "skevi-gate.json"
EXTENSIONES_CONOCIDAS = {
    ".css", ".glb", ".html", ".js", ".json", ".md", ".py", ".toml",
    ".ts", ".txt", ".yaml", ".yml",
}
TAREA_RE = re.compile(r"^\s*TAREA\s+\S+")
CHECKBOX_RE = re.compile(r"^\s*- \[[ xX]\]")
CAMPO_RE = {
    "Consumes:": re.compile(r"^\s*Consumes:", re.MULTILINE),
    "Produce:": re.compile(r"^\s*Produce:", re.MULTILINE),
    "Steps:": re.compile(r"^\s*Steps:", re.MULTILINE),
}
TOKEN_RE = re.compile(r"`([^`]+)`")
CREA_RE = re.compile(r"\bcrea\w*\b", re.IGNORECASE)


def _claves_validas() -> set[str]:
    """Las mismas de check_sizes.py más `plans`: una sola fuente de config.
    El fallback duplica el set por si check_sizes no está al lado."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from check_sizes import CONFIG_KEYS

        return set(CONFIG_KEYS) | {"plans"}
    except ImportError:
        return {
            "limits", "default_limit", "exempt_paths", "required",
            "skip_dirs", "root_markdown", "plans",
        }


def cargar_config(root: Path) -> dict:
    ruta = root / CONFIG_NAME
    if not ruta.is_file():
        return {}
    data = json.loads(ruta.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{CONFIG_NAME}: la raíz debe ser un objeto")
    desconocidas = sorted(set(data) - _claves_validas())
    if desconocidas:
        raise ValueError(
            f"{CONFIG_NAME}: claves desconocidas: {', '.join(desconocidas)}"
        )
    return data


def _spans_de_fence(lineas: list[str]) -> list[tuple[int, int]]:
    """Rangos [a, b) de líneas dentro de fences ```."""
    dentro = False
    inicio = None
    spans = []
    for i, ln in enumerate(lineas):
        if ln.strip().startswith("```"):
            dentro = not dentro
            if dentro:
                inicio = i + 1
            elif inicio is not None:
                spans.append((inicio, i))
                inicio = None
    return spans


def _bloques_tarea(texto: str) -> list[list[str]]:
    """Bloques TAREA, sólo dentro de fences; cada bloque termina en la
    próxima TAREA o al cerrar su fence — nunca cruza a la prosa."""
    lineas = texto.splitlines()
    bloques: list[list[str]] = []
    for a, b in _spans_de_fence(lineas):
        segmento = lineas[a:b]
        indices = [i for i, ln in enumerate(segmento) if TAREA_RE.match(ln)]
        for n, inicio in enumerate(indices):
            fin = indices[n + 1] if n + 1 < len(indices) else len(segmento)
            bloques.append(segmento[inicio:fin])
    return bloques


def _contenida(root: Path, ruta: Path) -> bool:
    try:
        (root / ruta).resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _rutas_rotas(linea: str, root: Path) -> list[str]:
    if CREA_RE.search(linea):  # creación declarada: puede no existir aún
        return []
    rotas = []
    for token in TOKEN_RE.findall(linea):
        if "/" not in token or "://" in token:
            continue  # sin ruta, o referencia externa (URL): fuera del ancla
        ruta = Path(token)
        if ruta.suffix.lower() not in EXTENSIONES_CONOCIDAS:
            continue
        if not _contenida(root, ruta):
            rotas.append(f"{token} (fuera del repo)")
        elif not (root / ruta).exists():
            rotas.append(token)
    return rotas


def _agrupar_steps(bloque: list[str]) -> list[str]:
    """Cada step = línea checkbox + sus líneas de continuación (más
    indentadas que el guion del checkbox, sin cruzar otro elemento)."""
    steps: list[str] = []
    actual: list[str] = []
    for ln in bloque[1:]:
        if CHECKBOX_RE.match(ln):
            if actual:
                steps.append("\n".join(actual))
            actual = [ln]
        elif actual:
            if TAREA_RE.match(ln):
                break
            indentacion = len(ln) - len(ln.lstrip())
            marcador = len(actual[0]) - len(actual[0].lstrip()) + 2
            if ln.strip() and indentacion >= marcador:
                actual.append(ln)
            else:
                steps.append("\n".join(actual))
                actual = []
        # líneas antes del primer checkbox: no son steps
    if actual:
        steps.append("\n".join(actual))
    return steps


def comprobar_plan(relativo: str, texto: str, root: Path) -> list[str]:
    fallos: list[str] = []
    bloques = _bloques_tarea(texto)
    if not bloques:
        return [f"{relativo}: sin bloques TAREA en fences (regla E1)"]

    for bloque in bloques:
        id_tarea = bloque[0].strip()
        cuerpo = "\n".join(bloque)
        for campo, patron in CAMPO_RE.items():
            if not patron.search(cuerpo):
                fallos.append(f"{relativo}: {id_tarea} sin '{campo}' (regla E2)")
        steps = _agrupar_steps(bloque)
        if not steps:
            fallos.append(
                f"{relativo}: {id_tarea} sin steps con checkbox (regla E3)"
            )
        for step in steps:
            if "verificación:" not in step.lower():
                fallos.append(
                    f"{relativo}: {id_tarea}: step sin criterio de "
                    "verificación (regla E4)"
                )
        for ln in bloque:
            for rota in _rutas_rotas(ln, root):
                fallos.append(
                    f"{relativo}: {id_tarea}: ruta referenciada "
                    f"inexistente: {rota} (regla E5)"
                )
    return fallos


def planes_declarados(root: Path) -> list[Path] | None:
    """Archivos de planes que el gate debe comprobar, según config.

    None = fail-closed: sin clave `plans` no se comprueba nada.
    Levanta ValueError si la config es inválida (clave desconocida, o
    `plans` presente con tipo inválido — un typo no puede apagar el gate).
    """
    config = cargar_config(root)
    if "plans" not in config:
        return None
    plans_dir = config["plans"]
    if not isinstance(plans_dir, str) or not plans_dir.strip():
        raise ValueError(
            f"{CONFIG_NAME}: «plans» debe ser un directorio relativo (texto)"
        )
    directorio = root / plans_dir
    if not directorio.is_dir():
        raise ValueError(
            f"{CONFIG_NAME}: plans declarado pero el directorio no existe: {plans_dir}"
        )
    archivos = sorted(directorio.glob("*.md"))
    if not archivos:
        raise ValueError(
            f"{CONFIG_NAME}: plans declarado pero sin planes en {plans_dir}"
        )
    return archivos


def _repo_del_archivo(archivo: Path) -> Path:
    """Raíz del repo que contiene al archivo (.git o config), subiendo;
    si no se encuentra, el directorio del archivo."""
    actual = archivo.resolve().parent
    while True:
        if (actual / ".git").exists() or (actual / CONFIG_NAME).is_file():
            return actual
        if actual.parent == actual:
            return archivo.resolve().parent
        actual = actual.parent


def main_para_tests(root: Path, archivos: list[str]) -> list[str]:
    """Núcleo puro para los tests; devuelve la lista de fallos."""
    fallos: list[str] = []
    for archivo in archivos:
        texto = (root / archivo).read_text(encoding="utf-8")
        fallos.extend(comprobar_plan(archivo, texto, root))
    return fallos


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    raiz = ROOT
    if argv and argv[0] == "--root":
        if len(argv) < 2:
            print("BLOQ — --root exige un directorio")
            return 2
        raiz = Path(argv[1]).resolve()
        argv = argv[2:]

    if argv:  # archivos explícitos: evidencia sobre planes de cualquier repo
        fallos: list[str] = []
        for arg in argv:
            ruta = Path(arg)
            if not ruta.is_file():
                print(f"BLOQ — no existe: {arg}")
                return 1
            root_archivo = _repo_del_archivo(ruta)
            fallos.extend(
                comprobar_plan(arg, ruta.read_text(encoding="utf-8"), root_archivo)
            )
        if fallos:
            print("BLOQ — check_plans encontró incumplimientos")
            for fallo in fallos:
                print(f"- {fallo}")
            return 1
        print(f"OK — {len(argv)} plan(es) verificados (estructura E1-E5)")
        return 0

    try:
        archivos = planes_declarados(raiz)
    except (ValueError, OSError) as exc:
        print("BLOQ — check_plans no pudo leer la configuración del proyecto")
        print(f"- {exc}")
        return 1

    if archivos is None:
        print("OK — sin planes declarados (fail-closed: clave 'plans' ausente)")
        return 0

    fallos = []
    for ruta in archivos:
        fallos.extend(
            comprobar_plan(
                ruta.relative_to(raiz).as_posix(),
                ruta.read_text(encoding="utf-8"),
                raiz,
            )
        )
    if fallos:
        print("BLOQ — check_plans encontró incumplimientos")
        for fallo in fallos:
            print(f"- {fallo}")
        return 1

    print(f"OK — {len(archivos)} plan(es) verificados (estructura E1-E5)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
