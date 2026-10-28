"""Batería v2 (issue #167) — durabilidad: crash mid-commit y compactación 20k.

`run_crash_mid_commit`: store grande precargado, calibración de la latencia
de commit, y un subproceso escritor real que recibe SIGKILL con retardo
calibrado como fracción de esa latencia (para aterrizar dentro de
`commit_write_plan`). Cada intento registra evidencia de dónde aterrizó el
kill (`transaction inspect`, `recover`, `doctor`) y el escenario cierra con
una escritura gobernada post-crash (servicio restaurado). Nada se inventa:
donde la escala diminuta impide garantizar el aterrizaje, el intento se
registra con su evidencia y la limitación se declara en el resultado.

`run_compaction_large`: ceremonia de compactación completa por CLI sobre un
store de N revisiones (objetivo del issue: ~20.000) midiendo duración y la
**ventana de indisponibilidad** para escritores (escritura sonda que sólo
puede commitear cuando el lock se libera) más `snapshot()` resultante.
"""
from __future__ import annotations

import json
import multiprocessing
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from benchmarks.scale.core import (
    TEXT,
    build_authority,
    build_proposal,
    cli,
    dir_size_bytes,
    governed_write,
    internal_commit,
    make_store,
    subject_refs,
    timed,
)
from an_kla.store import IntegrityError, LockBusyError
from an_kla.write_policy import WritePolicyError


# ---------------------------------------------------------------- crash ----


def _preload_big(
    crash_ws: Path, records: int, batch: int
) -> tuple[Any, str, float]:
    """Precarga interna (diagnóstica) del store grande: lotes de `batch`."""
    store, cur = make_store(crash_ws)
    refs = subject_refs(store, 1)
    t0 = time.perf_counter()
    n = 0
    while n < records:
        facts = [
            {
                "id": f"seed-{n + i}",
                "subject_ref": refs[0],
                "payload": {"text": TEXT.format(i=n + i)},
            }
            for i in range(min(batch, records - n))
        ]
        cur = internal_commit(store, cur, facts)
        n += len(facts)
    return store, cur, time.perf_counter() - t0


def _mid_commit_writer(ws: Path, conn: Any) -> None:
    """Escritor gobernado en bucle; avisa por el pipe justo antes de commitear."""
    from an_kla.store import MemoryStore

    from benchmarks.scale.core import build_authority, build_proposal

    store = MemoryStore(str(ws))
    i = 0
    while True:
        txid = str(uuid.uuid4())
        record = {
            "id": f"m-{os.getpid()}-{i}",
            "payload": {"text": TEXT.format(i=i)},
        }
        cur = store.read_current()
        proposal = build_proposal(cur, record)
        authority = build_authority(proposal)
        planning = store.plan_write(proposal, authority)
        conn.send({"phase": "pre_commit", "txid": txid, "n": i})
        store.commit_write_plan(
            expected_current_hash=cur,
            proposal=proposal,
            authority=authority,
            decision=planning["decision"],
            plan=planning["plan"],
            transaction_id=txid,
        )
        conn.send({"phase": "committed", "txid": txid})
        i += 1


def _cli_json_any_rc(ws: Path, *args: str, timeout: int = 300) -> dict[str, Any]:
    """CLI de producto parseando stdout aunque el rc sea != 0.

    `transaction inspect` sale con rc=3 cuando el outcome no está firme
    (p. ej. journal preparado por un kill mid-commit): el payload diagnóstico
    vive igualmente en stdout y este runner lo preserva.
    """
    cmd = [sys.executable, "-m", "an_kla", "--project-root", str(ws), *args]
    out = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "AN_KLA_NO_UPDATE_CHECK": "1"},
    )
    try:
        parsed = json.loads(out.stdout)
    except json.JSONDecodeError:
        return {
            "ok": False, "returncode": out.returncode,
            "stderr_tail": out.stderr[-400:],
        }
    if isinstance(parsed, dict):
        parsed.setdefault("ok", True)
        parsed["cli_returncode"] = out.returncode
    return parsed


def _attempt_diagnostics(crash_ws: Path, txid: str | None) -> dict[str, Any]:
    verify = cli(crash_ws, "verify")
    status = cli(crash_ws, "status")
    doctor = cli(crash_ws, "doctor")
    recover = cli(crash_ws, "recover")
    inspect: dict[str, Any] = {}
    if txid:
        inspect = _cli_json_any_rc(crash_ws, "transaction", "inspect", txid)
    return {
        "verify_ok": bool(verify.get("ok")),
        "revision_number_after": status.get("revision_number"),
        "doctor_current_ok": bool(doctor.get("current_ok")),
        "doctor_quarantine_objects": doctor.get("quarantine_objects"),
        "recover_pending_transactions": len(
            recover.get("pending_transactions", [])
        ),
        "inspect_state": inspect.get("state"),
        "inspect_committed": inspect.get("committed"),
        "inspect_recorded": inspect.get("recorded"),
        "inspect_error_code": inspect.get("operation_error_code"),
    }


def run_crash_mid_commit(
    ws: Path, th: dict[str, Any], overrides: dict[str, Any] | None = None
) -> dict[str, Any]:
    cfg = th["crash_mid_commit"]
    ov = overrides or {}
    attempts = ov.get("attempts", cfg["attempts"])
    preload_records = ov.get("preload_records", cfg["preload_records"])
    preload_batch = ov.get("preload_batch", cfg["preload_batch"])
    fraction = ov.get(
        "kill_delay_fraction_of_commit", cfg["kill_delay_fraction_of_commit"]
    )
    marker_timeout = ov.get("marker_timeout_s", cfg["marker_timeout_s"])

    crash_ws = ws / "crash-mid-commit"
    crash_ws.mkdir(parents=True, exist_ok=True)
    t_cell = time.perf_counter()
    store, cur, preload_s = _preload_big(crash_ws, preload_records, preload_batch)
    refs = subject_refs(store, 1)

    # Calibración: latencia de un commit gobernado real sobre el store ya
    # grande. El retardo de kill se siembra como fracción de esta latencia.
    cur, probe_s, _decision = governed_write(
        store, cur,
        {"id": "probe-cal", "subject_ref": refs[0],
         "payload": {"text": TEXT.format(i=-1)}},
    )
    kill_delay_s = max(fraction * probe_s, 0.002)

    attempts_out: list[dict[str, Any]] = []
    for k in range(attempts):
        parent_conn, child_conn = multiprocessing.Pipe()
        p = multiprocessing.Process(
            target=_mid_commit_writer, args=(crash_ws, child_conn)
        )
        p.start()
        child_conn.close()
        entry: dict[str, Any] = {
            "attempt": k + 1,
            "kill_delay_s": kill_delay_s,
            "commit_probe_s": probe_s,
        }
        try:
            marker_ready = parent_conn.poll(marker_timeout)
        except (EOFError, OSError):
            marker_ready = False
        if not marker_ready:
            os.kill(p.pid, signal.SIGKILL)
            p.join(10)
            parent_conn.close()
            entry.update(
                {
                    "marker": False,
                    "note": "sin marcador pre-commit dentro del timeout; kill "
                            "aterrizó fuera de la ventana de commit",
                    **_attempt_diagnostics(crash_ws, None),
                }
            )
            attempts_out.append(entry)
            continue
        msg = parent_conn.recv()
        entry["txid"] = msg["txid"]
        entry["marker_n"] = msg["n"]
        time.sleep(kill_delay_s)
        os.kill(p.pid, signal.SIGKILL)
        p.join(10)
        parent_conn.close()
        entry.update(
            {"marker": True, **_attempt_diagnostics(crash_ws, msg["txid"])}
        )
        # Evidencia de aterrizaje mid-commit: journal preparado sin outcome
        # firme, o transacción grabada sin commit confirmado.
        entry["mid_commit_evidence"] = bool(
            entry["recover_pending_transactions"]
            or (
                entry["inspect_recorded"] is True
                and entry["inspect_committed"] is not True
            )
        )
        attempts_out.append(entry)

    # El servicio debe seguir aceptando escrituras gobernadas tras los kills.
    post: dict[str, Any] = {}
    try:
        cur_after = store.read_current()
        _rev, elapsed, _decision = governed_write(
            store, cur_after,
            {"id": "post-crash", "subject_ref": refs[0],
             "payload": {"text": "post recovery"}},
        )
        post = {"committed": True, "write_s": elapsed}
    except Exception as exc:
        post = {"committed": False, "error": f"{type(exc).__name__}: {exc}"}

    return {
        "schema": "an-kla/scale-battery-scenario/v1",
        "scenario": "crash_mid_commit",
        "battery_phase": "v2-#167",
        "internal_commit_diagnostic": "sólo la precarga (lotes internos); los "
                                      "commits interrumpidos son gobernados",
        "method": "SIGKILL con retardo calibrado (fracción de la latencia de "
                  "commit observada) tras marcador pre-commit del escritor",
        "params": {
            "attempts": attempts,
            "preload_records": preload_records,
            "preload_batch": preload_batch,
            "kill_delay_fraction_of_commit": fraction,
        },
        "preload_s": preload_s,
        "commit_probe_s": probe_s,
        "attempts": attempts_out,
        "landing_summary": {
            "mid_commit": sum(
                1 for a in attempts_out if a.get("mid_commit_evidence")
            ),
            "post_commit": sum(
                1 for a in attempts_out
                if a.get("inspect_committed") is True
            ),
            "pre_commit": sum(
                1 for a in attempts_out
                if a.get("marker")
                and a.get("inspect_committed") is not True
                and not a.get("mid_commit_evidence")
            ),
            "no_marker": sum(1 for a in attempts_out if not a.get("marker")),
        },
        "post_crash": post,
        "verify_all_ok": all(a["verify_ok"] for a in attempts_out),
        "doctor_all_ok": all(a["doctor_current_ok"] for a in attempts_out),
        "wall_s": time.perf_counter() - t_cell,
        "limitations": [
            "El aterrizaje del SIGKILL dentro de commit_write_plan es "
            "probabilístico incluso con retardo calibrado: cada intento "
            "registra su evidencia (journal preparado, outcome inspeccionado) "
            "en vez de afirmar el punto de muerte.",
            "La precarga del store grande usa commit interno por lotes "
            "(diagnóstico); los commits interrumpidos son siempre por la vía "
            "gobernada pública.",
        ],
        "ok": bool(
            all(a["verify_ok"] for a in attempts_out)
            and all(a["doctor_current_ok"] for a in attempts_out)
            and post.get("committed") is True
        ),
    }


# ---------------------------------------------------------- compacción ----


def _popen_cli(ws: Path, *args: str) -> subprocess.Popen:
    cmd = [sys.executable, "-m", "an_kla", "--project-root", str(ws), *args]
    return subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={**os.environ, "AN_KLA_NO_UPDATE_CHECK": "1"},
    )


def _probe_writer(store: Any, refs: list[str], deadline_s: float) -> dict[str, Any]:
    """Escritura sonda: mide cuánto tarda un escritor en lograr commitear.

    Durante `compact commit` el lock de escritura está tomado: la sonda
    bloquea en `commit_write_plan` hasta liberación (o LockBusyError al
    agotar el deadline) y revalida CAS si la epoch cambió bajo ella.
    """
    t0 = time.perf_counter()
    cas = 0
    lock_busy = 0
    epoch_archived = 0
    committed = False
    while time.perf_counter() - t0 < deadline_s:
        cur_now = store.read_current()
        record = {
            "id": f"probe-{uuid.uuid4().hex[:8]}",
            "subject_ref": refs[0],
            "payload": {"text": "sonda de indisponibilidad"},
        }
        proposal = build_proposal(cur_now, record)
        authority = build_authority(proposal)
        try:
            planning = store.plan_write(proposal, authority)
        except WritePolicyError:
            cas += 1
            continue
        except IntegrityError as exc:
            # Hallazgo observado en carrera: la revisión leída por la sonda
            # fue archivada por la compactación mientras plan_write derivaba
            # su snapshot. Es el cambio de epoch manifestándose; se reintenta
            # sobre la epoch vigente y se registra.
            if "archived_by_compaction" in str(exc):
                epoch_archived += 1
                continue
            raise
        try:
            result = store.commit_write_plan(
                expected_current_hash=cur_now,
                proposal=proposal,
                authority=authority,
                decision=planning["decision"],
                plan=planning["plan"],
            )
            if result.get("committed"):
                committed = True
                break
            cas += 1
        except LockBusyError:
            lock_busy += 1
    return {
        "committed": committed,
        "blocked_s": time.perf_counter() - t0,
        "cas_retries": cas,
        "lock_busy_errors": lock_busy,
        "epoch_archived_events": epoch_archived,
    }


def run_compaction_large(
    ws: Path, th: dict[str, Any], overrides: dict[str, Any] | None = None
) -> dict[str, Any]:
    cfg = th["compaction_large"]
    ov = overrides or {}
    target = ov.get("target_revisions", cfg["target_revisions"])
    probe_delay = ov.get("probe_delay_s", cfg["probe_delay_s"])
    probe_budget = ov.get("probe_budget_s", cfg["probe_budget_s"])
    cli_timeout = ov.get("cli_timeout_s", cfg.get("cli_timeout_s", 14400))

    comp_ws = ws / "compaction-large"
    comp_ws.mkdir(parents=True, exist_ok=True)
    store, cur = make_store(comp_ws)
    refs = subject_refs(store, 1)

    t_build = time.perf_counter()
    for i in range(target):
        cur = internal_commit(
            store,
            cur,
            [{
                "id": f"k-{i}",
                "subject_ref": refs[0],
                "payload": {"text": TEXT.format(i=i)},
            }],
        )
    build_s = time.perf_counter() - t_build
    snapshot_before_s = timed(store.snapshot)
    bytes_before = dir_size_bytes(comp_ws)

    bundle = comp_ws / "bundle.tar"
    t0 = time.perf_counter()
    export = cli(comp_ws, "export", "create", "--bundle", str(bundle),
                 timeout=cli_timeout)
    export_s = time.perf_counter() - t0
    manifest_sha = next(
        (v for k, v in export.items()
         if "manifest" in k and isinstance(v, str) and v.startswith("sha256:")),
        None,
    )
    proposal = {
        "schema": "an-kla/compaction-proposal-v1",
        "base_revision": cur,
        "epoch_id": str(uuid.uuid4()),
        "transaction_id": str(uuid.uuid4()),
        "export_manifest_sha256": manifest_sha,
    }
    proposal_path = comp_ws / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")

    t0 = time.perf_counter()
    plan = cli(comp_ws, "compact", "plan",
               "--proposal", str(proposal_path), "--bundle", str(bundle),
               timeout=cli_timeout)
    plan_s = time.perf_counter() - t0
    # cli() inyecta "ok" para diagnóstico; el validador estricto del CLI
    # exige el conjunto exacto de campos al re-leer el archivo.
    plan_path = comp_ws / "compact-plan.json"
    plan_path.write_text(
        json.dumps({k: v for k, v in plan.items() if k != "ok"}),
        encoding="utf-8",
    )

    # `compact commit` en subproceso; la sonda de indisponibilidad intenta
    # escribir desde el proceso padre mientras el lock está tomado.
    t0 = time.perf_counter()
    proc = _popen_cli(
        comp_ws, "compact", "commit",
        "--planning-result", str(plan_path), "--expected-current", cur,
        "--bundle", str(bundle),
    )
    time.sleep(probe_delay)
    probe = _probe_writer(store, refs, probe_budget)
    if not probe["committed"]:
        # Observación censurada: el presupuesto de la sonda venció antes de
        # la liberación del lock (compact commit más largo que el presupuesto).
        probe["censored"] = (
            "presupuesto de sonda agotado sin commit; la ventana registrada "
            "es una cota inferior de la indisponibilidad real"
        )
    stdout, stderr = proc.communicate(timeout=max(cli_timeout, 300))
    commit_s = time.perf_counter() - t0
    if proc.returncode != 0:
        commit: dict[str, Any] = {
            "ok": False, "returncode": proc.returncode,
            "stderr_tail": stderr[-800:],
        }
    else:
        try:
            commit = json.loads(stdout)
            commit.setdefault("ok", True)
        except json.JSONDecodeError:
            commit = {"ok": False, "stdout_tail": stdout[-800:]}

    snapshot_after_s = timed(store.snapshot)
    verify = cli(comp_ws, "verify")
    status = cli(comp_ws, "status")
    return {
        "schema": "an-kla/scale-battery-scenario/v1",
        "scenario": "compaction_large",
        "battery_phase": "v2-#167",
        "internal_commit_diagnostic": "sólo la construcción (revisiones por "
                                      "commit interno); la compactación es la "
                                      "ceremonia CLI completa",
        "params": {
            "target_revisions": target,
            "probe_delay_s": probe_delay,
        },
        "timings_s": {
            "build": build_s,
            "export_create": export_s,
            "compact_plan": plan_s,
            "compact_commit": commit_s,
        },
        "unavailability_window_s": probe["blocked_s"],
        "probe": probe,
        "limitations": [
            "La sonda de indisponibilidad arranca a probe_delay_s del "
            "lanzamiento de `compact commit`: si dispara antes de que el "
            "subproceso tome el lock, el commit aborta con "
            "compaction_base_changed (carrera registrada, no silenciada); "
            "si dispara tras la liberación, la ventana se subestima. A "
            "escala completa el commit tarda segundos o minutos y la sonda "
            "aterriza dentro de la ventana con alta probabilidad.",
        ],
        "bytes": {"before": bytes_before, "after": dir_size_bytes(comp_ws)},
        "snapshot_s": {"before": snapshot_before_s, "after": snapshot_after_s},
        "revision_number_after": status.get("revision_number"),
        "export_ok": bool(export.get("ok")),
        "plan_ok": bool(plan.get("ok")),
        "commit_ok": bool(commit.get("ok")),
        "commit_result": commit,
        "verify_after": verify,
        "ok": bool(
            export.get("ok") and plan.get("ok") and commit.get("ok")
            and verify.get("ok")
        ),
    }
