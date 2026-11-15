"""Corpus determinista de escenarios de ``commit_write_plan`` (fase A2, ADR-0063).

Lo usan ``tests/test_write_commit_locked_extraction.py`` (recalcula y compara
byte a byte con ``tests/fixtures/write-commit-goldens/``) y el generador de
goldens (``python -m tests.write_commit_scenarios <dir>`` con la raíz del repo
como cwd). No es una prueba: no empieza por ``test_``.

Determinismo: ``uuid.uuid4`` se sustituye por un contador, el proyecto usa una
raíz testigo (``WITNESS_ROOT``) y la ruta temporal real se normaliza a
``<TMP>`` en la salida. Cada escenario devuelve el resultado (o el código de error) y el árbol
del store resultante (ruta relativa y sha256 de cada archivo).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

from an_kla.canonical import digest_json
from an_kla.store import MemoryStore
from an_kla.write_policy import (
    WritePolicyError,
    build_write_plan,
    evaluate_write,
)

DIGEST_B = "sha256:" + "b" * 64
# Raíz absoluta inexistente: ``canonical_project_root_at_init`` entra en los
# digests y no puede depender del directorio temporal de cada corrida.
WITNESS_ROOT = Path("/an-kla-golden-root")
TXID = "11111111-2222-4333-8444-555555555555"
TXID_OTHER = "66666666-7777-4888-9999-aaaaaaaaaaaa"


def _counter_uuid4() -> Callable[[], uuid.UUID]:
    state = {"n": 0}

    def next_uuid() -> uuid.UUID:
        state["n"] += 1
        return uuid.UUID(int=state["n"], version=4)

    return next_uuid


def proposal_v1(base: str, record_id: str, **record: Any) -> dict[str, Any]:
    body = {"id": record_id, "indexable_text": record_id, "summary": record_id}
    body.update(record)
    return {
        "schema": "an-kla/write-proposal-v1",
        "base_revision": base,
        "stream": "facts",
        "operation": "add",
        "requested_representation": "summary",
        "record": body,
        "lineage": {"derived_from_retrieval": False, "refs": []},
    }


def proposal_v2(base: str, count: int = 3) -> dict[str, Any]:
    return {
        "schema": "an-kla/write-proposal-v2",
        "base_revision": base,
        "stream": "facts",
        "operation": "add",
        "requested_representation": "summary",
        "records": [
            {"id": f"b-{i}", "payload": {"text": f"registro {i} sobre quetzal"}}
            for i in range(count)
        ],
        "lineage": {"derived_from_retrieval": False, "refs": []},
    }


def authority_for(
    candidate: dict[str, Any], authority_class: str = "model_derived"
) -> dict[str, Any]:
    kind = {
        "model_derived": "model",
        "unresolved": "unknown",
        "tool_observed": "tool",
    }[authority_class]
    value: dict[str, Any] = {
        "schema": "an-kla/write-authority-v1",
        "proposal_sha256": digest_json(candidate),
        "base_revision": candidate["base_revision"],
        "authority_class": authority_class,
        "issuer": {
            "kind": kind,
            "id": "golden-authority",
            "configuration_fingerprint": DIGEST_B,
        },
        "evidence": [],
        "scope": {
            "streams": [candidate["stream"]],
            "representations": [candidate["requested_representation"]],
            "operations": [candidate["operation"]],
        },
    }
    if authority_class == "tool_observed":
        value["schema"] = "an-kla/write-authority-v2"
        value["evidence"] = [
            {
                "kind": "attestation_receipt",
                "id": "fabricado",
                "sha256": "sha256:" + "c" * 64,
                "resolution": "verified",
            }
        ]
    return value


def plan_for(store: MemoryStore, candidate: dict, auth: dict) -> dict[str, Any]:
    return store.plan_write(candidate, auth)


def commit_kwargs(candidate, auth, planning, base, **extra) -> dict[str, Any]:
    return {
        "expected_current_hash": base,
        "plan": planning["plan"],
        "proposal": candidate,
        "authority": auth,
        "decision": planning["decision"],
        **extra,
    }


def tree(root: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            # ``attest.key`` es aleatoria por diseño (ADR-0046): se registra
            # su presencia y tamaño, no su contenido.
            if relative == "attest.key":
                entries[relative] = f"<random:{path.stat().st_size}>"
                continue
            entries[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return entries


def _add(store: MemoryStore, base: str, record_id: str, txid: str | None = None):
    candidate = proposal_v1(base, record_id)
    auth = authority_for(candidate)
    planning = plan_for(store, candidate, auth)
    result = store.commit_write_plan(
        **commit_kwargs(candidate, auth, planning, base, transaction_id=txid)
    )
    return result["revision"], candidate, auth, planning


# Cada escenario recibe (store, root_revision) y devuelve el resultado de
# ``commit_write_plan`` (el dict o lo que dejó el store lo captura ``run``).


def s_add_v1(store, root):
    candidate = proposal_v1(root, "f-add")
    auth = authority_for(candidate)
    planning = plan_for(store, candidate, auth)
    return store.commit_write_plan(**commit_kwargs(candidate, auth, planning, root))


def s_batch_v2(store, root):
    candidate = proposal_v2(root)
    auth = authority_for(candidate)
    planning = plan_for(store, candidate, auth)
    return store.commit_write_plan(**commit_kwargs(candidate, auth, planning, root))


def s_supersede_ok(store, root):
    rev1, *_ = _add(store, root, "f-old")
    candidate = proposal_v1(rev1, "f-new")
    candidate["operation"] = "supersede"
    candidate["supersedes"] = "f-old"
    auth = authority_for(candidate)
    planning = plan_for(store, candidate, auth)
    return store.commit_write_plan(**commit_kwargs(candidate, auth, planning, rev1))


def s_supersede_target_missing(store, root):
    rev1, *_ = _add(store, root, "f-old")
    candidate = proposal_v1(rev1, "f-new")
    candidate["operation"] = "supersede"
    candidate["supersedes"] = "f-never-existed"
    auth = authority_for(candidate)
    decision = evaluate_write(candidate, auth)
    plan = build_write_plan(candidate, auth, decision)
    return store.commit_write_plan(
        expected_current_hash=rev1,
        plan=plan,
        proposal=candidate,
        authority=auth,
        decision=decision,
    )


def s_skip(store, root):
    candidate = proposal_v1(root, "f-skip")
    candidate["requested_representation"] = "full"
    auth = authority_for(candidate, "unresolved")
    planning = plan_for(store, candidate, auth)
    return store.commit_write_plan(**commit_kwargs(candidate, auth, planning, root))


def s_base_changed_no_txid(store, root):
    candidate = proposal_v1(root, "f-stale")
    auth = authority_for(candidate)
    planning = plan_for(store, candidate, auth)
    _add(store, root, "f-mover")
    return store.commit_write_plan(**commit_kwargs(candidate, auth, planning, root))


def s_replay_committed_txid(store, root):
    rev1, candidate, auth, planning = _add(store, root, "f-replay", TXID)
    return store.commit_write_plan(
        **commit_kwargs(candidate, auth, planning, root, transaction_id=TXID)
    )


def s_replay_uncommitted_txid(store, root):
    candidate = proposal_v1(root, "f-stale")
    auth = authority_for(candidate)
    planning = plan_for(store, candidate, auth)
    _add(store, root, "f-mover")
    return store.commit_write_plan(
        **commit_kwargs(candidate, auth, planning, root, transaction_id=TXID_OTHER)
    )


def s_tool_observed_no_receipt(store, root):
    candidate = proposal_v1(root, "f-forged")
    candidate["requested_representation"] = "full"
    auth = authority_for(candidate, "tool_observed")
    planning = plan_for(store, candidate, auth)
    return store.commit_write_plan(**commit_kwargs(candidate, auth, planning, root))


def s_no_indexable_text(store, root):
    candidate = proposal_v1(root, "f-notext")
    candidate["record"] = {"id": "f-notext"}
    auth = authority_for(candidate)
    planning = plan_for(store, candidate, auth)
    return store.commit_write_plan(**commit_kwargs(candidate, auth, planning, root))


def _unlock_fails():
    import fcntl

    original = fcntl.flock

    def injected(fd, operation):
        if operation == fcntl.LOCK_UN:
            raise OSError("unlock-EIO")
        return original(fd, operation)

    return patch("fcntl.flock", side_effect=injected)


def s_batch_no_text(store, root):
    candidate = proposal_v2(root, count=2)
    candidate["records"] = [{"id": "b-0"}, {"id": "b-1"}]
    auth = authority_for(candidate)
    planning = plan_for(store, candidate, auth)
    return store.commit_write_plan(**commit_kwargs(candidate, auth, planning, root))


def s_replay_release_error(store, root):
    rev1, candidate, auth, planning = _add(store, root, "f-replay", TXID)
    with _unlock_fails():
        return store.commit_write_plan(
            **commit_kwargs(candidate, auth, planning, root, transaction_id=TXID)
        )


def s_skip_release_error(store, root):
    candidate = proposal_v1(root, "f-skip")
    candidate["requested_representation"] = "full"
    auth = authority_for(candidate, "unresolved")
    planning = plan_for(store, candidate, auth)
    with _unlock_fails():
        return store.commit_write_plan(**commit_kwargs(candidate, auth, planning, root))


def s_release_error(store, root):
    candidate = proposal_v1(root, "f-unlock")
    auth = authority_for(candidate)
    planning = plan_for(store, candidate, auth)
    with _unlock_fails():
        return store.commit_write_plan(
            **commit_kwargs(candidate, auth, planning, root, transaction_id=TXID)
        )


SCENARIOS: dict[str, Callable[[MemoryStore, str], dict[str, Any]]] = {
    "add_v1": s_add_v1,
    "batch_v2": s_batch_v2,
    "supersede_ok": s_supersede_ok,
    "supersede_target_missing": s_supersede_target_missing,
    "skip": s_skip,
    "write_plan_base_changed_no_txid": s_base_changed_no_txid,
    "replay_committed_txid": s_replay_committed_txid,
    "replay_uncommitted_txid": s_replay_uncommitted_txid,
    "tool_observed_no_receipt": s_tool_observed_no_receipt,
    "record_without_indexable_text": s_no_indexable_text,
    "release_error_on_unlock": s_release_error,
    "batch_v2_without_indexable_text": s_batch_no_text,
    "replay_release_error_on_unlock": s_replay_release_error,
    "skip_release_error_on_unlock": s_skip_release_error,
}


def run_scenario(name: str, base_dir: Path) -> dict[str, Any]:
    """Ejecuta un escenario en un store nuevo y devuelve su salida canónica.

    ``base_dir`` es un directorio propio de quien llama (p. ej. un
    ``TemporaryDirectory`` bajo ``TMPDIR``). Los digests del store incluyen la
    raíz del proyecto, así que se fija una raíz testigo (``WITNESS_ROOT``)
    antes de inicializar y la salida no depende de ``base_dir``.
    """

    project = base_dir / name
    if project.exists():
        shutil.rmtree(project)
    project.mkdir(parents=True)
    with patch("uuid.uuid4", _counter_uuid4()):
        store = MemoryStore(project)
        store.project_root = WITNESS_ROOT
        root = store.initialize()
        try:
            outcome: dict[str, Any] = {"result": SCENARIOS[name](store, root)}
        except WritePolicyError as exc:
            outcome = {"error": exc.code, "detail": exc.detail}
    outcome["store_tree"] = tree(project / ".an-kla")
    text = json.dumps(outcome, sort_keys=True, indent=2, default=str)
    for real in {str(project), str(project.resolve())}:
        text = text.replace(real, "<TMP>")
    return json.loads(text.replace(str(WITNESS_ROOT), "<ROOT>"))


def canonical_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")


def main(argv: list[str]) -> int:
    target = Path(argv[1])
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as base:
        for name in SCENARIOS:
            output = canonical_bytes(run_scenario(name, Path(base)))
            (target / f"{name}.json").write_bytes(output)
            print("golden", name)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
