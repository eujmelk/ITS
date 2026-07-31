from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.enums import Severity

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class Message(BaseModel):
    detail: str


class BulkResult(BaseModel):
    created: int = 0
    updated: int = 0
    deleted: int = 0


class ValidationIssue(BaseModel):
    """A rule-check result.

    Issues are reported, never enforced: a save always succeeds so an operator
    can consciously accept an edge case. ``severity`` drives the colour in the
    UI; ``code`` is stable and safe to key off.
    """

    code: str
    severity: Severity = Severity.ERROR
    message: str
    entity: str | None = None
    entity_id: int | None = None
    sequence: int | None = None


class ValidationReport(BaseModel):
    ok: bool = Field(description="True when there are no error-severity issues.")
    issues: list[ValidationIssue] = []

    @classmethod
    def from_issues(cls, issues: list[ValidationIssue]) -> ValidationReport:
        return cls(
            ok=not any(i.severity == Severity.ERROR for i in issues),
            issues=issues,
        )


class AppConfig(BaseModel):
    """Public runtime config handed to the frontend before login."""

    app_name: str
    map_tile_url: str
    map_attribution: str
    map_default_lat: float
    map_default_lon: float
    map_default_zoom: int
