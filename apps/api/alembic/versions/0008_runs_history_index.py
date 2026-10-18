"""index for paging through a user's runs

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-18 19:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_runs_user_id_created_at_id", "runs", ["user_id", "created_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_runs_user_id_created_at_id", table_name="runs")
