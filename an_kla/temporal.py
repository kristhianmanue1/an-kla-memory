"""Pure temporal primitives for self-asserted record freshness."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Mapping


VERIFIED_AT_VALIDATOR = "an-kla-verified-at/v1"
FRESHNESS_PROFILE = "computed-age/v1"
FRESHNESS_SEMANTICS = "self_asserted_timestamp"
FRESHNESS_SOURCE_FIELD = "record.verified_at"
FRESHNESS_PROJECTION_KEYS = (
    "verified_at",
    "days_since_verified",
    "stale",
    "freshness_error",
)
MICROSECONDS_PER_DAY = 86_400_000_000

# Closed ISO-8601 subset from ADR-0021. ``-00:00`` is intentionally absent:
# it means an unknown offset, while this contract requires a known offset.
VERIFIED_AT_PATTERN = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?"
    r"(?:Z|\+(?:(?:0[0-9]|1[0-3]):[0-5][0-9]|14:00)"
    r"|-(?:00:(?:0[1-9]|[1-5][0-9])|(?:0[1-9]|1[0-3]):[0-5][0-9]|14:00))$"
)
_VERIFIED_AT = re.compile(VERIFIED_AT_PATTERN)


class TemporalError(ValueError):
    """Stable temporal validation failure for projection-layer mapping."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def parse_verified_at(text: str) -> datetime:
    """Parse the closed grammar and return a timezone-aware UTC datetime."""

    if not isinstance(text, str) or not _VERIFIED_AT.fullmatch(text):
        raise TemporalError("unparseable_verified_at")
    zone_width = 1 if text.endswith("Z") else 6
    body, zone = text[:-zone_width], text[-zone_width:]
    if "." in body:
        prefix, fraction = body.rsplit(".", 1)
        body = prefix + "." + fraction.ljust(6, "0")
    normalized = body + ("+00:00" if zone == "Z" else zone)
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.utcoffset() is None:
            raise TemporalError("unparseable_verified_at")
    except TemporalError:
        raise
    except (TypeError, ValueError) as exc:
        raise TemporalError("unparseable_verified_at") from exc
    try:
        return parsed.astimezone(timezone.utc)
    except (OverflowError, ValueError) as exc:
        raise TemporalError("unrepresentable_verified_at") from exc


def normalize_freshness_now(value: datetime) -> datetime:
    """Validate an injected clock value and normalize it to UTC."""

    if not isinstance(value, datetime):
        raise TemporalError("invalid_freshness_now")
    try:
        if value.utcoffset() is None:
            raise TemporalError("invalid_freshness_now")
        return value.astimezone(timezone.utc)
    except TemporalError:
        raise
    except (OverflowError, TypeError, ValueError) as exc:
        raise TemporalError("invalid_freshness_now") from exc


def parse_freshness_now(text: str) -> datetime:
    """Parse a CLI/MCP clock string and map all failures to its safe code."""

    if not isinstance(text, str):
        raise TemporalError("invalid_freshness_now")
    try:
        return parse_verified_at(text)
    except TemporalError as exc:
        raise TemporalError("invalid_freshness_now") from exc


def format_utc(value: datetime) -> str:
    """Format a valid datetime as canonical UTC with six fractional digits."""

    normalized = normalize_freshness_now(value)
    return (
        f"{normalized.year:04d}-{normalized.month:02d}-{normalized.day:02d}T"
        f"{normalized.hour:02d}:{normalized.minute:02d}:{normalized.second:02d}."
        f"{normalized.microsecond:06d}Z"
    )


def validate_stale_after_days(value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TemporalError("invalid_stale_after_days")
    return value


def compute_freshness(
    verified_at: Any,
    now: datetime,
    stale_after_days: int | None = None,
) -> dict[str, Any]:
    """Project temporal metadata without mutating, ranking or excluding data."""

    computed_at = normalize_freshness_now(now)
    threshold = validate_stale_after_days(stale_after_days)
    if not isinstance(verified_at, str):
        return {}
    projection: dict[str, Any] = {"verified_at": verified_at}
    try:
        verified = parse_verified_at(verified_at)
    except TemporalError as exc:
        projection["freshness_error"] = exc.code
        return projection
    delta = computed_at - verified
    micros = (
        (delta.days * 86_400 + delta.seconds) * 1_000_000
        + delta.microseconds
    )
    complete_days = abs(micros) // MICROSECONDS_PER_DAY
    days = -complete_days if micros < 0 else complete_days
    projection["days_since_verified"] = days
    if threshold is not None and days > threshold:
        projection["stale"] = True
    return projection


def project_record_freshness(
    record: Mapping[str, Any],
    now: datetime,
    stale_after_days: int | None = None,
) -> dict[str, Any]:
    """Project freshness from an open record without interpreting other keys."""

    return compute_freshness(record.get("verified_at"), now, stale_after_days)


def summarize_freshness(items: list[dict[str, Any]]) -> dict[str, int]:
    """Count freshness states over the final selected population (ADR-0037).

    ``items`` are selected retrieval items already carrying the projected
    freshness keys.  States are total and mutually exclusive:
    ``evaluated`` (``days_since_verified`` present), ``not_evaluable``
    (no ``verified_at``), ``unparseable`` (``freshness_error`` present).
    ``stale`` counts items flagged stale and is a subset of
    ``evaluated``.
    """

    evaluated = 0
    not_evaluable = 0
    unparseable = 0
    stale = 0
    for item in items:
        if item.get("freshness_error") is not None:
            unparseable += 1
        elif "days_since_verified" in item:
            evaluated += 1
            if item.get("stale") is True:
                stale += 1
        else:
            not_evaluable += 1
    return {
        "evaluated": evaluated,
        "not_evaluable": not_evaluable,
        "unparseable": unparseable,
        "stale": stale,
    }


__all__ = [
    "FRESHNESS_PROFILE",
    "FRESHNESS_PROJECTION_KEYS",
    "FRESHNESS_SEMANTICS",
    "FRESHNESS_SOURCE_FIELD",
    "TemporalError",
    "VERIFIED_AT_PATTERN",
    "VERIFIED_AT_VALIDATOR",
    "compute_freshness",
    "format_utc",
    "normalize_freshness_now",
    "parse_freshness_now",
    "parse_verified_at",
    "project_record_freshness",
    "summarize_freshness",
    "validate_stale_after_days",
]
