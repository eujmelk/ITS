"""Pattern attributes, and the few that GTFS knows about.

Most attributes are yours: ``TYPE=EXP``, ``via=Hospital``, whatever the
operation needs. They are internal — they print as bubbles on duty cards and
timetables, and GTFS has nowhere to put them, so they do not appear in an
exported feed.

A handful of keys, though, correspond to real GTFS fields on ``trips.txt``.
Those are reserved: their values are validated on write, so a feed cannot be
built with ``wheelchair_accessible=maybe`` in it, and they are exported into
the right column rather than being silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, status


@dataclass(frozen=True)
class GtfsAttribute:
    key: str
    #: Column this becomes in trips.txt.
    gtfs_field: str
    description: str
    #: Accepted input, lowercased, mapped to the GTFS enum value.
    values: dict[str, str]


#: GTFS uses 0 = no information, 1 = yes, 2 = no. Accepting the words people
#: actually type avoids a feed that fails validation over a spelling.
_YES_NO = {
    "yes": "1",
    "true": "1",
    "1": "1",
    "accessible": "1",
    "allowed": "1",
    "no": "2",
    "false": "2",
    "2": "2",
    "none": "2",
    "unknown": "0",
    "": "0",
    "0": "0",
}

GTFS_ATTRIBUTES: tuple[GtfsAttribute, ...] = (
    GtfsAttribute(
        "wheelchair_accessible",
        "wheelchair_accessible",
        "Whether trips on this pattern take a wheelchair. yes / no / unknown.",
        _YES_NO,
    ),
    GtfsAttribute(
        "bikes_allowed",
        "bikes_allowed",
        "Whether bicycles may be carried. yes / no / unknown.",
        _YES_NO,
    ),
)

GTFS_ATTRIBUTES_BY_KEY = {spec.key: spec for spec in GTFS_ATTRIBUTES}

#: Suggested keys for the UI. The GTFS ones first, since they do more.
SUGGESTED_KEYS = [spec.key for spec in GTFS_ATTRIBUTES] + [
    "TYPE",
    "SERVICE",
    "via",
    "peak_only",
    "school_days",
    "operator_notes",
]


def validate(attributes) -> None:
    """Reject values a reserved key cannot mean.

    Raised as a 422 so it reads as a validation error in the UI rather than
    surfacing later as a broken export.
    """
    for entry in attributes:
        key = (entry.attribute_key or "").strip()
        spec = GTFS_ATTRIBUTES_BY_KEY.get(key)
        if spec is None:
            continue
        raw = (entry.attribute_value or "").strip().lower()
        if raw not in spec.values:
            accepted = ", ".join(sorted({v for v in ("yes", "no", "unknown")}))
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"'{key}' is a GTFS field, so its value must be one of "
                f"{accepted} (got '{entry.attribute_value}'). Use a different "
                "key if you meant something else.",
            )


def gtfs_value(key: str, value: str | None) -> str | None:
    """Map an attribute onto its GTFS enum value, or None if not reserved."""
    spec = GTFS_ATTRIBUTES_BY_KEY.get(key)
    if spec is None:
        return None
    return spec.values.get((value or "").strip().lower(), "0")


def badge_values(attributes) -> list[str]:
    """Values printed as bubbles.

    Reserved GTFS keys are excluded: "yes" beside a line number tells a driver
    nothing, and the accessibility of the vehicle is not a service variant.
    """
    return [
        (a.attribute_value or "").strip()
        for a in sorted(attributes, key=lambda a: a.attribute_key)
        if (a.attribute_value or "").strip()
        and a.attribute_key not in GTFS_ATTRIBUTES_BY_KEY
    ]
