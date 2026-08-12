"""Group parameters by category.

Adds ``parameters.category`` so the Settings page can separate who this
instance is ("identity" -- the name shown in the UI, the agency details GTFS
needs) from the driving and break rules the roster validates against
("operating").

Revision ID: 0002
Revises: 0001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Existing rows are all operating rules; the identity rows are inserted by
# the parameter seeder on the next startup.
_DEFAULT = "operating"


def upgrade() -> None:
    op.add_column(
        "parameters",
        sa.Column(
            "category",
            sa.String(length=32),
            nullable=False,
            server_default=_DEFAULT,
        ),
    )


def downgrade() -> None:
    op.drop_column("parameters", "category")
