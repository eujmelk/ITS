"""Generic key/value attributes on patterns.

Locations and lines already carry these; patterns did not, so there was no way
to say "this variant is the express one" without inventing a naming
convention. Values print as bubbles beside the line number on duty cards.

Revision ID: 0003
Revises: 0002
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pattern_attributes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pattern_id", sa.Integer(), nullable=False),
        sa.Column("attribute_key", sa.String(length=64), nullable=False),
        sa.Column("attribute_value", sa.String(length=512), nullable=True),
        sa.ForeignKeyConstraint(
            ["pattern_id"],
            ["patterns.id"],
            name=op.f("fk_pattern_attributes_pattern_id_patterns"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pattern_attributes")),
        sa.UniqueConstraint("pattern_id", "attribute_key", name="uq_pattern_attribute"),
    )
    op.create_index(
        op.f("ix_pattern_attributes_pattern_id"),
        "pattern_attributes",
        ["pattern_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_pattern_attributes_pattern_id"), table_name="pattern_attributes")
    op.drop_table("pattern_attributes")
