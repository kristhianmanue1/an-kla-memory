"""CLI of the anchors (ADR-0066): ``remember --anchor-*``, ``dispute`` and ``anchors verify``.

Parsers and dispatch live here so ``cli_parser`` and ``__main__`` only gain a hook.  The input is data:
a JSON list of anchors or repeatable ``--anchor-path`` / ``--anchor-quote`` / ``--anchor-commit`` groups
(without ``--anchor-commit`` a ``fact`` or ``decision`` takes the current ``HEAD`` and a ``state`` leaves
``commit: null``).  ``repo`` and ``session`` are filled by the tool from C0.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, BinaryIO

from .anchors_read import DEFAULT_ANCHOR_LIMIT, verify_command
from .inbox_anchors import VERDICTS
from .inbox_ops import target_exists
from .remember import RememberError, read_text_file, remember

MAX_ANCHOR_INPUT_BYTES = 1024 * 1024
HEAD = "HEAD"  # the shortcut's default; ``inbox_anchors.fill_anchor`` resolves it per record type
_FIELDS = {"--anchor-path": "path", "--anchor-quote": "quote", "--anchor-commit": "commit"}


class _AnchorGroup(argparse.Action):
    """Collect ``--anchor-path/-quote/-commit`` into ordered groups: a flag fills the open group or opens a new one."""

    def __call__(self, parser: Any, namespace: Any, values: Any, option_string: Any = None) -> None:
        groups = list(getattr(namespace, "anchor_groups", None) or [])
        field = _FIELDS[option_string]
        if not groups or field in groups[-1]:
            groups.append({})
        groups[-1][field] = values
        namespace.anchor_groups = groups


def add_anchor_arguments(command: Any) -> None:
    command.add_argument(
        "--anchor-file", metavar="RUTA", default=None,
        help="Anclas de C3: lista JSON de 0 a 16 objetos memoria/ancla/v1 (o '-' para stdin; no a la vez que --text-file -). "
        "repo y session los pone la herramienta.",
    )
    command.add_argument("--anchor-path", action=_AnchorGroup, metavar="P", help="Atajo: ruta relativa del archivo citado (repetible, en grupo con --anchor-quote).")
    command.add_argument("--anchor-quote", action=_AnchorGroup, metavar="Q", help="Atajo: cita literal de 8 a 300 bytes (40 mínimo en un document).")
    command.add_argument(
        "--anchor-commit", action=_AnchorGroup, metavar="C",
        help="Atajo: commit completo en que se observó la cita (por defecto HEAD para fact y decision; null para state).",
    )


def add_parsers(sub: Any, remember_cmd: Any) -> None:
    add_anchor_arguments(remember_cmd)
    dispute_cmd = sub.add_parser(
        "dispute",
        help="Registrar un dictamen externo sobre un registro (ADR-0066): disputa nativa; escribe en el store.",
        description=(
            "Guarda un dictamen (contradicted o insufficient) como disputa de <id> con la forma de ADR-0063 D3. "
            "El objetivo sigue vigente: nunca se sustituye ni se jubila (tampoco un state). supported y not_reviewed "
            "se quedan en el libro de quien juzga. No exige juez medido: el dictamen es dato no confiable. "
            "Misma salida y rc que remember."
        ),
    )
    dispute_cmd.add_argument("target", metavar="ID", help="Id del registro dictaminado.")
    dispute_cmd.add_argument("--verdict", required=True, help="contradicted o insufficient.")
    text = dispute_cmd.add_mutually_exclusive_group(required=True)
    text.add_argument("--text", help="Texto del dictamen. Visible en argv: prefiere --text-file -.")
    text.add_argument("--text-file", help="Archivo con el texto, o '-' para stdin.")
    dispute_cmd.add_argument("--idempotency-key", metavar="K", default=None, help="Como en remember.")
    add_anchor_arguments(dispute_cmd)
    anchors_cmd = sub.add_parser("anchors", help="Anclas de C3 (ADR-0066), sólo lectura.")
    anchors_sub = anchors_cmd.add_subparsers(dest="anchors_command", required=True)
    verify_cmd = anchors_sub.add_parser(
        "verify", help="Volver a comprobar las anclas de un registro, o de todos los vigentes con --all (auditoría)."
    )
    verify_cmd.add_argument("id", nargs="?", default=None, help="Id del registro; no con --all.")
    verify_cmd.add_argument("--all", action="store_true", help="Todos los registros vigentes con anclas, en orden determinista.")
    verify_cmd.add_argument(
        "--anchor-limit", type=int, default=DEFAULT_ANCHOR_LIMIT, metavar="N",
        help=f"Anclas comprobadas como máximo (por defecto {DEFAULT_ANCHOR_LIMIT}); el resto sale unverified con anchor_limit.",
    )


def _read_anchor_input(path: str, stdin: BinaryIO | None = None) -> Any:
    try:
        if path == "-":
            raw = (stdin if stdin is not None else sys.stdin.buffer).read(MAX_ANCHOR_INPUT_BYTES + 1)
        else:
            with open(path, "rb") as handle:
                raw = handle.read(MAX_ANCHOR_INPUT_BYTES + 1)
    except OSError:
        raise RememberError("anchor_input_invalid", "no se pudo leer el archivo de anclas") from None
    if len(raw) > MAX_ANCHOR_INPUT_BYTES:
        raise RememberError("anchor_input_invalid", "el archivo de anclas es demasiado grande")
    try:
        return json.loads(raw)
    except (ValueError, RecursionError):
        raise RememberError("anchor_input_invalid", "JSON mal formado") from None


def anchors_from_args(args: Any) -> list[dict[str, Any]] | None:
    """The anchors a command asked for, or ``None``; malformed input is ``anchor_input_invalid`` (nothing queued)."""

    given: list[Any] = []
    if getattr(args, "anchor_file", None) is not None:
        if args.anchor_file == "-" and getattr(args, "text_file", None) == "-":
            raise RememberError("anchor_input_invalid", "stdin sólo puede ser del texto o de las anclas")
        loaded = _read_anchor_input(args.anchor_file)
        if not isinstance(loaded, list) or not all(isinstance(item, dict) for item in loaded):
            raise RememberError("anchor_input_invalid", "se espera una lista JSON de objetos")
        given.extend(loaded)
    for group in getattr(args, "anchor_groups", None) or []:
        if "path" not in group or "quote" not in group:
            raise RememberError("anchor_input_invalid", "cada ancla del atajo lleva --anchor-path y --anchor-quote")
        given.append({
            "source": {"kind": "repo-file", "path": group["path"], "commit": group.get("commit", HEAD)},
            "quote": group["quote"],
        })
    return given or None


def run(store: Any, args: Any) -> dict[str, Any]:
    """``dispute`` or ``anchors verify``."""

    if args.command == "anchors":
        return verify_command(store, args)
    if args.verdict not in VERDICTS:
        raise RememberError("dispute_verdict_invalid", "contradicted o insufficient; supported y not_reviewed no entran en el store")
    if not target_exists(store, args.target):
        raise RememberError("dispute_target_missing", "el registro dictaminado no existe en el store")
    text = args.text if args.text_file is None else read_text_file(args.text_file)
    return remember(
        store, text, kind="fact", supersedes=args.target, idempotency_key=args.idempotency_key,
        anchors=anchors_from_args(args), verdict=args.verdict, operation="dispute",
    )
