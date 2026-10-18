"""run log, cancel flag and one active run per show

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-18 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column("cancel_requested", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_index(
        "uq_runs_one_active_per_show",
        "runs",
        ["show_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.create_table(
        "run_events",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "level",
            sa.Enum(
                "info",
                "warning",
                "error",
                name="event_level",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="info",
            nullable=False,
        ),
        sa.Column("stage", sa.String(length=50), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_run_events_run_id_runs"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_run_events_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_events")),
    )
    op.create_index(op.f("ix_run_events_user_id"), "run_events", ["user_id"], unique=False)
    op.create_index("ix_run_events_run_id_ts", "run_events", ["run_id", "ts"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_run_events_run_id_ts", table_name="run_events")
    op.drop_index(op.f("ix_run_events_user_id"), table_name="run_events")
    op.drop_table("run_events")
    op.drop_index("uq_runs_one_active_per_show", table_name="runs")
    op.drop_column("runs", "cancel_requested")
