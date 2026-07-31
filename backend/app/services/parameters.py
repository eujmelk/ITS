"""Access to the global operating parameters.

Every caller goes through :func:`resolve`, which already accepts a ``scope``.
Today the scope is ignored and the single global row wins; when per-line or
per-driver overrides are added, only this function changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Parameter


@dataclass(frozen=True)
class ParameterSpec:
    key: str
    default: str
    value_type: str
    description: str
    unit: str | None = None


#: Seeded on first startup. Editing the value is a Settings-page action;
#: editing this list is a code change.
PARAMETER_SPECS: tuple[ParameterSpec, ...] = (
    ParameterSpec(
        "max_driving_minutes_per_day",
        "540",
        "int",
        "Maximum time a driver may spend on block segments in one duty.",
        "minutes",
    ),
    ParameterSpec(
        "min_break_minutes",
        "45",
        "int",
        "Total break time a duty must contain once it is long enough to "
        "require one.",
        "minutes",
    ),
    ParameterSpec(
        "min_driving_minutes_before_break_required",
        "240",
        "int",
        "A break must be taken before this much continuous driving has "
        "elapsed. Set to 0 to check only the daily total.",
        "minutes",
    ),
    ParameterSpec(
        "min_single_break_minutes",
        "20",
        "int",
        "Shortest rest that counts towards the break total; anything "
        "shorter is treated as an idle gap.",
        "minutes",
    ),
    ParameterSpec(
        "max_duty_length_minutes",
        "780",
        "int",
        "Maximum elapsed time from sign-on to sign-off, breaks included.",
        "minutes",
    ),
    ParameterSpec(
        "min_sign_on_minutes",
        "10",
        "int",
        "Paid time before the first block segment starts.",
        "minutes",
    ),
    ParameterSpec(
        "min_sign_off_minutes",
        "10",
        "int",
        "Paid time after the last block segment ends.",
        "minutes",
    ),
    ParameterSpec(
        "min_layover_seconds_between_pieces",
        "0",
        "int",
        "Minimum turnaround a vehicle needs between consecutive block "
        "pieces at the same location.",
        "seconds",
    ),
    ParameterSpec(
        "require_break_at_driver_changeover",
        "false",
        "bool",
        "When true, splitting a block between two drivers must include a "
        "break or relief piece at the split point rather than a direct "
        "hand-off.",
        None,
    ),
)

PARAMETER_SPECS_BY_KEY = {spec.key: spec for spec in PARAMETER_SPECS}


def _cast(raw: str, value_type: str) -> Any:
    if value_type == "int":
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return 0
    if value_type == "float":
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.0
    if value_type == "bool":
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    return raw


def resolve(db: Session, key: str, scope: dict[str, Any] | None = None) -> Any:
    """Return the effective value of ``key``.

    ``scope`` is accepted for forward compatibility (e.g.
    ``{"line_id": 4}``) and currently has no effect.
    """
    del scope  # no override table yet -- see module docstring

    row = db.get(Parameter, key)
    spec = PARAMETER_SPECS_BY_KEY.get(key)
    if row is not None:
        return _cast(row.value, row.value_type)
    if spec is not None:
        return _cast(spec.default, spec.value_type)
    return None


def resolve_all(db: Session, scope: dict[str, Any] | None = None) -> dict[str, Any]:
    """All known parameters, database values overriding the built-in defaults."""
    values = {spec.key: _cast(spec.default, spec.value_type) for spec in PARAMETER_SPECS}
    for row in db.scalars(select(Parameter)).all():
        values[row.key] = _cast(row.value, row.value_type)
    del scope
    return values


def ensure_seeded(db: Session) -> int:
    """Insert any parameter rows that do not exist yet. Idempotent."""
    existing = {row.key for row in db.scalars(select(Parameter)).all()}
    added = 0
    for spec in PARAMETER_SPECS:
        if spec.key in existing:
            continue
        db.add(
            Parameter(
                key=spec.key,
                value=spec.default,
                value_type=spec.value_type,
                description=spec.description,
                unit=spec.unit,
            )
        )
        added += 1
    if added:
        db.commit()
    return added
