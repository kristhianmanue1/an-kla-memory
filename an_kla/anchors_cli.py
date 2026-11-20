"""CLI of the anchors (ADR-0066, ADR-0071): ``remember --anchor-*``, ``dispute`` and ``anchors verify``.

Parsers and dispatch live here so ``cli_parser`` and ``__main__`` only gain a hook.  The input is data:
a JSON list of anchors or repeatable ``--anchor-path`` / ``--anchor-quote`` / ``--anchor-commit`` groups
(without ``--anchor-commit`` a ``fact`` or ``decision`` takes the current ``HEAD`` and a ``state`` leaves
``commit: null``), or, for a ``document``, ``--anchor-document`` / ``--anchor-custodian`` / ``--anchor-derivation`` /
``--anchor-manifest`` / ``--anchor-modality`` / ``--anchor-page`` / ``--anchor-item`` (repeatable) / ``--anchor-copy`` /
``--anchor-quote`` groups.  ``repo`` and ``session`` (and a copy's ``repo``) are filled by the tool from C0.
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
_FIELDS = {
    "--anchor-path": "path", "--anchor-quote": "quote", "--anchor-commit": "commit",
    "--anchor-document": "document", "--anchor-custodian": "custodian", "--anchor-derivation": "derivation",
    "--anchor-manifest": "manifest", "--anchor-modality": "modality", "--anchor-page": "page",
    "--anchor-item": "item", "--anchor-copy": "copy",
}
_DOCUMENT_FIELDS = ("document", "custodian", "derivation", "manifest", "modality", "page", "item", "copy")


class _AnchorGroup(argparse.Action):
    """Collect the ``--anchor-*`` shortcuts into ordered groups: a flag fills the open group or opens a new one
    (``--anchor-item`` repeats inside a group: it accumulates, in the order given)."""

    def __call__(self, parser: Any, namespace: Any, values: Any, option_string: Any = None) -> None:
        groups = list(getattr(namespace, "anchor_groups", None) or [])
        field = _FIELDS[option_string]
        if field == "item" and groups and "item" in groups[-1]:
            groups[-1]["item"] = [*groups[-1]["item"], values]
        else:
            if not groups or field in groups[-1]:
                groups.append({})
            groups[-1][field] = [values] if field == "item" else values
        namespace.anchor_groups = groups


def add_anchor_arguments(command: Any) -> None:
    command.add_argument(
        "--anchor-file", metavar="RUTA", default=None,
        help="Anclas de C3: lista JSON de 0 a 16 objetos memoria/ancla/v1 o v2 (o '-' para stdin; no a la vez que --text-file -). "
        "repo y session (y el repo de la copia de un document) los pone la herramienta.",
    )
    for flag, metavar, text in (
        ("--anchor-document", "SHA256", "Atajo de un document: sha256 del documento (grupo con --anchor-custodian, --anchor-derivation, --anchor-manifest, --anchor-modality, --anchor-page y --anchor-quote)."),
        ("--anchor-custodian", "ID", "Atajo de un document: id del custodio ([a-z0-9][a-z0-9_-]{0,31}); su adaptador sale de la tabla `custodians` de la configuración."),
        ("--anchor-derivation", "ID", "Atajo de un document: derivation_id."),
        ("--anchor-manifest", "SHA256", "Atajo de un document: sha256 del manifiesto de la derivación."),
        ("--anchor-modality", "M", "Atajo de un document: native_text, ocr_text o visual (la de los elementos citados)."),
        ("--anchor-page", "N", "Atajo de un document: página física (1…N); sin ella no se escribe (anchor_locator_required)."),
        ("--anchor-item", "ID", "Atajo de un document: elemento de la página (repetible, en el orden del custodio); sin ninguno, toda la página."),
        ("--anchor-copy", "RUTA", "Atajo de un document: ruta relativa de la copia local, leída por Git de la rama por defecto."),
    ):
        command.add_argument(flag, action=_AnchorGroup, metavar=metavar, help=text)
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
        given.append(_document_group(group) if "document" in group else _repo_file_group(group))
    return given or None


def _repo_file_group(group: dict[str, Any]) -> dict[str, Any]:
    if "path" not in group or "quote" not in group or any(field in group for field in _DOCUMENT_FIELDS):
        raise RememberError("anchor_input_invalid", "cada ancla del atajo lleva --anchor-path y --anchor-quote")
    return {"source": {"kind": "repo-file", "path": group["path"], "commit": group.get("commit", HEAD)}, "quote": group["quote"]}


def _document_group(group: dict[str, Any]) -> dict[str, Any]:
    """A ``document`` anchor from its shortcut group (ADR-0071 §2); without ``--anchor-page`` there is no ``page`` and the
    write is refused later, in its order, as ``anchor_locator_required``."""
    needed = ("document", "custodian", "derivation", "manifest", "modality", "quote")
    if any(field not in group for field in needed) or "path" in group or "commit" in group:
        raise RememberError("anchor_input_invalid", "un document lleva --anchor-document, -custodian, -derivation, -manifest, -modality y -quote")
    locator: dict[str, Any] = {}
    if "page" in group:
        try:
            locator["page"] = int(group["page"])
        except ValueError:
            raise RememberError("anchor_input_invalid", "--anchor-page es un entero") from None
    items = group.get("item", [])
    if len(items) == 1:
        locator["item_id"] = items[0]
    elif items:
        locator["item_ids"] = list(items)
    source: dict[str, Any] = {
        "kind": "document", "document_sha256": group["document"],
        "derivation": {"custodian": group["custodian"], "derivation_id": group["derivation"],
                       "manifest_sha256": group["manifest"], "modality": group["modality"]},
        "locator": locator,
    }
    if "copy" in group:
        source["copy"] = {"repo": "", "path": group["copy"]}  # the repo is the project's, put by the tool from C0
    return {"source": source, "quote": group["quote"]}


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
