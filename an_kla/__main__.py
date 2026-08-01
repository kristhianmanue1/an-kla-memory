"""Command-line interface for the AN-KLA alpha."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .canonical import canonical_json
from .context import assemble_context
from .index import INDEX_PROFILE, build_index, detect_fts5, verify_index_deep
from .evaluation import evaluate_retrieval
from .retrieval import SCAN_PROFILE, retrieve
from .store import ConcurrentUpdateError, MemoryStore, StoreError


def _json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _cli_authority(value: Any) -> Any:
    """Fail closed when a JSON file claims authority the CLI cannot resolve."""

    if isinstance(value, dict) and value.get("authority_class") in {
        "tool_observed",
        "channel_confirmed",
    }:
        raise ValueError("cli_privileged_authority_unresolved")
    return value


def _planning_result(value: Any) -> tuple[Any, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "current_revision", "decision", "plan"}
        or value.get("schema") != "an-kla/write-planning-result-v1"
    ):
        raise ValueError("invalid_write_planning_result")
    return value["decision"], value["plan"]


def main() -> None:
    parser = argparse.ArgumentParser(description="AN-KLA Memory alpha")
    parser.add_argument("--project-root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("status")
    sub.add_parser("verify")
    doctor_cmd = sub.add_parser("doctor")
    doctor_cmd.add_argument("--deep-index", action="store_true")
    sub.add_parser("recover")
    index_cmd = sub.add_parser("rebuild-index")
    index_cmd.add_argument("--revision", default=None)
    retrieve_cmd = sub.add_parser("retrieve")
    retrieve_cmd.add_argument("--query", required=True)
    retrieve_cmd.add_argument("--budget", type=int, required=True)
    retrieve_cmd.add_argument(
        "--profile", choices=(SCAN_PROFILE, INDEX_PROFILE), default=SCAN_PROFILE
    )
    assemble_cmd = sub.add_parser("assemble-context")
    assemble_cmd.add_argument("--query", required=True)
    assemble_cmd.add_argument("--budget", type=int, required=True)
    assemble_cmd.add_argument("--new-information")
    evaluate_cmd = sub.add_parser("evaluate")
    evaluate_cmd.add_argument("--queries", required=True)
    evaluate_cmd.add_argument("--budget", type=int, required=True)
    write_cmd = sub.add_parser(
        "write", help="API alfa heredada; omite write-policy/v1 y emite deprecación."
    )
    write_cmd.add_argument("--expected-current", required=True)
    write_cmd.add_argument("--checkpoint-patch", required=True)
    write_cmd.add_argument("--facts", default="")
    write_cmd.add_argument("--events", default="")
    write_cmd.add_argument("--episodes", default="")
    plan_write_cmd = sub.add_parser(
        "plan-write", help="Planificar sin mutar; autoridad privilegiada requiere adaptador externo."
    )
    plan_write_cmd.add_argument("--proposal", required=True)
    plan_write_cmd.add_argument("--authority", required=True)
    commit_plan_cmd = sub.add_parser(
        "commit-write-plan", help="Revalidar y escribir un plan exacto bajo el lock."
    )
    commit_plan_cmd.add_argument("--expected-current", required=True)
    commit_plan_cmd.add_argument("--proposal", required=True)
    commit_plan_cmd.add_argument("--authority", required=True)
    commit_plan_cmd.add_argument("--planning-result", required=True)
    args = parser.parse_args()
    store = MemoryStore(args.project_root)
    if args.command == "init":
        result: Any = {"revision": store.initialize()}
    elif args.command == "status":
        result = store.verify()
    elif args.command == "verify":
        result = store.verify()
    elif args.command == "doctor":
        result = {**store.doctor(), "fts5": detect_fts5(), "memory_exists": store.current_path.exists()}
        if args.deep_index:
            result["index_deep"] = verify_index_deep(store)
    elif args.command == "recover":
        result = store.recover()
    elif args.command == "rebuild-index":
        result = build_index(store, revision_id=args.revision)
    elif args.command == "retrieve":
        result = retrieve(store, args.query, args.budget, profile=args.profile)
    elif args.command == "assemble-context":
        result = assemble_context(
            store,
            args.query,
            args.budget,
            new_information=args.new_information,
        )
    elif args.command == "evaluate":
        result = evaluate_retrieval(store, args.queries, args.budget)
    elif args.command == "write":
        result = {
            "revision": store.commit(
                expected_current_hash=args.expected_current,
                checkpoint_patch=_json(args.checkpoint_patch),
                facts=_json(args.facts) if args.facts else (),
                events=_json(args.events) if args.events else (),
                episodes=_json(args.episodes) if args.episodes else (),
            ),
            "deprecation": "legacy_write_bypasses_write_policy",
        }
    elif args.command == "plan-write":
        result = store.plan_write(
            _json(args.proposal),
            _cli_authority(_json(args.authority)),
        )
    else:
        decision, plan = _planning_result(_json(args.planning_result))
        result = store.commit_write_plan(
            expected_current_hash=args.expected_current,
            proposal=_json(args.proposal),
            authority=_cli_authority(_json(args.authority)),
            decision=decision,
            plan=plan,
        )
    if args.command == "assemble-context":
        sys.stdout.buffer.write(canonical_json(result))
    else:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (StoreError, ConcurrentUpdateError, ValueError, OSError) as exc:
        raise SystemExit(f"an-kla error: {exc}")
