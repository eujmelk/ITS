"""Initial schema.

Revision ID: 0001
Revises:
Create Date: 2026-07-30

This first revision creates the schema straight from ``Base.metadata`` rather
than from ~25 hand-written ``op.create_table`` calls. The result is byte-for-
byte the schema the models describe, which removes a whole class of drift
between revision 1 and the ORM, and it is ordered correctly by SQLAlchemy's
own dependency sort.

From revision 2 onwards use the normal workflow -- ``alembic revision
--autogenerate -m "..."`` -- which compares the live database against
``Base.metadata`` and emits explicit operations. Autogenerate works correctly
against a database created this way precisely because the two are identical.
"""

from typing import Sequence, Union

from alembic import op

from app.models import Base

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
