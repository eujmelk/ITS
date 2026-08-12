"""Generic CRUD plumbing.

Twelve modules with near-identical list/get/create/update/delete endpoints is
twelve chances to make an inconsistent one. :func:`crud_router` builds them
from the model plus its schemas; modules then add only the endpoints that are
genuinely specific to them (pattern-stop replacement, block validation, ...).
"""

# NOTE: deliberately no `from __future__ import annotations` here.
# crud_router() annotates its generated endpoints with `create_schema` /
# `update_schema`, which are closure variables. Postponed evaluation would
# turn those into strings that FastAPI resolves via get_type_hints() against
# module globals only -- where they do not exist -- raising NameError at
# import time. Eager evaluation binds the real classes instead.

from enum import Enum
from typing import Any, Callable, Sequence, Type

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import DbSession, ReaderUser, require_planner
from app.schemas.common import Page

MAX_LIMIT = 1000


def get_or_404(db: Session, model: type, pk: Any, label: str | None = None) -> Any:
    obj = db.get(model, pk)
    if obj is None:
        name = label or model.__name__
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"{name} {pk} not found"
        )
    return obj


def check_exists(db: Session, model: type, pk: Any, field: str) -> Any:
    """Validate a foreign key from the service layer, with a clear message."""
    obj = db.get(model, pk)
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field}={pk} does not exist ({model.__name__})",
        )
    return obj


def commit(db: Session) -> None:
    """Commit, turning constraint violations into a readable 409."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_explain_integrity_error(exc),
        ) from exc


def _explain_integrity_error(exc: IntegrityError) -> str:
    raw = str(getattr(exc, "orig", exc))
    lowered = raw.lower()
    if "unique" in lowered or "duplicate key" in lowered:
        return f"That value is already in use. ({_first_line(raw)})"
    if "foreign key" in lowered:
        return (
            "This record is still referenced by other data, or points at "
            f"something that no longer exists. ({_first_line(raw)})"
        )
    if "check constraint" in lowered:
        return f"A validation rule rejected this record. ({_first_line(raw)})"
    return _first_line(raw)


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0][:300]


def unwrap_enums(data: dict[str, Any]) -> dict[str, Any]:
    """Replace Enum members with their values before they reach the database.

    The controlled vocabularies are stored as plain VARCHAR, so the driver
    must be handed a str, not a StrEnum member.
    """
    return {k: (v.value if isinstance(v, Enum) else v) for k, v in data.items()}


def apply_updates(obj: Any, payload: BaseModel, skip: Sequence[str] = ()) -> None:
    """Apply a PATCH body, honouring 'field absent' vs 'field set to null'.

    Only *column* attributes are assigned. Testing ``hasattr`` instead would
    also match relationships -- a payload carrying ``attributes`` would then
    assign a list of plain dicts straight into a relationship collection, and
    SQLAlchemy raises on flush, surfacing as a 500. Nested collections are the
    business of the module's own ``on_update`` hook, which knows how to build
    the right ORM objects.
    """
    columns = {c.key for c in type(obj).__mapper__.column_attrs}
    data = unwrap_enums(payload.model_dump(exclude_unset=True))
    for key, value in data.items():
        if key in skip or key not in columns:
            continue
        setattr(obj, key, value)


def crud_router(
    *,
    model: type,
    read_schema: Type[BaseModel],
    create_schema: Type[BaseModel] | None,
    update_schema: Type[BaseModel] | None,
    prefix: str,
    tags: list[str],
    pk_attr: str = "id",
    search_fields: Sequence[str] = (),
    filter_fields: Sequence[str] = (),
    order_by: Sequence[str] = ("id",),
    options: Sequence[Any] = (),
    serialize: Callable[[Any, Session], BaseModel] | None = None,
    on_create: Callable[[Any, BaseModel, Session], None] | None = None,
    on_update: Callable[[Any, BaseModel, Session], None] | None = None,
    on_delete: Callable[[Any, Session], None] | None = None,
    label: str | None = None,
) -> APIRouter:
    """Build a standard CRUD router for ``model``.

    ``filter_fields`` are read straight off the query string (e.g.
    ``?line_id=3``) rather than being declared as typed parameters -- keeping
    them declarative would mean generating a signature per model, which is
    more magic than it is worth. They are still allow-listed, so an unknown
    or non-filterable parameter is simply ignored.
    """

    router = APIRouter(prefix=prefix, tags=tags)
    entity = label or model.__name__

    def _serialize(obj: Any, db: Session) -> BaseModel:
        if serialize is not None:
            return serialize(obj, db)
        return read_schema.model_validate(obj)

    def _apply_filters(stmt, request: Request):
        for name in filter_fields:
            raw = request.query_params.get(name)
            if raw is None or raw == "":
                continue
            column = getattr(model, name)
            lowered = raw.lower()
            if lowered in ("null", "none"):
                stmt = stmt.where(column.is_(None))
                continue
            try:
                python_type = model.__table__.c[name].type.python_type
            except (KeyError, NotImplementedError):
                python_type = str
            if python_type is bool:
                if lowered not in ("true", "false", "1", "0"):
                    continue
                stmt = stmt.where(column.is_(lowered in ("true", "1")))
            elif python_type is int:
                # A non-numeric value for an integer column would otherwise
                # reach the driver and raise a 500.
                try:
                    stmt = stmt.where(column == int(raw))
                except ValueError:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=f"{name} must be a whole number, got {raw!r}",
                    ) from None
            else:
                stmt = stmt.where(column == raw)
        return stmt

    @router.get(
        "",
        response_model=Page[read_schema],
        summary=f"List {entity} records",
    )
    def list_items(  # noqa: D401
        request: Request,
        db: DbSession,
        _user: ReaderUser,
        limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
        offset: int = Query(default=0, ge=0),
        q: str | None = Query(default=None, description="Free-text search"),
        sort: str | None = Query(
            default=None, description="Column to sort by; unknown names are ignored"
        ),
        order: str = Query(default="asc", pattern="^(asc|desc)$"),
    ) -> Page:
        stmt = select(model)
        stmt = _apply_filters(stmt, request)

        if q and search_fields:
            needle = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(*[getattr(model, f).ilike(needle) for f in search_fields])
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = db.scalar(count_stmt) or 0

        # `total` is the count *before* limit/offset, so the client can tell
        # "50 of 4,312" from "50 of 50" and page rather than silently see a
        # truncated list.
        if sort and sort in model.__table__.c:
            column = getattr(model, sort)
            stmt = stmt.order_by(column.desc() if order == "desc" else column.asc())
            # Ties would otherwise page unstably, repeating or skipping rows.
            stmt = stmt.order_by(getattr(model, pk_attr))
        else:
            for field in order_by:
                stmt = stmt.order_by(getattr(model, field))

        if options:
            # Eager-load relationships the serializer touches, so listing N
            # rows stays one query rather than N.
            stmt = stmt.options(*options)

        rows = db.scalars(stmt.limit(limit).offset(offset)).all()
        return Page(
            items=[_serialize(row, db) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    @router.get("/{item_id}", response_model=read_schema, summary=f"Get one {entity}")
    def get_item(item_id: str, db: DbSession, _user: ReaderUser):
        obj = get_or_404(db, model, _coerce_pk(model, pk_attr, item_id), entity)
        return _serialize(obj, db)

    if create_schema is not None:

        @router.post(
            "",
            response_model=read_schema,
            status_code=status.HTTP_201_CREATED,
            summary=f"Create a {entity}",
            dependencies=[Depends(require_planner)],
        )
        def create_item(payload: create_schema, db: DbSession):  # type: ignore[valid-type]
            data = unwrap_enums(payload.model_dump(exclude_unset=True))
            columns = {c.key for c in model.__mapper__.column_attrs}
            obj = model(**{k: v for k, v in data.items() if k in columns})
            db.add(obj)
            if on_create is not None:
                db.flush()
                on_create(obj, payload, db)
            commit(db)
            db.refresh(obj)
            return _serialize(obj, db)

    if update_schema is not None:

        @router.patch(
            "/{item_id}",
            response_model=read_schema,
            summary=f"Update a {entity}",
            dependencies=[Depends(require_planner)],
        )
        def update_item(item_id: str, payload: update_schema, db: DbSession):  # type: ignore[valid-type]
            obj = get_or_404(db, model, _coerce_pk(model, pk_attr, item_id), entity)
            apply_updates(obj, payload)
            if on_update is not None:
                on_update(obj, payload, db)
            commit(db)
            db.refresh(obj)
            return _serialize(obj, db)

    @router.delete(
        "/{item_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        summary=f"Delete a {entity}",
        dependencies=[Depends(require_planner)],
    )
    def delete_item(item_id: str, db: DbSession):
        obj = get_or_404(db, model, _coerce_pk(model, pk_attr, item_id), entity)
        if on_delete is not None:
            on_delete(obj, db)
        db.delete(obj)
        commit(db)

    return router


def _coerce_pk(model: type, pk_attr: str, raw: str) -> Any:
    """Path params arrive as strings; integer keys must be converted."""
    python_type = None
    try:
        python_type = model.__table__.c[pk_attr].type.python_type
    except (AttributeError, KeyError, NotImplementedError):
        pass
    if python_type is int:
        try:
            return int(raw)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{model.__name__} '{raw}' not found",
            ) from None
    return raw
