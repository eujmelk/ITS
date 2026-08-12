"""CSV import for locations.

Designed to round-trip the export: download `/csv/locations`, edit it in a
spreadsheet, upload it back. That means tolerating what spreadsheets actually
produce — a UTF-8 BOM, semicolon delimiters from a European Excel, comma
decimal separators, stray whitespace and inconsistent header casing.

Two passes. The first is a dry run that reports exactly what would happen to
every row without keeping any of it; only when the operator has seen that does
a second call commit. Each row runs inside its own savepoint, so one bad line
reports its own error instead of taking the whole file down with it.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.enums import LocationType
from app.models import FareZone, Location, LocationAttribute, StopArea

#: Columns the importer understands. Anything else is treated as a location
#: attribute, which is what makes the generic key/value model importable at
#: all -- the export writes one column per attribute key in use.
KNOWN_COLUMNS = {
    "id",
    "name",
    "code",
    "location_type",
    "type",
    "lat",
    "latitude",
    "lon",
    "lng",
    "longitude",
    "zone",
    "zone_id",
    "zone_code",
    "area",
    "area_id",
    "stop_area",
    "is_active",
    "active",
    "notes",
}

MAX_ROWS = 20_000

_TRUE = {"1", "true", "yes", "y", "t", "on", "x"}
_FALSE = {"0", "false", "no", "n", "f", "off"}


@dataclass
class RowResult:
    line: int
    action: str  # created | updated | skipped | failed
    name: str = ""
    code: str = ""
    location_id: int | None = None
    message: str = ""


@dataclass
class ImportReport:
    dry_run: bool = True
    delimiter: str = ","
    columns: list[str] = field(default_factory=list)
    attribute_columns: list[str] = field(default_factory=list)
    total: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    rows: list[RowResult] = field(default_factory=list)
    #: File-level problems that stopped anything being read at all.
    fatal: str | None = None

    @property
    def ok(self) -> bool:
        return self.fatal is None and self.failed == 0


class RowError(ValueError):
    """A problem with one row, reported rather than raised to the client."""


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------


def decode(payload: bytes) -> str:
    """Decode a spreadsheet's idea of a text file.

    ``utf-8-sig`` strips the BOM Excel writes (and that our own export writes,
    so accented stop names survive a round trip). Windows-1252 is the usual
    fallback when someone saved as "CSV" rather than "CSV UTF-8".
    """
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="replace")


def sniff_delimiter(text: str) -> str:
    """Comma or semicolon.

    A European Excel writes semicolons, and getting this wrong turns the whole
    file into a single unnamed column -- a confusing failure to debug from the
    other end, so it is worth guessing properly.
    """
    sample = text[:4096]
    header = sample.splitlines()[0] if sample.splitlines() else ""
    if header.count(";") > header.count(","):
        return ";"
    if header.count("\t") > header.count(","):
        return "\t"
    return ","


def normalise_header(name: str) -> str:
    return (name or "").strip().lstrip("﻿").lower().replace(" ", "_")


def _number(raw: str, label: str) -> float | None:
    text = (raw or "").strip()
    if not text:
        return None
    # A spreadsheet in a comma-decimal locale writes "52,3676".
    text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        raise RowError(f"{label} '{raw}' is not a number") from None


def _boolean(raw: str) -> bool:
    # Callers only reach this with a non-empty cell, because a blank means
    # "leave alone" and is filtered out before we get here.
    text = (raw or "").strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise RowError(f"'{raw}' is not a yes/no value")


def _pick(row: dict[str, str], *names: str) -> str:
    for name in names:
        if name in row and (row[name] or "").strip():
            return row[name].strip()
    return ""


# --------------------------------------------------------------------------
# Importing
# --------------------------------------------------------------------------


def run_import(
    db: Session,
    payload: bytes,
    dry_run: bool = True,
    replace_attributes: bool = False,
) -> ImportReport:
    """Import locations from CSV bytes.

    Matching, in order: ``id`` if given, then ``code``. A row that matches is
    updated; one that matches nothing is created. An ``id`` that does not
    exist is an error rather than an insert -- a mistyped id should not
    quietly become a new stop.

    Blank cells mean "leave alone" on update, so a partial spreadsheet with
    only ``code`` and ``lat``/``lon`` is a safe way to add coordinates in bulk.
    """
    report = ImportReport(dry_run=dry_run)

    text = decode(payload)
    if not text.strip():
        report.fatal = "The file is empty."
        return report

    report.delimiter = sniff_delimiter(text)
    reader = csv.DictReader(io.StringIO(text), delimiter=report.delimiter)
    if not reader.fieldnames:
        report.fatal = "No header row found."
        return report

    fieldmap = {normalise_header(f): f for f in reader.fieldnames if f is not None}
    report.columns = sorted(fieldmap)
    if "name" not in fieldmap and "code" not in fieldmap and "id" not in fieldmap:
        report.fatal = (
            "The header must contain at least one of 'name', 'code' or 'id'. "
            f"Found: {', '.join(report.columns) or '(nothing)'}. If the columns "
            "look right, the delimiter may be wrong — this file was read as "
            f"'{report.delimiter}'-separated."
        )
        return report

    report.attribute_columns = sorted(k for k in fieldmap if k not in KNOWN_COLUMNS)

    zones = _lookup(db, FareZone)
    areas = _lookup(db, StopArea)

    for offset, raw_row in enumerate(reader):
        line = offset + 2  # header is line 1
        if len(report.rows) >= MAX_ROWS:
            report.fatal = f"Stopped at {MAX_ROWS:,} rows; split the file."
            break

        row = {key: (raw_row.get(source) or "") for key, source in fieldmap.items()}
        if not any(v.strip() for v in row.values()):
            continue  # blank line, common at the end of a spreadsheet

        report.total += 1
        savepoint = db.begin_nested()
        try:
            result = _apply_row(db, row, line, zones, areas, replace_attributes)
            db.flush()
            savepoint.commit()
            report.rows.append(result)
            setattr(report, result.action, getattr(report, result.action) + 1)
        except RowError as exc:
            savepoint.rollback()
            report.failed += 1
            report.rows.append(
                RowResult(
                    line=line,
                    action="failed",
                    name=_pick(row, "name"),
                    code=_pick(row, "code"),
                    message=str(exc),
                )
            )
        except Exception as exc:  # noqa: BLE001 - one row must not kill the file
            savepoint.rollback()
            report.failed += 1
            report.rows.append(
                RowResult(
                    line=line,
                    action="failed",
                    name=_pick(row, "name"),
                    code=_pick(row, "code"),
                    message=_readable(exc),
                )
            )

    # A dry run leaves nothing behind; a real run is all-or-nothing, so a file
    # is never half-applied.
    if dry_run or not report.ok:
        db.rollback()
        if not dry_run and not report.ok:
            report.created = report.updated = report.skipped = 0
            for entry in report.rows:
                if entry.action != "failed":
                    entry.action = "skipped"
                    entry.message = "Not applied — the file had errors."
            report.skipped = sum(1 for e in report.rows if e.action == "skipped")
    else:
        db.commit()

    return report


def _lookup(db: Session, model) -> dict[str, int]:
    """Name and code to id, lowercased, for resolving references by label."""
    index: dict[str, int] = {}
    rows = db.scalars(select(model)).all()
    for row in rows:
        if row.name:
            index[row.name.strip().lower()] = row.id
        code = getattr(row, "code", None)
        if code:
            index[code.strip().lower()] = row.id
    return index


def _apply_row(
    db: Session,
    row: dict[str, str],
    line: int,
    zones: dict[str, int],
    areas: dict[str, int],
    replace_attributes: bool,
) -> RowResult:
    raw_id = _pick(row, "id")
    code = _pick(row, "code")
    name = _pick(row, "name")

    target: Location | None = None
    if raw_id:
        try:
            location_id = int(raw_id)
        except ValueError:
            raise RowError(f"id '{raw_id}' is not a number") from None
        target = db.get(Location, location_id)
        if target is None:
            raise RowError(
                f"id {location_id} does not exist. Leave the id blank to create "
                "a new location."
            )
    elif code:
        target = db.scalar(
            select(Location).where(func.lower(Location.code) == code.lower())
        )

    creating = target is None
    if creating:
        if not name:
            raise RowError("a new location needs a name")
        target = Location(name=name, location_type=LocationType.STOP.value)
        db.add(target)
    elif name:
        target.name = name

    # When the row was matched by id, the code is genuinely editable. When it
    # was matched *by* code, this is the same value anyway.
    if code and (creating or raw_id):
        target.code = code

    # --- type -------------------------------------------------------------
    type_text = _pick(row, "location_type", "type")
    if type_text:
        try:
            target.location_type = LocationType(type_text.strip().lower()).value
        except ValueError:
            allowed = ", ".join(t.value for t in LocationType)
            raise RowError(f"location_type '{type_text}' is not one of: {allowed}") from None

    # --- coordinates ------------------------------------------------------
    lat_text = _pick(row, "lat", "latitude")
    if lat_text:
        lat = _number(lat_text, "lat")
        if lat is not None and not -90 <= lat <= 90:
            raise RowError(f"lat {lat} is outside -90..90")
        target.lat = lat
    lon_text = _pick(row, "lon", "lng", "longitude")
    if lon_text:
        lon = _number(lon_text, "lon")
        if lon is not None and not -180 <= lon <= 180:
            raise RowError(f"lon {lon} is outside -180..180")
        target.lon = lon

    # --- references -------------------------------------------------------
    zone_text = _pick(row, "zone_id", "zone", "zone_code")
    if zone_text:
        target.zone_id = _resolve(zone_text, zones, "fare zone")

    area_text = _pick(row, "area_id", "area", "stop_area")
    if area_text:
        area_id = _resolve(area_text, areas, "stop area")
        if target.location_type != LocationType.STOP.value:
            raise RowError(
                "only 'stop' locations can belong to a stop area — a depot is "
                "not somewhere a passenger transfers"
            )
        target.area_id = area_id

    active_text = _pick(row, "is_active", "active")
    if active_text:
        target.is_active = _boolean(active_text)

    notes = _pick(row, "notes")
    if notes:
        target.notes = notes

    db.flush()

    # --- attributes -------------------------------------------------------
    changed_attributes = _apply_attributes(db, target, row, replace_attributes)

    action = "created" if creating else "updated"
    if not creating and not changed_attributes and not _touched(row):
        action = "skipped"

    return RowResult(
        line=line,
        action=action,
        name=target.name,
        code=target.code or "",
        location_id=target.id,
        message="" if action != "skipped" else "Nothing to change.",
    )


def _touched(row: dict[str, str]) -> bool:
    """Did this row carry any field worth writing?"""
    return any(
        (row.get(key) or "").strip()
        for key in KNOWN_COLUMNS - {"id", "code"}
        if key in row
    )


def _resolve(text: str, index: dict[str, int], label: str) -> int:
    if text.isdigit():
        candidate = int(text)
        if candidate in index.values():
            return candidate
        raise RowError(f"{label} id {candidate} does not exist")
    found = index.get(text.strip().lower())
    if found is None:
        raise RowError(f"{label} '{text}' does not exist — create it first")
    return found


def _apply_attributes(
    db: Session, location: Location, row: dict[str, str], replace: bool
) -> bool:
    """Unknown columns become attributes.

    A blank cell leaves the attribute alone rather than deleting it, so a
    spreadsheet holding only a couple of columns cannot wipe everything else.
    `replace` is the explicit opt-in for "this file is the whole truth".
    """
    incoming = {
        key: (value or "").strip()
        for key, value in row.items()
        if key not in KNOWN_COLUMNS
    }
    if not incoming and not replace:
        return False

    existing = {a.attribute_key: a for a in location.attributes}
    changed = False

    if replace:
        for key, attribute in list(existing.items()):
            if key not in incoming or not incoming[key]:
                db.delete(attribute)
                changed = True

    for key, value in incoming.items():
        if not value:
            continue
        current = existing.get(key)
        if current is None:
            db.add(
                LocationAttribute(
                    location_id=location.id, attribute_key=key, attribute_value=value
                )
            )
            changed = True
        elif current.attribute_value != value:
            current.attribute_value = value
            changed = True

    return changed


def _readable(exc: Exception) -> str:
    text = str(getattr(exc, "orig", exc)).strip().splitlines()
    first = text[0] if text else str(exc)
    lowered = first.lower()
    if "unique" in lowered or "duplicate" in lowered:
        return f"That code is already used by another location. ({first[:160]})"
    return first[:200]
