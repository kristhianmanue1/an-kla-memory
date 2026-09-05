#!/usr/bin/env python3
"""ankla_agent.py — wrapper de referencia para agentes (issue #111 / P6).

Ejemplo, no core: envuelve el CLI de AN-KLA con las compensaciones medidas
en la ronda adversarial externa del 2026-09-02:

(a) lectura post-escritura obligatoria: un commit sin texto indexable tiene
    éxito pero el registro queda invisible a retrieval (`no_text`); el
    wrapper re-lee con `retrieve` y falla si el registro no se sirve;
(b) retry con re-plan ante CAS perdido (`current_changed:expected=`) o lock
    ocupado (`write_lock_busy`): relee `status`, reconstruye proposal y
    authority contra la revisión nueva y reintenta (los planes no se
    reutilizan ni se fuerzan);
(c) salida ambigua: si el commit muere sin JSON de outcome, el wrapper se
    niega a reintentar a ciegas y exige `transaction inspect` con el UUID
    del plan antes de decidir.

Sólo usa la stdlib: habla con el motor exclusivamente por subprocess del
CLI (`python -m an_kla`); los digests canónicos se calculan con
`an_kla.canonical.digest_json` en el intérprete del propio CLI.

No es un generador autorizado de propuestas (decisión documental, issue
#71): construye los mismos objetos que un agente manual y los somete al
mismo flujo `plan-write` -> `commit-write-plan`.

Uso:
    python3 ankla_agent.py --demo                    # demo en tmp
    python3 ankla_agent.py <project-root> "<texto>"  # escritura verificada
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

DIGEST_SNIPPET = (
    "import json,sys;from an_kla.canonical import digest_json;"
    "print(digest_json(json.load(sys.stdin)))"
)
ISSUER_CONFIG = {
    "kind": "model",
    "id": "agent-reference-wrapper",
    "profile": "reference-wrapper/v1",
}
MAX_ATTEMPTS = 3
CLI_TIMEOUT_SECONDS = 180


class WriteVerificationError(RuntimeError):
    """La escritura se comprometió pero la lectura post-escritura falló."""


class AnKlaAgent:
    def __init__(self, project_root: Path, python: str = sys.executable) -> None:
        self.project_root = Path(project_root)
        self.python = python

    def run(self, args: list) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                [self.python, "-m", "an_kla", "--project-root", str(self.project_root)] + args,
                capture_output=True, text=True, timeout=CLI_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            # En POSIX el write lock es bloqueante sin deadline: un commit
            # colgado no debe colgar al wrapper. Resultado ambiguo: exigir
            # `transaction inspect` antes de decidir (camino (c)).
            raise RuntimeError(
                f"{args[0]} excedió {CLI_TIMEOUT_SECONDS}s sin respuesta: "
                "resultado ambiguo; exigir `transaction inspect <uuid>` "
                "antes de decidir (no reintentes a ciegas)"
            ) from exc

    def run_json(self, args: list) -> dict:
        completed = self.run(args)
        if completed.returncode != 0:
            raise RuntimeError(
                f"{args[0]} exit {completed.returncode}: {completed.stderr.strip()}"
            )
        return json.loads(completed.stdout)

    def current_revision(self) -> str:
        return self.run_json(["status"])["revision"]

    def _digest(self, obj: dict) -> str:
        completed = subprocess.run(
            [self.python, "-c", DIGEST_SNIPPET],
            input=json.dumps(obj), capture_output=True, text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"digest_json falló: {completed.stderr.strip()}")
        return completed.stdout.strip()

    def _objects_for_revision(self, record: dict, revision: str) -> tuple:
        proposal = {
            "schema": "an-kla/write-proposal-v1",
            "base_revision": revision,
            "stream": "facts",
            "operation": "add",
            "requested_representation": "summary",
            "record": {
                **record,
                "verified_at": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"),
            },
            "lineage": {"derived_from_retrieval": False, "refs": []},
        }
        authority = {
            "schema": "an-kla/write-authority-v1",
            "proposal_sha256": self._digest(proposal),
            "base_revision": revision,
            "authority_class": "model_derived",
            "issuer": {
                "kind": ISSUER_CONFIG["kind"],
                "id": ISSUER_CONFIG["id"],
                "configuration_fingerprint": self._digest(ISSUER_CONFIG),
            },
            "evidence": [],
            "scope": {
                "streams": ["facts"],
                "representations": ["summary"],
                "operations": ["add"],
            },
        }
        return proposal, authority

    def _plan(self, proposal: dict, authority: dict, workdir: Path) -> tuple:
        """plan-write sin mutación; devuelve (ruta_del_resultado, plan)."""
        proposal_path = workdir / "proposal.json"
        authority_path = workdir / "authority.json"
        planning_path = workdir / f"planning-{uuid.uuid4().hex}.json"
        proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
        authority_path.write_text(json.dumps(authority), encoding="utf-8")
        completed = self.run([
            "plan-write",
            "--proposal", str(proposal_path),
            "--authority", str(authority_path),
        ])
        if completed.returncode != 0:
            raise RuntimeError(
                f"plan-write exit {completed.returncode}: {completed.stderr.strip()}"
            )
        planning_path.write_text(completed.stdout, encoding="utf-8")
        return (proposal_path, authority_path, planning_path), json.loads(completed.stdout)

    def _commit(self, paths: tuple, revision: str) -> subprocess.CompletedProcess:
        proposal_path, authority_path, planning_path = paths
        return self.run([
            "commit-write-plan",
            "--expected-current", revision,
            "--proposal", str(proposal_path),
            "--authority", str(authority_path),
            "--planning-result", str(planning_path),
        ])

    def _plan_and_commit(self, record: dict, step=print) -> dict:
        """(b) un intento = leer revisión fresca, planificar, confirmar."""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            revision = self.current_revision()
            proposal, authority = self._objects_for_revision(record, revision)
            with tempfile.TemporaryDirectory(prefix="ankla-agent-") as tmp:
                paths, plan = self._plan(proposal, authority, Path(tmp))
                if plan.get("decision") == "skip":
                    step(f"plan-write -> skip {plan.get('reason_codes')}")
                    return plan
                commit = self._commit(paths, revision)
            if commit.returncode == 0:
                if not commit.stdout.strip():
                    # (c) exit 0 sin outcome (crash tras el commit): igual
                    # de ambiguo que un fallo sin JSON.
                    raise RuntimeError(
                        "commit exit 0 sin outcome: exigir `transaction "
                        "inspect <uuid>` antes de decidir"
                    )
                return json.loads(commit.stdout)
            err = commit.stderr
            if "current_changed:expected=" in err or "write_plan_base_changed" in err:
                step(f"intento {attempt}: CAS perdido (CURRENT avanzó); re-plan")
                continue
            if "write_lock_busy" in err:
                step(f"intento {attempt}: lock ocupado; re-plan tras backoff")
                time.sleep(0.5 * attempt)
                continue
            if not commit.stdout.strip():
                # (c) resultado ambiguo: no se repite a ciegas.
                raise RuntimeError(
                    "commit sin outcome: exigir `transaction inspect <uuid>` "
                    f"antes de decidir; stderr={err.strip()}"
                )
            raise RuntimeError(f"commit terminal: {err.strip()}")
        raise RuntimeError(f"sin commit tras {MAX_ATTEMPTS} intentos")

    def read_back(self, record_id: str, text: str) -> list:
        # Consulta acotada a las primeras palabras: BM25 con el texto
        # completo diluye el score y textos largos pueden caer fuera del
        # presupuesto (falso negativo).
        query = " ".join(text.split()[:12])
        read = self.run_json(["retrieve", "--query", query, "--budget", "1600"])
        excluded = read.get("excluded_detail", {}).get("ids", {})
        if record_id in excluded.get("budget", []):
            raise WriteVerificationError(
                f"{record_id} quedó excluido por presupuesto en la "
                "lectura post-escritura; revisa --budget del read-back"
            )
        return read.get("selected", [])

    def write_and_verify(self, record_id: str, text: str, step=print) -> dict:
        outcome = self._plan_and_commit(
            {"id": record_id, "payload": {"text": text}}, step)
        if not outcome.get("committed"):
            return outcome
        # (a) lectura post-escritura: retrieve es BM25 sobre TEXTO — la
        # consulta usa palabras del hecho, no el id físico del registro.
        served = {item.get("id") for item in self.read_back(record_id, text)}
        if record_id not in served:
            raise WriteVerificationError(
                f"{record_id} comprometido pero no servido por retrieve "
                f"(revisa excluded_detail / record_without_indexable_text)"
            )
        step(f"lectura post-escritura OK: {record_id} servido por retrieve")
        return outcome

    def demonstrate_cas_lost(self, record_id: str, text: str,
                             rival: "AnKlaAgent", step=print) -> dict:
        """(b) fuerza el caso: plan contra revisión R, escritura ajena que
        avanza CURRENT, y commit con --expected-current R (obsoleto)."""
        revision = self.current_revision()
        record = {"id": record_id, "payload": {"text": text}}
        proposal, authority = self._objects_for_revision(record, revision)
        workdir = Path(tempfile.mkdtemp(prefix="ankla-agent-cas-"))
        try:
            paths, _ = self._plan(proposal, authority, workdir)
            step(f"plan preparado contra {revision[:24]}…")
            rival.write_and_verify(
                "f-cas-rival",
                "Escritura concurrente que avanza CURRENT antes del commit.",
                step=step,
            )
            commit = self._commit(paths, revision)
            if commit.returncode == 0:
                raise RuntimeError("se esperaba CAS perdido y el commit pasó")
            if ("write_plan_base_changed" not in commit.stderr
                    and "current_changed:expected=" not in commit.stderr):
                raise RuntimeError(
                    f"falló por otra causa: {commit.stderr.strip()}"
                )
            step("CAS perdido detectado (write_plan_base_changed); re-planificando…")
            return self.write_and_verify(record_id, text, step=step)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


def demo() -> int:
    root = Path(tempfile.mkdtemp(prefix="ankla-wrapper-demo-"))
    agent = AnKlaAgent(root)
    try:
        print(f"[demo] project root efímero: {root}")
        print("[demo] init:", agent.run(["init"]).returncode)

        print("\n== (a) escritura + lectura post-escritura obligatoria ==")
        agent.write_and_verify(
            "f-wrapper-demo-1",
            "Hecho de demostración del wrapper de referencia (issue #111 P6).",
        )

        print("\n== (b) CAS perdido: plan obsoleto por escritura concurrente ==")
        agent.demonstrate_cas_lost(
            "f-wrapper-demo-2",
            "Escrito tras re-plan automático ante CAS perdido.",
            rival=AnKlaAgent(root),
        )
        print("\n[demo] OK: escritura verificada y retry con re-plan ejercitados")
        return 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="demo en tmp")
    parser.add_argument("project_root", nargs="?", help="proyecto con .an-kla")
    parser.add_argument("text", nargs="?", help="texto del hecho a escribir")
    args = parser.parse_args()
    if args.demo:
        return demo()
    if not args.project_root or not args.text:
        parser.error("requiere --demo o <project_root> <text>")
    agent = AnKlaAgent(args.project_root)
    outcome = agent.write_and_verify("f-agent-" + uuid.uuid4().hex[:8], args.text)
    print(json.dumps(outcome, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
