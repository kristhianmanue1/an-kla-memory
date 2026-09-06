"""Read-only release availability check for AN-KLA.

This module never installs, replaces, or downgrades the package.  It queries a
public release index, caches the result, and returns an advisory record that
the caller may print to ``stderr`` (or ignore).  All network and filesystem
errors fail closed: a silent skip is always preferred to blocking the CLI.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import os
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from .version import VERSION, is_newer_release, normalized_release_tag


RELEASE_INDEX_URL = (
    # ``/releases/latest`` excludes pre-releases by GitHub design, which would
    # make every beta invisible to the hook.  ``/releases?per_page=1`` returns
    # the most recent release regardless of pre-release flag.
    "https://api.github.com/repos/kristhianmanue1/an-kla-memory/releases?per_page=1"
)
INSTALL_HINT = (
    "git+https://github.com/kristhianmanue1/an-kla-memory.git"
)
CACHE_TTL_SECONDS = 24 * 60 * 60
HTTP_TIMEOUT_SECONDS = 3.0
USER_AGENT = f"an-kla-memory/{VERSION}"
OPT_OUT_ENV = "AN_KLA_NO_UPDATE_CHECK"
CI_ENV_VARS = ("CI", "GITHUB_ACTIONS", "AN_KLA_DISABLE_UPDATE_CHECK")

_CHECK_SCHEMA = "an-kla/update-check-v1"


class UpdateCheckError(RuntimeError):
    """Internal error type; never raised across the public API."""


@dataclass(frozen=True)
class UpdateNotice:
    schema: str
    status: str
    installed_version: str
    latest_release_tag: str | None
    cache_path: str
    seconds_until_next_check: int
    notice: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "status": self.status,
            "installed_version": self.installed_version,
            "latest_release_tag": self.latest_release_tag,
            "cache_path": self.cache_path,
            "seconds_until_next_check": self.seconds_until_next_check,
            "notice": self.notice,
        }


def _cache_path() -> Path:
    """Resolve a per-user cache path honoring XDG when present."""

    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        base = Path(xdg) / "an-kla"
    elif os.name == "nt":
        local_app = os.environ.get("LOCALAPPDATA")
        base = Path(local_app) / "an-kla" if local_app else Path.home() / ".cache" / "an-kla"
    else:
        base = Path.home() / ".cache" / "an-kla"
    return base / "update-check.json"


def _load_cache(path: Path) -> dict[str, Any] | None:
    try:
        payload = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        value = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    return value


def _store_cache(path: Path, value: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        # Caching is a best-effort optimization, never a critical path.
        pass


def _skip_environment() -> str | None:
    for name in CI_ENV_VARS:
        if os.environ.get(name, "").lower() in {"1", "true", "yes"}:
            return name
    if os.environ.get(OPT_OUT_ENV, "").lower() in {"1", "true", "yes"}:
        return OPT_OUT_ENV
    return None


def _fetch_latest_release() -> dict[str, Any] | None:
    request = Request(RELEASE_INDEX_URL, headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            payload = response.read()
    except (URLError, OSError, TimeoutError):
        return None
    except Exception:
        # urllib can raise unexpected exceptions for malformed responses; treat
        # any of them as a soft failure so the CLI never crashes on a check.
        return None
    try:
        value = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    # ``/releases?per_page=1`` returns a list; ``/releases/latest`` returned
    # an object.  Normalize to the single most recent release object.
    if isinstance(value, list):
        if not value:
            return None
        value = value[0]
    if not isinstance(value, dict):
        return None
    tag = value.get("tag_name")
    if not isinstance(tag, str) or not tag.startswith("v"):
        return None
    try:
        normalized_release_tag(tag)
    except ValueError:
        return None
    return value


def _build_notice(installed: str, latest_tag: str, html_url: str | None) -> str:
    install_command = (
        f'python -m pip install --upgrade "an-kla-memory@{INSTALL_HINT}@{latest_tag}"'
    )
    see_release = f" Ver: {html_url}" if html_url else ""
    # Issue #116/G1: el aviso apunta también al flujo completo de
    # actualización — instalar el paquete es sólo el primer paso; el
    # contexto gestionado se actualiza aparte (context plan/update).
    return (
        f"an-kla-memory {installed}: hay una versión más reciente ({latest_tag})."
        f" Actualiza con:\n  {install_command}{see_release}\n"
        f"  (AN-KLA no se actualiza a sí mismo; ejecuta el comando manualmente.)\n"
        f"  (Proyecto con contexto gestionado: tras instalar, sigue el flujo"
        f" `context plan --operation update` — docs/uso-diario.md"
        f" #actualizar-desde-otra-beta.)"
    )


def check_for_update(
    *,
    force: bool = False,
    cache_path: Path | None = None,
) -> UpdateNotice:
    """Return an advisory update notice without ever mutating the package.

    ``force`` bypasses the cache and the CI/opt-out skip checks except for
    network failures (which always fail closed).  It is intended for the
    explicit ``check-updates`` subcommand, not for the implicit startup hook.
    """

    import time

    cache = cache_path if cache_path is not None else _cache_path()
    schema = _CHECK_SCHEMA

    if not force:
        skipped = _skip_environment()
        if skipped is not None:
            return UpdateNotice(
                schema=schema,
                status=f"skipped_by_env:{skipped}",
                installed_version=VERSION,
                latest_release_tag=None,
                cache_path=str(cache),
                seconds_until_next_check=CACHE_TTL_SECONDS,
                notice=None,
            )

        cached = _load_cache(cache)
        if isinstance(cached, dict):
            now = time.time()
            fetched_at = float(cached.get("fetched_at", 0.0) or 0.0)
            cached_tag = cached.get("latest_release_tag")
            age = now - fetched_at
            if age < CACHE_TTL_SECONDS and isinstance(cached_tag, str):
                seconds_left = max(0, int(CACHE_TTL_SECONDS - age))
                notice_text: str | None = None
                latest_tag = cached_tag
                if is_newer_release(latest_tag, VERSION):
                    notice_text = _build_notice(VERSION, latest_tag, cached.get("html_url"))
                return UpdateNotice(
                    schema=schema,
                    status="cached",
                    installed_version=VERSION,
                    latest_release_tag=latest_tag,
                    cache_path=str(cache),
                    seconds_until_next_check=seconds_left,
                    notice=notice_text,
                )

    release = _fetch_latest_release()
    if release is None:
        return UpdateNotice(
            schema=schema,
            status="fetch_failed",
            installed_version=VERSION,
            latest_release_tag=None,
            cache_path=str(cache),
            seconds_until_next_check=CACHE_TTL_SECONDS,
            notice=None,
        )

    latest_tag = str(release["tag_name"])
    html_url = release.get("html_url")
    _store_cache(
        cache,
        {
            "schema": schema,
            "fetched_at": time.time(),
            "installed_version_at_fetch": VERSION,
            "latest_release_tag": latest_tag,
            "html_url": html_url,
        },
    )
    notice_text = (
        _build_notice(VERSION, latest_tag, html_url)
        if is_newer_release(latest_tag, VERSION)
        else None
    )
    return UpdateNotice(
        schema=schema,
        status="fresh",
        installed_version=VERSION,
        latest_release_tag=latest_tag,
        cache_path=str(cache),
        seconds_until_next_check=CACHE_TTL_SECONDS,
        notice=notice_text,
    )


__all__ = [
    "INSTALL_HINT",
    "OPT_OUT_ENV",
    "RELEASE_INDEX_URL",
    "UpdateNotice",
    "check_for_update",
]
