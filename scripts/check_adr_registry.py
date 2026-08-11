"""Valida inventario y estado decisional de los ADRs.

El registro canónico vive en la tabla de ``docs/README.md``. Este gate comprueba
que los archivos sean continuos, que cada título use su número y que el estado
de cada ADR coincida con el registro. Sólo lee el worktree; no usa red ni reloj.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADR_DIR = ROOT / "docs" / "architecture"
REGISTRY = ROOT / "docs" / "README.md"

ADR_FILE_RE = re.compile(r"^(\d{4})-[a-z0-9][a-z0-9-]*\.md$")
TITLE_RE = re.compile(r"^# ADR-(\d{4}):\s+.+$", re.MULTILINE)
INLINE_STATE_RE = re.compile(
    r"^-\s+(?:\*\*Estado:\*\*|Estado:)\s*(.+)$", re.MULTILINE
)
LINK_RE = re.compile(r"\((architecture/(\d{4})-[^)]+\.md)\)")
MARKDOWN_LINK_RE = re.compile(r"\[[^]]+\]\(([^)]+)\)")
STATES = ("Aceptada", "Propuesta", "Rechazada", "Reemplazada")


def canonical_state(raw: str) -> str | None:
    normalized = raw.strip().casefold()
    for state in STATES:
        key = state.casefold()
        if normalized == key or (
            normalized.startswith(key) and normalized[len(key)] in " \t;:,(."
        ):
            return state
    return None


def document_state(text: str) -> tuple[str | None, str]:
    inline = INLINE_STATE_RE.search(text)
    if inline:
        raw = inline.group(1).strip()
        return canonical_state(raw), raw

    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != "## Estado":
            continue
        for candidate in lines[index + 1 :]:
            if candidate.strip():
                raw = candidate.strip()
                return canonical_state(raw), raw
    return None, ""


def registry_rows(text: str) -> tuple[dict[str, tuple[str, str]], list[str]]:
    rows: dict[str, tuple[str, str]] = {}
    duplicates: list[str] = []
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if len(cells) < 5 or re.fullmatch(r"\d{4}", cells[0]) is None:
            continue
        number = cells[0]
        link = LINK_RE.search(cells[1])
        if link is None:
            continue
        if number in rows:
            duplicates.append(number)
        rows[number] = (link.group(1), cells[3])
    return rows, duplicates


def registry_local_links(text: str) -> set[str]:
    links: set[str] = set()
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if len(cells) < 5 or re.fullmatch(r"\d{4}", cells[0]) is None:
            continue
        for target in MARKDOWN_LINK_RE.findall(line):
            if "://" not in target and not target.startswith("#"):
                links.add(target.split("#", 1)[0])
    return links


def check_registry(root: Path = ROOT) -> tuple[list[str], Counter[str]]:
    adr_dir = root / "docs" / "architecture"
    registry = root / "docs" / "README.md"
    errors: list[str] = []
    documents: dict[str, Path] = {}

    for path in sorted(adr_dir.glob("[0-9][0-9][0-9][0-9]-*.md")):
        match = ADR_FILE_RE.fullmatch(path.name)
        if match is None:
            errors.append(f"nombre ADR inválido: {path.relative_to(root)}")
            continue
        number = match.group(1)
        if number in documents:
            errors.append(f"número ADR duplicado: {number}")
        documents[number] = path

    numbers = sorted(int(number) for number in documents)
    expected = list(range(1, max(numbers, default=0) + 1))
    if numbers != expected:
        missing = sorted(set(expected) - set(numbers))
        errors.append(f"numeración no continua; faltan: {missing}")

    registry_text = registry.read_text(encoding="utf-8")
    rows, duplicate_rows = registry_rows(registry_text)
    for number in duplicate_rows:
        errors.append(f"fila duplicada en registro: {number}")
    for target in sorted(registry_local_links(registry_text)):
        if not (registry.parent / target).exists():
            errors.append(f"referencia local ausente en registro: {target}")

    states: Counter[str] = Counter()
    for number, path in documents.items():
        text = path.read_text(encoding="utf-8")
        title = TITLE_RE.search(text)
        if title is None or title.group(1) != number:
            errors.append(f"{path.name}: título ADR no coincide con {number}")

        state, raw_state = document_state(text)
        if state is None:
            errors.append(f"{path.name}: estado ausente o no canónico: {raw_state!r}")
        else:
            states[state] += 1

        row = rows.get(number)
        if row is None:
            errors.append(f"{path.name}: ausente del registro docs/README.md")
            continue
        indexed_path, indexed_state = row
        expected_path = f"architecture/{path.name}"
        if indexed_path != expected_path:
            errors.append(
                f"ADR-{number}: ruta del registro {indexed_path!r} != {expected_path!r}"
            )
        if canonical_state(indexed_state) != state:
            errors.append(
                f"ADR-{number}: estado del registro {indexed_state!r} "
                f"!= estado del ADR {raw_state!r}"
            )

    extra_rows = sorted(set(rows) - set(documents))
    for number in extra_rows:
        errors.append(f"ADR-{number}: registrado sin archivo")
    return errors, states


def main() -> int:
    errors, states = check_registry()
    if errors:
        print("check_adr_registry: FAIL")
        for error in errors:
            print(f"  - {error}")
        return 1
    total = sum(states.values())
    detail = ", ".join(f"{state.lower()}={states[state]}" for state in STATES if states[state])
    print(f"check_adr_registry: OK — {total} ADRs ({detail})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
