"""per-provider delay between requests

A built-in provider's delay lives in the user's settings (it applies whether the key comes from
the environment or from the app); a connection keeps its own on the connection.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-20 17:41:07.230551
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "provider_connections",
        sa.Column("min_interval_s", sa.Float(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "user_settings",
        sa.Column(
            "request_intervals",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "request_intervals")
    op.drop_column("provider_connections", "min_interval_s")
