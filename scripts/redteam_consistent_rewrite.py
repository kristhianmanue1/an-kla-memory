#!/usr/bin/env python3
"""redteam_consistent_rewrite.py — G-3: caracterización del límite de detección.

Ataque simulado: un adversario con control de escritura del medio reescribe
la memoria de forma CONSISTENTE — no corrompe nada, sino que fabrica una
cadena alternativa internamente válida (nuevos segments, nuevo manifiesto,
nuevo CURRENT) que `verify` acepta. Esto caracteriza la frontera
tamper-evidence vs tamper-proofness declarada en ADR-0043.

Guard mecánico (fail-closed, check guard_store_canonico de la tarjeta):
este script RECHAZA operar sobre cualquier root que contenga `.git/` o
`docs/architecture/` — es decir, solo acepta copias desechables en tmp,
nunca un checkout de repositorio. El mensaje de rechazo es canónico.

Uso:
    python3 scripts/redteam_consistent_rewrite.py --target-root /tmp/ankla-rt-XXXX
    python3 scripts/redteam_consistent_rewrite.py --selftest

El script NO usa los writers de an_kla para el ataque (un atacante no
respeta write-policy); sí los usa para leer/verificar el estado resultante,
que es exactamente lo que un consumidor legítimo ejecutaría.

Salida: JSON a stdout con el resultado del ataque y los exit codes observados
de las verificaciones post-ataque. Exit 0 = ataque caracterizado (incluye el
caso "verify aceptó la falsificación"); exit != 0 = error operacional.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import shutil
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from an_kla.canonical import canonical_json, digest_bytes, digest_json  # noqa: E402

GUARD_MESSAGE = "redteam_refused: target root looks like a repository checkout (contains .git/ or docs/architecture/); attack only runs on disposable copies in tmp"

RESULT_SCHEMA = "an-kla/redteam-consistent-rewrite-result/v1"

FORBIDDEN_MARKERS = (".git", "docs/architecture")


def refuse_repository_root(target_root: Path) -> None:
    """Fail-closed contra el default '.' y cualquier checkout real."""
    resolved = target_root.resolve()
    for marker in FORBIDDEN_MARKERS:
        if (resolved / marker).exists():
            print(GUARD_MESSAGE, file=sys.stderr)
            sys.exit(2)


def dir_tree_digest(root: Path) -> str:
    """sha256 determinista del árbol de archivos (paths relativos + bytes)."""
    accumulator = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        accumulator.update(str(path.relative_to(root)).encode("utf-8"))
        accumulator.update(b"\0")
        accumulator.update(hashlib.sha256(path.read_bytes()).digest())
    return accumulator.hexdigest()


def write_object(root: Path, kind: str, payload: bytes) -> str:
    """Escribe un objeto content-addressed como el store lo esperaría."""
    identifier = digest_bytes(payload)
    destination = root / ".an-kla" / "memory" / kind / "sha256" / (
        identifier[len("sha256:"):] + ".json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return identifier


def write_segment(root: Path, stream: str, rows: list) -> str:
    payload = b"".join(canonical_json(row) + b"\n" for row in rows)
    identifier = digest_bytes(payload)
    destination = (
        root / ".an-kla" / "memory" / "segments" / stream / "sha256" /
        (identifier[len("sha256:"):] + ".jsonl")
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return identifier


def falsify(root: Path, lie_text: str) -> dict:
    """Fabrica una cadena alternativa coherente con un fact falso.

    Estrategia (mínimo esfuerzo del atacante): bifurcar desde la revisión
    corriente. El manifiesto falsificado referencia un segmento nuevo con el
    fact mentiroso AÑADIDO a los facts existentes, un checkpoint válido y un
    transaction_id sintáctico; CURRENT se apunta al manifiesto falsificado.
    La cadena parental permanece intacta (cada eslabón sigue verificando).
    """
    memory_root = root / ".an-kla" / "memory"
    current = (memory_root / "refs" / "CURRENT").read_text(encoding="ascii").strip()
    manifest_path = memory_root / "revisions" / "sha256" / (current[len("sha256:"):] + ".json")
    manifest = json.loads(manifest_path.read_bytes())

    # Copiar los facts vigentes y añadir el hecho falso.
    fact_rows = []
    for segment_id in manifest["facts_segments"]:
        segment_path = memory_root / "segments" / "facts" / "sha256" / (
            segment_id[len("sha256:"):] + ".jsonl"
        )
        fact_rows.extend(json.loads(line) for line in segment_path.read_bytes().decode("utf-8").splitlines())
    lie_record = {
        "id": "f-adversarial-consistent-rewrite-v1",
        "payload": {"text": lie_text, "topic": "adversarial-redteam"},
        "provenance": {
            "kind": "git_document",
            "repository": "kristhianmanue1/an-kla-memory",
            "commit": hashlib.sha256(b"").hexdigest(),
            "path": "docs/falsified-by-redteam.md",
            "sha256": hashlib.sha256(lie_text.encode("utf-8")).hexdigest(),
        },
        "schema": "an-kla/fact-v1",
        "status": "active",
    }
    fact_rows.append(lie_record)
    new_facts_segment = write_segment(root, "facts", fact_rows)

    new_manifest = {
        "canonicalization": manifest["canonicalization"],
        "checkpoint": manifest["checkpoint"],
        "episodes_segments": manifest["episodes_segments"],
        "events_segments": manifest["events_segments"],
        "facts_segments": [new_facts_segment],
        "integrity_claim": manifest["integrity_claim"],
        "parent": current,
        "revision": int(manifest["revision"]) + 1,
        "schema": manifest["schema"],
        "store_identity": manifest.get("store_identity"),
        "supersedes_map": manifest.get("supersedes_map", []),
        "transaction_id": str(uuid.uuid4()),
    }
    manifest_payload = canonical_json(new_manifest)
    new_manifest_id = write_object(root, "revisions", manifest_payload)

    (memory_root / "refs" / "CURRENT").write_text(new_manifest_id + "\n", encoding="ascii")
    return {
        "attack": "consistent_rewrite_fork",
        "base_revision": current,
        "forged_revision": new_manifest_id,
        "forged_segment": new_facts_segment,
        "lie_record_id": lie_record["id"],
    }


def run_cli(root: Path, args: list) -> dict:
    command = [sys.executable, "-m", "an_kla", "--project-root", str(root)] + args
    completed = subprocess.run(command, cwd=str(REPO_ROOT), capture_output=True, text=True)
    return {"command": " ".join(command), "exit_code": completed.returncode, "stdout": completed.stdout[:4000], "stderr": completed.stderr[:2000]}


def attack(target_root: Path) -> dict:
    refuse_repository_root(target_root)
    memory_root = target_root / ".an-kla" / "memory"
    if not memory_root.exists():
        print(f"redteam_refused: no .an-kla/memory under {target_root}", file=sys.stderr)
        sys.exit(3)

    before_digest = dir_tree_digest(memory_root)
    verify_before = run_cli(target_root, ["verify"])
    lie_text = (
        "RECORD FALSIFICADO POR RED-TEAM (G-3): este hecho fue inyectado por un "
        "adversario con control del medio mediante reescritura consistente; si lo "
        "estas leyendo via retrieve, la falsificación atravesó verify."
    )

    falsification = falsify(target_root, lie_text)
    after_digest = dir_tree_digest(memory_root)
    verify_after = run_cli(target_root, ["verify"])
    retrieve_after = run_cli(target_root, ["retrieve", "--query", "RECORD FALSIFICADO", "--budget", "2000"])

    accepted = verify_after["exit_code"] == 0
    lie_served = falsification["lie_record_id"] in (retrieve_after["stdout"] or "")
    return {
        "schema": RESULT_SCHEMA,
        "target_root": str(target_root),
        "memory_tree_sha256_before": before_digest,
        "memory_tree_sha256_after": after_digest,
        "verify_before": verify_before,
        "attack_details": falsification,
        "verify_after": verify_after,
        "retrieve_after": retrieve_after,
        "forgery_accepted_by_verify": accepted,
        "lie_served_to_consumer": lie_served,
    }


def make_disposable_copy() -> Path:
    """Copia el store canónico a tmp y devuelve el root de la copia.

    La copia es un root SIN .git ni docs/ — solo .an-kla — para que el
    guard de esta herramienta la acepte y para que ningún artefacto del
    repositorio pueda ser alcanzado por el ataque.
    """
    staging = Path(tempfile.mkdtemp(prefix="ankla-redteam-"))
    destination = staging / "copy"
    destination.mkdir()
    shutil.copytree(REPO_ROOT / ".an-kla", destination / ".an-kla")
    refuse_repository_root(destination)
    return destination


def boundary_failure_mode(result: dict) -> str | None:
    """Modo de fallo de frontera, o None si la frontera sigue en pie.

    ADR-0043 §Test de regresión (issue #109 punto 2): ambos modos de fallo
    imprimen el mismo mensaje canónico y salen con exit code 5 — ninguno es
    un éxito silencioso.
    """
    if (
        result["forgery_accepted_by_verify"] is True
        and result["lie_served_to_consumer"] is True
    ):
        return None
    if result["forgery_accepted_by_verify"] is not True:
        return "verify now rejects consistent rewrite"
    return "forgery accepted but lie not served to consumer"


def selftest() -> int:
    """Verifica el guard y el camino feliz sobre copia desechable."""
    # Guard: el propio repo DEBE ser rechazado.
    guard_probe = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--target-root", str(REPO_ROOT)],
        capture_output=True, text=True,
    )
    if guard_probe.returncode != 2 or GUARD_MESSAGE not in guard_probe.stderr:
        print("selftest FAIL: guard did not reject repository root", file=sys.stderr)
        return 1
    copy_root = make_disposable_copy()
    try:
        result = attack(copy_root)
        # Frontera ADR-0043 §Test de regresión: el resultado esperado es que
        # verify ACEPTE la falsificación y retrieve sirva la mentira. Si una
        # mejora futura voltea la frontera, es un evento visible con exit
        # code propio (5), no un éxito silencioso del `or` que antes
        # aceptaba también el caso contrario.
        boundary_holds = (
            result["forgery_accepted_by_verify"] is True
            and result["lie_served_to_consumer"] is True
        )
        failure_mode = boundary_failure_mode(result)
        if failure_mode is not None:
            print(
                f"redteam_boundary_changed: {failure_mode}; "
                "ADR-0043 must be reviewed",
                file=sys.stderr,
            )
        print(json.dumps({"selftest": "ok" if boundary_holds else "unexpected_shape", "guard": "refused_repo_root", "forgery_accepted_by_verify": result["forgery_accepted_by_verify"], "lie_served_to_consumer": result["lie_served_to_consumer"]}, indent=2))
        return 0 if boundary_holds else 5
    finally:
        shutil.rmtree(copy_root.parent, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-root", type=Path, help="root de la COPIA del store en tmp (requerido salvo --selftest)")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--keep-copy", action="store_true", help="no borrar la copia tmp (depuración; el resultado incluye su ruta)")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if args.target_root is None:
        print("redteam_refused: --target-root es obligatorio (no hay default; el default sería '.')", file=sys.stderr)
        return 4
    result = attack(args.target_root)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
