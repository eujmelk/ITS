"""Attributes belong to patterns, not lines.

An attribute describes a *variant* of a service -- express, school-days-only,
via the hospital -- and those differ between a line's patterns rather than
applying to all of them. Having both levels was ambiguous: nothing said which
one won when they disagreed.

Existing line attributes are copied onto that line's patterns before the table
is dropped, so nothing entered is silently lost. A pattern that already
defines the same key keeps its own value -- the more specific statement wins.

Revision ID: 0004
Revises: 0003
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()

    connection.execute(
        sa.text(
            """
            INSERT INTO pattern_attributes (pattern_id, attribute_key, attribute_value)
            SELECT p.id, la.attribute_key, la.attribute_value
            FROM line_attributes AS la
            JOIN patterns AS p ON p.line_id = la.line_id
            WHERE NOT EXISTS (
                SELECT 1 FROM pattern_attributes AS pa
                WHERE pa.pattern_id = p.id
                  AND pa.attribute_key = la.attribute_key
            )
            """
        )
    )

    op.drop_index("ix_line_attributes_line_id", table_name="line_attributes")
    op.drop_table("line_attributes")


def downgrade() -> None:
    """Recreate the table, empty.

    The copy above is not reversible: once merged onto patterns there is no
    record of which rows came from a line, and guessing would invent data.
    """
    op.create_table(
        "line_attributes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("line_id", sa.Integer(), nullable=False),
        sa.Column("attribute_key", sa.String(length=64), nullable=False),
        sa.Column("attribute_value", sa.String(length=512), nullable=True),
        sa.ForeignKeyConstraint(
            ["line_id"],
            ["lines.id"],
            name=op.f("fk_line_attributes_line_id_lines"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_line_attributes")),
        sa.UniqueConstraint("line_id", "attribute_key", name="uq_line_attribute"),
    )
    op.create_index("ix_line_attributes_line_id", "line_attributes", ["line_id"])
