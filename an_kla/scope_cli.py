"""CLI del ámbito (ADR-0069): ``remember --subject/--audience/--valid-until/--until-revoked/--revoke`` y, en las lecturas,
``--subject`` y ``--include-other-audience``. Los parsers y los argumentos viven aquí para que ``cli_parser`` y
``__main__`` sólo ganen un gancho."""

from __future__ import annotations

from typing import Any, Callable

from .audience import Reader, is_subject, make_reader

SUBJECT_HELP = "repo.id de C0 canónico del proyecto del que trata el recuerdo (host[:puerto]/ruta, local:|remoto:<16 hex>)."


def add_arguments(remember_cmd: Any, retrieve_cmd: Any, list_cmd: Any, state_show_cmd: Any) -> None:
    remember_cmd.add_argument("--subject", metavar="REPO_ID", default=None, help=SUBJECT_HELP + " Obligatorio en --kind directive.")
    remember_cmd.add_argument(
        "--audience", metavar="A", default=None,
        help="Para quién es: all, role:<papel> o agent:<nombre>. Obligatorio en --kind directive (ADR-0069).",
    )
    remember_cmd.add_argument(
        "--valid-until", metavar="FECHA", default=None,
        help="Sólo --kind directive: AAAA-MM-DD (vale hasta el final de ese día, UTC) o AAAA-MM-DDTHH:MM:SSZ.",
    )
    remember_cmd.add_argument(
        "--until-revoked", action="store_true", help="Sólo --kind directive: vale hasta que otra directive la sustituya o revoque.",
    )
    remember_cmd.add_argument(
        "--revoke", action="store_true",
        help="Sólo --kind directive con --supersedes: el registro nuevo es el acta de la revocación y hereda subject y audience del destino.",
    )
    for command in (retrieve_cmd, list_cmd, state_show_cmd):
        command.add_argument(
            "--subject", metavar="REPO_ID", default=None,
            help="Proyecto del lector (repo.id de C0); por defecto el del checkout. Es una afirmación: sirve para filtrar, no prueba nada.",
        )
        command.add_argument(
            "--include-other-audience", action="store_true",
            help="Sirve también lo que es para otro (subject o audience), marcado con for_reader: false.",
        )


def reader_from_args(store: Any, args: Any, error: Callable[[], Exception]) -> Reader:
    """El lector de una lectura: identidad C0 del entorno y ``--subject`` (``error()`` si está mal formado)."""

    subject = getattr(args, "subject", None)
    if subject is not None and not is_subject(subject):
        raise error()
    return make_reader(store, subject=subject, include_other=bool(getattr(args, "include_other_audience", False)))


__all__ = ["add_arguments", "reader_from_args"]
