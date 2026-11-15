"""Sondas H3-H8 y recolector: ``python -m spikes.e1a_recovery.probes <sonda> <salida.json>``."""

from __future__ import annotations

import errno
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from an_kla import transactions as tx
from an_kla.canonical import canonical_json, digest_json
from an_kla.store import MemoryStore
from an_kla.write_policy import WritePolicyError, build_write_plan, evaluate_write

from . import inbox as ib

BASE = Path("/var/tmp/ankla-spike-b2/probes")
PY = sys.executable
ENV = {**os.environ, "AN_KLA_NO_UPDATE_CHECK": "1", "PYTHONDONTWRITEBYTECODE": "1",
       "TMPDIR": "/var/tmp/ankla-spike-b2"}


def fresh(name: str) -> tuple[Path, MemoryStore]:
    project = BASE / name
    shutil.rmtree(project, ignore_errors=True)
    project.mkdir(parents=True)
    store = MemoryStore(str(project))
    store.initialize()
    return project, store


def worker(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([PY, "-m", "spikes.e1a_recovery.worker", *args], env={**ENV, **(env or {})},
                          capture_output=True, text=True, timeout=120)


def cut_state(name: str, point: str, n: int = 3) -> tuple[Path, MemoryStore]:
    project, store = fresh(name)
    for k in range(n):
        worker("enqueue1", str(project), f"{name}-{k}")
    r = worker("drain", str(project), env={"SPIKE_CUT": point})
    assert r.returncode == -9, (point, r.returncode, r.stderr[-200:])
    return project, MemoryStore(str(project))


def journal_stage(store: MemoryStore, txid: str) -> str | None:
    j = tx._journal(store, txid)
    return None if j is None else j.get("stage", "corrupt")


def batch_txids(store: MemoryStore) -> list[str]:
    ids = []
    for p in sorted((Path(store.root) / "transactions").glob("*.json")):
        j = json.loads(p.read_bytes())
        if j.get("attempt", {}).get("operation") == "write":
            ids.append(p.stem)
    return ids


# ------------------------------------------------------------------ H3
def supersede_batch(base: str, pairs: list[tuple[str, str]]) -> tuple[dict, dict]:
    proposal = {
        "schema": "an-kla/write-proposal-v2", "base_revision": base, "stream": "facts",
        "operation": "supersede", "requested_representation": "summary",
        "records": [{"id": new, "text": f"sustituto {new}"} for new, _ in pairs],
        "supersedes": {new: target for new, target in pairs},
        "lineage": {"derived_from_retrieval": False, "refs": []},
    }
    authority = {
        "schema": "an-kla/write-authority-v1", "proposal_sha256": digest_json(proposal),
        "base_revision": base, "authority_class": "model_derived",
        "issuer": {"kind": "model", "id": "spike", "configuration_fingerprint": ib.DIGEST_B},
        "evidence": [],
        "scope": {"streams": ["facts"], "representations": ["summary"], "operations": ["supersede"]},
    }
    return proposal, authority


def eval_ok(base: str, pairs: list[tuple[str, str]]) -> str | None:
    """Evaluación pura de un sub-lote: ``None`` si pasa, o el detalle del error."""
    proposal, authority = supersede_batch(base, pairs)
    try:
        decision = evaluate_write(proposal, authority)
        build_write_plan(proposal, authority, decision)
        return None
    except WritePolicyError as exc:
        return f"{exc.code}:{exc.detail}"


def probe_h3() -> dict:
    project, store = fresh("h3")
    n = 250
    for k in range(n):
        ib.enqueue(store, f"objetivo {k}", preflight=False)
    ib.drain_once(store)
    base = store.read_current()
    facts = [r["id"] for r in store.snapshot(base).records["facts"]]
    assert len(facts) == n, len(facts)
    pairs = [(f"s-{k}", facts[k]) for k in range(n - 1)] + [("s-dup", facts[0])]  # s-dup y s-0: mismo target
    t0 = time.perf_counter()
    whole = eval_ok(base, pairs)
    t_whole = time.perf_counter() - t0

    # (a) bisección por mitades, tal como la escribe el paso 7 del ADR
    calls = {"n": 0}

    def failing(sub: list) -> bool:
        calls["n"] += 1
        return eval_ok(base, sub) is not None

    levels = {"max": 0}

    def halves(sub: list, depth: int = 0) -> list | str:
        levels["max"] = max(levels["max"], depth)
        if not failing(sub):
            return []
        if len(sub) == 1:
            return list(sub)
        mid = len(sub) // 2
        left, right = halves(sub[:mid], depth + 1), halves(sub[mid:], depth + 1)
        if left == [] and right == []:
            return "unattributable_pairwise"  # el sub-lote falla pero ninguna mitad sola
        return (left if isinstance(left, list) else []) + (right if isinstance(right, list) else [])

    t0 = time.perf_counter()
    res_halves = halves(pairs)
    t_halves = time.perf_counter() - t0

    # (b) bisección por prefijos: el prefijo más corto que falla señala al culpable
    calls_p = {"n": 0}

    def prefix_isolate(entries: list) -> tuple[list, list]:
        accepted: list = []
        rejected: list = []
        rest = list(entries)
        while rest:
            calls_p["n"] += 1
            if eval_ok(base, accepted + rest) is None:
                accepted += rest
                break
            lo, hi = 1, len(rest)  # menor k con accepted+rest[:k] inválido
            while lo < hi:
                mid = (lo + hi) // 2
                calls_p["n"] += 1
                if eval_ok(base, accepted + rest[:mid]) is None:
                    lo = mid + 1
                else:
                    hi = mid
            accepted += rest[: lo - 1]
            rejected.append(rest[lo - 1])
            rest = rest[lo:]
        return accepted, rejected

    t0 = time.perf_counter()
    accepted, rejected = prefix_isolate(pairs)
    t_prefix = time.perf_counter() - t0

    # (c) prefiltro O(n) en el paso 4: segundo target repetido -> rechazada
    t0 = time.perf_counter()
    seen: dict[str, str] = {}
    pre_rejected, pre_kept = [], []
    for new, target in pairs:
        if target in seen:
            pre_rejected.append((new, "supersedes:duplicate_target"))
        else:
            seen[target] = new
            pre_kept.append((new, target))
    t_pre = time.perf_counter() - t0
    ok_pre = eval_ok(base, pre_kept)

    # commit real de los supervivientes con el cuerpo bloqueado del spike
    preflight = ib._mutation_preflight_with_context(store)
    proposal, authority = supersede_batch(base, accepted)
    decision = evaluate_write(proposal, authority)
    plan = build_write_plan(proposal, authority, decision)
    with ib.write_lock_deadline(Path(store.root), 2.0):
        _, outcome = ib.commit_batch_locked(store, preflight, base, proposal, authority, decision,
                                            plan, "00000000-0000-5000-8000-000000000003")
    snap = store.snapshot(store.read_current())
    return {
        "batch_size": len(pairs), "whole_batch_error": whole, "whole_batch_eval_ms": round(t_whole * 1000, 2),
        "halves": {"result": res_halves if isinstance(res_halves, str) else len(res_halves),
                   "eval_calls": calls["n"], "max_depth": levels["max"], "ms": round(t_halves * 1000, 1)},
        "prefix": {"accepted": len(accepted), "rejected": rejected, "eval_calls": calls_p["n"],
                   "ms": round(t_prefix * 1000, 1), "log2_250": 8},
        "prefilter_step4": {"rejected": pre_rejected, "kept": len(pre_kept), "ms": round(t_pre * 1000, 3),
                            "kept_batch_error": ok_pre},
        "commit_survivors": {"committed": outcome["committed"], "state": outcome["state"],
                             "superseded_vigentes": sum(1 for r in snap.records["facts"] if r["id"] in facts and r.get("status") == "sustituida")},
    }


# ------------------------------------------------------------------ H4
def probe_h4() -> dict:
    rows = {}
    # True / False / None(sin journal) a partir de cortes reales
    for point, label in (("pre_replace_current", "corte (ii) antes de CURRENT"),
                         ("post_replace_current", "corte (iii-a) tras CURRENT"),
                         ("post_journal", "corte (iv) tras journal"),
                         ("post_marker", "corte (v) tras marcador, antes del journal prepared")):
        project, store = cut_state("h4-" + point, point)
        marker = next((Path(store.root) / "inbox" / "inflight").glob("*.json"), None)
        txid = marker.stem
        info = tx.inspect_transaction(store, txid)
        rows[label] = {k: info[k] for k in ("committed", "state", "candidate_relation",
                                            "operation_error_code", "durability_state")}
        rows[label]["journal_stage"] = journal_stage(store, txid)
        rows[label]["never_started"] = ib.never_started(store, txid)
    # None: journal corrupto sin stage ni candidato
    project, store = fresh("h4-corrupt")
    txid = "11111111-1111-5111-8111-111111111111"
    (Path(store.root) / "transactions" / f"{txid}.json").write_bytes(b"{no json")
    info = tx.inspect_transaction(store, txid)
    rows["journal corrupto, sin candidato"] = {k: info[k] for k in ("committed", "state", "operation_error_code")}
    rows["journal corrupto, sin candidato"]["never_started"] = ib.never_started(store, txid)
    # None: dos candidatos con el mismo txid
    project, store = cut_state("h4-ambiguous", "pre_replace_current")
    marker = next((Path(store.root) / "inbox" / "inflight").glob("*.json"))
    txid = marker.stem
    cand = tx._manifest_candidates(store, txid)[0]
    manifest = json.loads((Path(store.root) / "revisions" / "sha256" / cand.removeprefix("sha256:")).with_suffix(".json").read_bytes())
    manifest["spike_noise"] = 1
    payload = canonical_json(manifest)
    from an_kla.canonical import digest_bytes
    ident = digest_bytes(payload)
    (Path(store.root) / "revisions" / "sha256" / (ident.removeprefix("sha256:") + ".json")).write_bytes(payload)
    info = tx.inspect_transaction(store, txid)
    rows["dos candidatos con el mismo txid"] = {k: info[k] for k in ("committed", "state", "operation_error_code")}
    rows["dos candidatos con el mismo txid"]["never_started"] = ib.never_started(store, txid)
    # None: read_current ilegible durante la inspección
    project, store = cut_state("h4-nocurrent", "pre_replace_current")
    txid = next((Path(store.root) / "inbox" / "inflight").glob("*.json")).stem
    with patch.object(store, "read_current", side_effect=OSError("injected")):
        info = tx.inspect_transaction(store, txid)
    rows["read_current falla al inspeccionar"] = {k: info[k] for k in ("committed", "state", "operation_error_code")}
    # qué hace el paso 0 en cada rama y cada configuración
    branch = {}
    for cfg, (cm, nm) in {"ADR literal (None->borra)": ("noop", "drop"), "r4 (None->aborta)": ("noop", "abort"),
                          "spike (None->never_started)": ("write", "smart")}.items():
        project, store = cut_state("h4-step0-" + cfg[:3].strip(), "post_marker")
        rep: dict = {}
        try:
            ib.reconcile_markers(store, ib.Inbox(store), close_mode=cm, none_mode=nm, report=rep)
            branch[cfg] = {"post_marker": "ok", "report": {k: len(v) for k, v in rep.items()}}
        except ib.DrainAbort as exc:
            branch[cfg] = {"post_marker": "DrainAbort " + exc.code}
        # y se repite en cada invocación siguiente (¿bloqueo permanente?)
        again = worker("drain", str(project), cm, nm)
        branch[cfg]["siguiente_drain"] = json.loads(again.stdout).get("state"), json.loads(again.stdout).get("drain_error")
        branch[cfg]["pending_tras"] = len(list((Path(store.root) / "inbox" / "pending").iterdir()))
    return {"inspect_transaction": rows, "paso_0_en_post_marker": branch}


# ------------------------------------------------------------------ H5
def probe_h5() -> dict:
    out: dict = {}
    for point in ("post_replace_current", "pre_committed_journal"):
        project, store = cut_state("h5-" + point, point)
        txid = next((Path(store.root) / "inbox" / "inflight").glob("*.json")).stem
        root = Path(store.root)
        rdir = root / "transactions" / txid / "receipts" / "sha256"
        kinds = sorted(json.loads(p.read_bytes())["kind"] for p in rdir.glob("*.json"))
        j = tx._journal(store, txid)
        res = {"journal_stage_tras_corte": j["stage"], "journal.current_receipt": j.get("current_receipt"),
               "journal.observed_log": j.get("observed_log"), "recibos_en_disco": kinds}
        info = tx.inspect_transaction(store, txid)
        res["inspect_tras_corte"] = {k: info[k] for k in ("committed", "state", "durability_state", "audit_state")}
        # (1) ruta de replay: _commit_locked con el mismo attempt
        base = j["parent"]
        attempt = j["attempt"]
        before = (root / "transactions" / f"{txid}.json").read_bytes()
        with ib.write_lock_deadline(root, 2.0):
            rev, outc = store._commit_locked(observed=base, checkpoint_patch={}, pending={"facts": [], "events": [], "episodes": []}, attempt=attempt)
        res["replay__commit_locked"] = {"state": outc["state"], "journal_cambia": before != (root / "transactions" / f"{txid}.json").read_bytes()}
        # (2) _reconcile_committed_journal de compaction con un `planning` mínimo
        from an_kla import compaction
        planning = {"proposal": {"transaction_id": txid, "base_revision": base},
                    "plan": {"core": {"candidate_revision": j["candidate"]}}}
        try:
            with ib.write_lock_deadline(root, 2.0):
                compaction._reconcile_committed_journal(store, planning, attempt, store.read_current())
            after = tx.inspect_transaction(store, txid)
            res["compaction._reconcile_committed_journal"] = {
                "journal_stage": tx._journal(store, txid)["stage"], "state": after["state"],
                "current_receipt_en_journal": tx._journal(store, txid).get("current_receipt")}
        except Exception as exc:  # noqa: BLE001
            res["compaction._reconcile_committed_journal"] = "error " + type(exc).__name__ + " " + str(exc)
        # restaurar el estado original del corte para probar el cierre del spike
        project2, store2 = cut_state("h5b-" + point, point)
        txid2 = next((Path(store2.root) / "inbox" / "inflight").glob("*.json")).stem
        with ib.write_lock_deadline(Path(store2.root), 2.0):
            res["cierre_spike"] = ib.close_committed_journal(store2, txid2)
        j2 = tx._journal(store2, txid2)
        res["cierre_spike"]["journal.current_receipt"] = j2.get("current_receipt")
        res["cierre_spike"]["journal.candidate_receipt"] = j2.get("candidate_receipt")
        # repair_durability explícito, si el recibo current-durable falta
        if res["cierre_spike"]["durability_state"] != "complete":
            from an_kla.transaction_repair import repair_durability
            rep = repair_durability(store2, txid2)
            res["tras_repair_durability"] = {"state": rep["state"], "durability_state": rep["durability_state"]}
        # idempotencia del cierre
        with ib.write_lock_deadline(Path(store2.root), 2.0):
            res["cierre_segunda_vez"] = ib.close_committed_journal(store2, txid2)
        res["verify_ok"] = store2.verify()["ok"]
        out[point] = res
    return out


# ------------------------------------------------------------------ H6
def probe_h6() -> dict:
    table: dict = {}

    def remember(store: MemoryStore, text: str, **kw) -> dict:
        q = ib.enqueue(store, text)
        d = ib.drain_once(store, lock_deadline=kw.pop("deadline", 0.0), **kw)
        return {"enqueue": q["state"], "drain": {k: d.get(k) for k in ("state", "committed", "drain_error", "lock_busy", "outcome_unknown", "rejected", "outcome")}}

    project, store = fresh("h6a")
    table["1 comprometida"] = remember(store, "uno")
    pend = list((Path(store.root) / "inbox" / "pending").iterdir())
    table["1 comprometida"]["pending_tras"] = len(pend)
    # reintento idempotente: mismo texto
    r2 = remember(store, "uno")
    table["2 reintento del mismo texto"] = {**r2, "records_con_ese_texto": [r["text"] for r in store.snapshot(store.read_current()).records["facts"]].count("uno")}
    # candado ocupado
    project, store = fresh("h6b")
    holder = subprocess.Popen([PY, "-c", "import fcntl,sys,time\nf=open(sys.argv[1],'a+b');fcntl.flock(f,fcntl.LOCK_EX);print('ok',flush=True);time.sleep(3)", str(Path(store.root) / ".write.lock")], stdout=subprocess.PIPE, text=True)
    holder.stdout.readline()
    table["3 write_lock ocupado"] = remember(store, "dos")
    holder.wait()
    table["3 write_lock ocupado"]["pending_tras"] = len(list((Path(store.root) / "inbox" / "pending").iterdir()))
    # entrada insegura
    project, store = fresh("h6c")
    ib.Inbox(store).make()
    victim = Path(store.root) / "inbox" / "pending" / "1-1-0000000000000000-00000000.json"
    src = project / "x.json"
    src.write_text("{}")
    os.link(src, victim)
    table["4 entrada con hardlink"] = remember(store, "tres")
    # vaciado abortado por error de E/S al escribir segmentos
    project, store = fresh("h6d")
    with patch.object(MemoryStore, "_write_segment", side_effect=OSError("injected-segment")):
        table["5 E/S falla antes de CURRENT"] = remember(store, "cuatro")
    table["5 E/S falla antes de CURRENT"]["pending_tras"] = len(list((Path(store.root) / "inbox" / "pending").iterdir()))
    table["5 E/S falla antes de CURRENT"]["marcadores_tras"] = len(list((Path(store.root) / "inbox" / "inflight").iterdir()))
    again = ib.drain_once(store)
    table["5 E/S falla antes de CURRENT"]["siguiente_drain"] = again.get("state")
    # outcome_unknown: CURRENT se reemplaza y después no se puede releer
    project, store = fresh("h6e")
    original = store._replace_current
    state = {"broken": False}

    def replace_then_break(identifier: str) -> None:
        original(identifier)
        state["broken"] = True

    real_read = store.read_current

    def read_current() -> str:
        if state["broken"]:
            raise OSError("injected-reread")
        return real_read()

    q = ib.enqueue(store, "cinco")
    with patch.object(store, "_replace_current", replace_then_break), patch.object(store, "read_current", read_current):
        # drain_once vuelve a envolver _replace_current; se inyecta tras instalar los cortes
        d = ib.drain_once(store)
    store2 = MemoryStore(str(project))
    table["6 CURRENT escrito y no releíble"] = {"drain": {k: d.get(k) for k in ("state", "drain_error", "outcome_unknown", "outcome")},
                                               "marcadores_tras": len(list((Path(store.root) / "inbox" / "inflight").iterdir())),
                                               "pending_tras": len(list((Path(store.root) / "inbox" / "pending").iterdir()))}
    again = ib.drain_once(store2)
    table["6 CURRENT escrito y no releíble"]["siguiente_drain"] = {k: again.get(k) for k in ("state", "drain_error", "closed")}
    table["6 CURRENT escrito y no releíble"]["records_con_ese_texto"] = [r["text"] for r in store2.snapshot(store2.read_current()).records["facts"]].count("cinco")
    # decisión skip: autoridad que la política no admite (representación `full` bajo model_derived)
    project, store = fresh("h6f")
    base = store.read_current()
    proposal, authority, _, _ = ib.build_batch(base, [{"key": "a" * 64, "text": "seis"}])
    proposal["requested_representation"] = "full"
    authority["proposal_sha256"] = digest_json(proposal)
    authority["scope"]["representations"] = ["full"]
    decision = evaluate_write(proposal, authority)
    table["7 decisión skip"] = {"decision": decision["decision"], "reason_codes": decision["reason_codes"]}
    return table


# ------------------------------------------------------------------ H7
def probe_h7() -> dict:
    out: dict = {}
    project, store = fresh("h7")
    inbox = ib.Inbox(store)
    inbox.make()
    name = "1-1-aaaaaaaaaaaaaaaa-bbbbbbbb.json"
    for mode in ("replace", "lstat", "link"):
        for f in list(inbox.pending.iterdir()) + list(inbox.tmp.iterdir()):
            f.unlink()
        (inbox.pending / name).write_text("VICTIMA-LEGITIMA")
        try:
            r = ib.enqueue(store, "intruso", publish_mode=mode, name=name, preflight=False)
            err = None
        except Exception as exc:  # noqa: BLE001
            r, err = None, f"{type(exc).__name__} errno={getattr(exc, 'errno', None)}"
        out[f"nombre plantado, modo {mode}"] = {
            "pending_contiene": (inbox.pending / name).read_text()[:20],
            "tmp_restante": sorted(p.name for p in inbox.tmp.iterdir()), "error": err,
            "sobrescribio_en_silencio": (inbox.pending / name).read_text() != "VICTIMA-LEGITIMA"}
    # errores de FS simulados
    for label, target, code in (("EXDEV en os.replace", "os.replace", errno.EXDEV),
                                ("ENOSPC en os.replace", "os.replace", errno.ENOSPC),
                                ("EXDEV en os.link", "os.link", errno.EXDEV),
                                ("ENOSPC en os.link", "os.link", errno.ENOSPC)):
        for f in list(inbox.pending.iterdir()) + list(inbox.tmp.iterdir()):
            f.unlink()
        mode = "link" if "link" in target else "replace"
        with patch(target, side_effect=OSError(code, os.strerror(code))):
            try:
                ib.enqueue(store, "x", publish_mode=mode, preflight=False)
                err = None
            except OSError as exc:
                err = f"OSError errno={exc.errno}"
        out[label + " (simulado)"] = {"error": err, "pending": len(list(inbox.pending.iterdir())),
                                      "tmp_restante": len(list(inbox.tmp.iterdir()))}
    # carrera del modo link con el filtro st_nlink == 1 del vaciado (G1 de r3)
    import threading
    stop = threading.Event()
    seen = {"nlink2": 0, "samples": 0}

    def watcher() -> None:
        while not stop.is_set():
            for entry in os.scandir(inbox.pending):
                try:
                    n = os.lstat(entry.path).st_nlink
                except FileNotFoundError:
                    continue
                seen["samples"] += 1
                if n != 1:
                    seen["nlink2"] += 1

    for mode in ("link", "replace"):
        seen.update(nlink2=0, samples=0)
        stop.clear()
        t = threading.Thread(target=watcher)
        t.start()
        for k in range(1500):
            ib.enqueue(store, f"race-{mode}-{k}", publish_mode=mode, preflight=False)
        stop.set()
        t.join()
        out[f"lstat concurrente a 1500 encolados, modo {mode}"] = dict(seen)
        for f in inbox.pending.iterdir():
            f.unlink()
    # coste (500 encolados por modo, con fsync real)
    for mode in ("replace", "lstat", "link"):
        lat = []
        for k in range(500):
            r = ib.enqueue(store, f"{mode}-{k}", publish_mode=mode, preflight=False)
            lat.append(r["elapsed"] * 1000)
        lat.sort()
        out[f"coste {mode}"] = {"p50_ms": round(statistics.median(lat), 3), "p95_ms": round(lat[474], 3)}
        for f in inbox.pending.iterdir():
            f.unlink()
    return out


# ------------------------------------------------------------------ H8 + tmp
def probe_h8() -> dict:
    out: dict = {}
    # export real de main hoy con archivos de bandeja presentes
    project, store = fresh("h8")
    ib.enqueue(store, "pendiente")
    bundle = BASE / "h8-bundle"
    shutil.rmtree(bundle, ignore_errors=True)
    r = subprocess.run([PY, "-m", "an_kla", "--project-root", str(project), "export", "create", "--bundle", str(bundle)],
                       env=ENV, capture_output=True, text=True)
    out["export create de main con memory/inbox/pending/ no vacío"] = (r.returncode, (r.stdout + r.stderr)[-300:])
    # estados alcanzables por kill -9 con pending vacío y marcador vivo
    states = Counter()
    for point in ("post_journal", "mid_delete", "post_entries_deleted"):
        project, store = cut_state("h8-" + point, point, n=1)
        root = Path(store.root)
        inbox = root / "inbox"
        txid = next(inbox.joinpath("inflight").glob("*.json"), None)
        stage = journal_stage(store, txid.stem) if txid else None
        info = tx.inspect_transaction(store, txid.stem) if txid else {}
        states[(point, len(list((inbox / "pending").iterdir())), len(list((inbox / "inflight").iterdir())), stage, info.get("committed"))] += 1
    out["estados_tras_corte (punto, pending, inflight, stage del journal, committed)"] = [list(k) + [v] for k, v in states.items()]
    # regla propuesta
    def quiescent(store: MemoryStore) -> str | None:
        ibx = ib.Inbox(store)
        with ib.inbox_lock(ibx, exclusive=True, deadline=0.0) as got:
            if not got:
                return "inbox_busy"
            if any(NAME_OK(p) for p in ibx.pending.iterdir()):
                return "inbox_pending"
            if any(ibx.inflight.iterdir()):
                return "inbox_inflight"
        return None

    NAME_OK = lambda p: ib.NAME_RE.match(p.name) is not None  # noqa: E731
    project, store = cut_state("h8-rule", "post_entries_deleted", n=1)
    out["regla: pending vacío + marcador vivo"] = quiescent(store)
    r = worker("drain", str(project))
    out["regla: tras un drain (paso 0 borra el marcador)"] = quiescent(MemoryStore(str(project)))
    return out


def probe_tmp() -> dict:
    out: dict = {}
    project, store = fresh("tmp")
    ibx = ib.Inbox(store)
    ibx.make()
    # huérfano real: encolador muerto con kill -9 en (i)
    worker("enqueue1", str(project), "huerfano", env={"SPIKE_CUT": "enq_tmp"})
    out["tmp tras kill -9 en (i)"] = len(list(ibx.tmp.iterdir()))
    out["pending tras kill -9 en (i)"] = len(list(ibx.pending.iterdir()))
    # (a) recolector por candado, con un encolador VIVO retenido
    holder = subprocess.Popen([PY, "-c", "import fcntl,sys,time\nf=open(sys.argv[1],'a+b');fcntl.flock(f,fcntl.LOCK_SH);print('ok',flush=True);time.sleep(2)", str(ibx.lock_path)], stdout=subprocess.PIPE, text=True)
    holder.stdout.readline()
    live = ibx.tmp / "vivo.json"
    live.write_text("encolado en vuelo")
    out["por candado, con encolador vivo"] = {"borrados": ib.collect_tmp_by_lock(ibx), "tmp": len(list(ibx.tmp.iterdir()))}
    holder.wait()
    out["por candado, sin encoladores"] = {"borrados": ib.collect_tmp_by_lock(ibx), "tmp": len(list(ibx.tmp.iterdir()))}
    # (b) por antigüedad: carrera con un encolado vivo que se demora más que el umbral
    f = ibx.tmp / "demorado.json"
    f.write_text("x")
    old = time.time() - 120
    os.utime(f, (old, old))
    removed = ib.collect_tmp_by_age(ibx, 60.0)
    try:
        os.replace(f, ibx.pending / "demorado.json")
        race = "publicado"
    except FileNotFoundError:
        race = "FileNotFoundError en os.replace: el encolado falla visible, sin entrada ni pérdida silenciosa"
    out["por antigüedad (umbral 60 s) con encolado demorado 120 s"] = {"borrados": removed, "resultado_del_encolador": race}
    return out


PROBES = {"h3": probe_h3, "h4": probe_h4, "h5": probe_h5, "h6": probe_h6, "h7": probe_h7, "h8": probe_h8, "tmp": probe_tmp}



def probe_lockhold() -> dict:
    """Tiempo con write_lock tomado por lote de hasta 250 entradas (1000 pendientes)."""
    project, store = fresh("lockhold")
    for k in range(1000):
        ib.enqueue(store, f"lh {k} quetzal memoria", preflight=False)
    holds, counts = [], []
    while True:
        d = ib.drain_once(store)
        if d["state"] == "idle":
            break
        holds.append(round(d["lock_hold"], 4))
        counts.append(d.get("committed"))
    return {"batches": counts, "lock_hold_s": holds, "max_s": max(holds),
            "pending_tras": len(list((Path(store.root) / "inbox" / "pending").iterdir())),
            "verify_ok": store.verify()["ok"], "revisions": store.snapshot(store.read_current()).manifest["revision"]}


PROBES["lockhold"] = probe_lockhold


if __name__ == "__main__":
    which, out = sys.argv[1], sys.argv[2]
    result = PROBES[which]()
    Path(out).write_text(json.dumps(result, indent=1, default=str, ensure_ascii=False))
    print(json.dumps(result, indent=1, default=str, ensure_ascii=False))
