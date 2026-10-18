"""ranking hints on shows, run reservation on items

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-18 14:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("shows", sa.Column("ranking_hints", sa.Text(), nullable=True))
    op.add_column("items", sa.Column("reserved_run_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_items_reserved_run_id"), "items", ["reserved_run_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_items_reserved_run_id_runs"),
        "items",
        "runs",
        ["reserved_run_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_items_reserved_run_id_runs"), "items", type_="foreignkey")
    op.drop_index(op.f("ix_items_reserved_run_id"), table_name="items")
    op.drop_column("items", "reserved_run_id")
    op.drop_column("shows", "ranking_hints")
