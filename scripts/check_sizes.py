"""check_sizes.py — gate duro de tamaño de archivos (líneas).

Valida límites de líneas por categoría para mantener archivos aptos para
contexto y preservar responsabilidad única. Exit 0 si todo dentro del límite
(o declarado como tech-debt conocida); exit 1 listando las violaciones.

Determinista: sin reloj, sin red, sin mutaciones; sólo lee archivos del
worktree. Coherente con el espíritu de los invariantes de pureza del motor.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Directorios nunca medidos (generados, caches, VCS, entorno).
EXENTOS_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".an-kla",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "build",
    "dist",
    "node_modules",
}

# Subcarpetas de docs consideradas históricas (no evergreen): no se miden.
DOCS_HISTORICOS = {"planning", "releases", "mejoras_ejemplo"}

# (descripción, patrón glob relativo a ROOT, límite duro en líneas).
REGLAS = [
    ("an_kla/**/*.py (módulos del paquete)", "an_kla/**/*.py", 800),
    ("scripts/*.py", "scripts/*.py", 400),
    ("docs/architecture/*.md (ADRs)", "docs/architecture/*.md", 400),
    ("docs/*.md (evergreen, raíz de docs)", "docs/*.md", 600),
    ("AGENTS.md", "AGENTS.md", 120),
]

# Tech-debt conocida: path relativo POSIX -> (límite de gracia, razón).
# El gate no bloquea estos archivos mientras se atiende la deuda, pero la
# evidencia aparece en la salida y el issue referenciado debe cerrarse para
# retirar la excepción.
TECH_DEBT = {
    # context_package.py (era 1011) se partió en #23 extrayendo el texto
    # canónico a context_text.py; ahora cumple el límite de 800 sin gracia.
    # ADR-0042 (622 líneas) pendiente de partir en ADR corto + detalle
    # técnico aparte — seguimiento en #95.
    "docs/architecture/0042-sealed-export-v1.md": (
        700,
        "#95 — partir en ADR normativo + apéndice técnico",
    ),
}


def lineas(ruta: Path) -> int:
    """Cuenta líneas de un archivo de texto; 0 si es binario o ilegible."""
    try:
        return len(ruta.read_text(encoding="utf-8").splitlines())
    except (UnicodeDecodeError, OSError):
        return 0


def es_exento(rel: Path) -> bool:
    """True si el archivo cae bajo un directorio exento o sufijo de egg-info."""
    if any(part in EXENTOS_DIRS for part in rel.parts):
        return True
    return any(str(rel).endswith(suf) for suf in (".egg-info",))


def limite_efectivo(rel_posix: str, limite: int) -> tuple[int, str | None]:
    """Devuelve (límite a aplicar, razón de gracia) para un path."""
    if rel_posix in TECH_DEBT:
        gracia, razon = TECH_DEBT[rel_posix]
        return gracia, razon
    return limite, None


def main() -> int:
    violaciones: list[str] = []

    for descripcion, patron, limite in REGLAS:
        for ruta in sorted(ROOT.glob(patron)):
            if not ruta.is_file():
                continue
            rel = ruta.relative_to(ROOT)
            if es_exento(rel):
                continue
            # Saltar subcarpetas históricas de docs aunque el glob las alcance.
            if rel.parts[0] == "docs" and len(rel.parts) > 2 and rel.parts[1] in DOCS_HISTORICOS:
                continue
            rel_posix = rel.as_posix()
            n = lineas(ruta)
            aplicable, razon = limite_efectivo(rel_posix, limite)
            if n > aplicable:
                marca = f" [TECH-DEBT: {razon}]" if razon else ""
                violaciones.append(
                    f"{rel_posix}: {n} líneas > {aplicable} "
                    f"({descripcion}){marca}"
                )

    if violaciones:
        print("check_sizes: FAIL — límites de tamaño excedidos:")
        for v in violaciones:
            print(f"  {v}")
        print(
            "\nSi es una excepción legítima, regístrala en TECH_DEBT de "
            "scripts/check_sizes.py con un issue de seguimiento."
        )
        return 1

    print("check_sizes: OK — todos los archivos dentro del límite duro.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
