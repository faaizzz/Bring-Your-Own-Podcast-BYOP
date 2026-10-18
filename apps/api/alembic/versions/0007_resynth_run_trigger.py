"""a run can be a re-synthesis of an edited script

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-18 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = op.f("ck_runs_run_trigger")  # the full name, so the naming convention leaves it


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, "runs", type_="check")
    op.create_check_constraint(
        CONSTRAINT, "runs", sa.text("trigger IN ('manual', 'schedule', 'resynth')")
    )


def downgrade() -> None:
    op.execute("DELETE FROM runs WHERE trigger = 'resynth'")
    op.drop_constraint(CONSTRAINT, "runs", type_="check")
    op.create_check_constraint(CONSTRAINT, "runs", sa.text("trigger IN ('manual', 'schedule')"))
