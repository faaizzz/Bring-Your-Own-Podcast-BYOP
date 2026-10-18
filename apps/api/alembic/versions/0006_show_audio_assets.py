"""intro, outro and music bed of a show

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-18 17:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for column in ("intro_key", "outro_key", "music_key"):
        op.add_column("shows", sa.Column(column, sa.String(length=500), nullable=True))


def downgrade() -> None:
    for column in ("music_key", "outro_key", "intro_key"):
        op.drop_column("shows", column)
