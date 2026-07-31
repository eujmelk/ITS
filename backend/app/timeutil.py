"""Service-day time handling.

Transit times are stored as **integer seconds since the start of the service
day**, not as SQL ``TIME`` values. This is deliberate: a trip that departs at
00:35 as part of Tuesday's service is "25:35:00" on the Tuesday service day,
and a ``TIME`` column cannot represent that. Every duration/ordering
comparison in the block and duty validators depends on it.

The API surface exposes these as ``"HH:MM:SS"`` strings; the ``TimeStr``
annotated type below does the conversion in both directions so that routers
and services only ever deal with integers.
"""

from typing import Annotated, Any

from pydantic import BeforeValidator, PlainSerializer, WithJsonSchema

SECONDS_PER_DAY = 86_400
# Guard rail: a service day may legitimately run past midnight, but never
# past 48h. Anything beyond that is a data-entry error, not a late trip.
MAX_SERVICE_SECONDS = 2 * SECONDS_PER_DAY


class TimeParseError(ValueError):
    pass


def parse_time(value: Any) -> int:
    """Accept ``"HH:MM"``, ``"HH:MM:SS"`` or a raw int, return seconds."""
    if value is None:
        raise TimeParseError("time is required")
    if isinstance(value, bool):
        raise TimeParseError("invalid time value")
    if isinstance(value, int):
        seconds = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise TimeParseError("time is required")
        if text.isdigit():
            seconds = int(text)
        else:
            parts = text.split(":")
            if len(parts) not in (2, 3):
                raise TimeParseError(f"expected HH:MM or HH:MM:SS, got {value!r}")
            try:
                nums = [int(p) for p in parts]
            except ValueError:
                raise TimeParseError(f"expected HH:MM or HH:MM:SS, got {value!r}") from None
            hours, minutes = nums[0], nums[1]
            secs = nums[2] if len(nums) == 3 else 0
            if hours < 0 or not (0 <= minutes < 60) or not (0 <= secs < 60):
                raise TimeParseError(f"out-of-range time {value!r}")
            seconds = hours * 3600 + minutes * 60 + secs
    else:
        raise TimeParseError(f"cannot interpret {type(value).__name__} as a time")

    if not 0 <= seconds <= MAX_SERVICE_SECONDS:
        raise TimeParseError(
            f"time {value!r} is outside the service day (00:00:00 - 48:00:00)"
        )
    return seconds


def format_time(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    hours, rem = divmod(int(seconds), 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_hhmm(seconds: int | None) -> str | None:
    """Shorter form used on printed timetables."""
    if seconds is None:
        return None
    hours, rem = divmod(int(seconds), 3600)
    minutes = rem // 60
    return f"{hours % 24:02d}:{minutes:02d}"


def _serialize(value: int | None) -> str | None:
    return format_time(value)


TimeStr = Annotated[
    int,
    BeforeValidator(parse_time),
    PlainSerializer(_serialize, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "examples": ["08:15:00", "25:10:00"]}),
]
"""Required service-day time. JSON in/out is ``"HH:MM:SS"``, Python is int."""


def _parse_optional(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return parse_time(value)


OptionalTimeStr = Annotated[
    int | None,
    BeforeValidator(_parse_optional),
    PlainSerializer(_serialize, return_type=str | None, when_used="json"),
    WithJsonSchema({"type": ["string", "null"], "examples": ["08:15:00"]}),
]
"""Nullable variant of :data:`TimeStr`."""
