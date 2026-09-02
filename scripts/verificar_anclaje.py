#!/usr/bin/env python3
"""verificar_anclaje.py — verificación activa del protocolo de anclaje externo.

Implementa la mitad ejecutable de C1 (ADR-0044): calcula el digest del
directorio refs/ del store con el comando EXACTO del protocolo
(docs/gobernanza/anclajes/2026-08-31-anclaje-inicial.md):

    find .an-kla/memory/refs -type f -exec shasum -a 256 {} + | sort -k2 | shasum -a 256

y lo compara contra el último ancla parseable del registro. Fail-closed:
jamás escribe el store ni el registro, jamás "corrige" el ancla para que
coincida — divergencia = parada + escalamiento al dueño.

Exit codes canónicos (check guard_anclaje_script de la tarjeta):
    0   match
    1   divergencia (mensaje canónico + ambos sha256 en stderr)
    2   registro PRESENTE pero sin fila de ancla parseable
    3   store sin refs/
    4   archivo de registro AUSENTE
    >=10 errores de uso / IO

Nota sobre el digest: el pipeline canónico hace dos pasadas de
`shasum -a 256` (una por archivo, una al agregado ordenado por nombre con
`LC_ALL=C sort -k2`; el segundo shasum agrega el sufijo "  -" de stdin a su
entrada). `LC_ALL=C` fija la colación para que macOS y Ubuntu agreguen en
el mismo orden (issue #109 punto 3; sin ella, un locale distinto produce
divergencia FALSA en verificación cruzada de máquinas).
Por eso este script delega en el pipeline textual vía subproceso con shell:
reproducirlo en Python puro (hashlib) requeriría reimplementar el framing
exacto de shasum y sería una segunda implementación divergente del
protocolo. La fórmula canónica es el comando, no un algoritmo re-derivado
(pitfall B3 de la ronda de la tarjeta: la versión abreviada
`shasum | sort | shasum` produce sha1 y divergencia FALSA).

Uso:
    python3 scripts/verificar_anclaje.py
    python3 scripts/verificar_anclaje.py --refs-root /tmp/copia/.an-kla/memory/refs \
        --registry /tmp/copia/registro.md
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_REFS_ROOT = REPO_ROOT / ".an-kla" / "memory" / "refs"
DEFAULT_REGISTRY = (
    REPO_ROOT / "docs" / "gobernanza" / "anclajes"
    / "2026-08-31-anclaje-inicial.md"
)

DIVERGENCE_MESSAGE = (
    "anchor_divergence: stop fail-closed + escalar al dueño"
)

# Fila de ancla: | fecha | `digest` | origen | comparación | — digest sha256
# de 64 hex entre backticks. La última fila parseable (la más reciente) es
# el ancla vigente.
ANCHOR_ROW_RE = re.compile(r"^\|[^|]*\|\s*`([0-9a-f]{64})`[^|]*\|[^|]*\|")


def compute_refs_digest(refs_root: Path) -> str:
    """Digest del directorio refs/ con el comando EXACTO del protocolo.

    La primera pasada es shasum -a 256 por archivo; el agregado se ordena
    por nombre de archivo con colación C (LC_ALL=C sort -k2, issue #109
    punto 3) y se vuelve a hashear. Se ejecuta vía subproceso con el
    pipeline literal para no reimplementar el framing.
    """
    if not refs_root.is_dir():
        print(
            f"verificar_anclaje: store sin refs/: {refs_root}",
            file=sys.stderr,
        )
        sys.exit(3)
    # El pipeline canónico corre desde la raíz del repo con la ruta
    # RELATIVA `.an-kla/memory/refs`: las rutas forman parte de la entrada
    # del agregado, así que una ruta absoluta produce otro digest
    # (divergencia FALSA). Se reproduce la forma relativa canónica cuando
    # el layout coincide; si no, se cae a relativa-al-padre.
    resolved = refs_root.resolve()
    if resolved.name == "refs" and resolved.parents[1].name == ".an-kla":
        cwd = resolved.parents[2]
        relative = ".an-kla/memory/refs"
    else:
        cwd = resolved.parent
        relative = resolved.name
    command = (
        f"find {relative} -type f -exec shasum -a 256 {{}} + "
        f"| LC_ALL=C sort -k2 | shasum -a 256"
    )
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )
    if result.returncode != 0:
        print(
            f"verificar_anclaje: fallo computando digest (exit "
            f"{result.returncode}): {result.stderr.strip()}",
            file=sys.stderr,
        )
        sys.exit(11)
    digest = result.stdout.split()[0]
    if len(digest) != 64:
        print(
            f"verificar_anclaje: digest inesperado: {digest!r}",
            file=sys.stderr,
        )
        sys.exit(12)
    return digest


def read_last_anchor(registry: Path) -> str | None:
    """Último digest de ancla parseable del registro; None si no hay fila.

    Exit 4 si el archivo de registro no existe; exit 2 si existe pero no
    tiene ninguna fila de ancla parseable.
    """
    if not registry.is_file():
        print(
            f"verificar_anclaje: archivo de registro AUSENTE: {registry}",
            file=sys.stderr,
        )
        sys.exit(4)
    text = registry.read_text(encoding="utf-8")
    last: str | None = None
    for line in text.splitlines():
        match = ANCHOR_ROW_RE.match(line)
        if match:
            last = match.group(1)
    if last is None:
        print(
            "verificar_anclaje: registro presente pero sin fila de ancla "
            f"parseable: {registry}",
            file=sys.stderr,
        )
        sys.exit(2)
    return last


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verificación activa del protocolo de anclaje externo "
            "(ADR-0044 C1): digest de refs/ vs último ancla del registro."
        )
    )
    parser.add_argument(
        "--refs-root",
        type=Path,
        default=DEFAULT_REFS_ROOT,
        help=(
            "raíz refs/ del store a verificar (default: la del protocolo "
            "en este repo; los tests usan copias tmp)"
        ),
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY,
        help="archivo de registro de anclas (default: el del protocolo)",
    )
    args = parser.parse_args(argv)

    refs_digest = compute_refs_digest(args.refs_root)
    anchor = read_last_anchor(args.registry)

    if refs_digest == anchor:
        print(f"anchor_match: {refs_digest}")
        return 0

    print(DIVERGENCE_MESSAGE, file=sys.stderr)
    print(f"refs_sha256:  {refs_digest}", file=sys.stderr)
    print(f"anchor_sha256: {anchor}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
