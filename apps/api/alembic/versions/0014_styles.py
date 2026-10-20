"""custom show styles

A user's own styles, and the show's pointer to one. Shows keep their built-in `style`; the
pointer is empty for every existing show.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-20 18:22:47.610233
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "styles",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name"),
    )
    op.create_index(op.f("ix_styles_user_id"), "styles", ["user_id"], unique=False)
    op.add_column("shows", sa.Column("custom_style_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_shows_custom_style_id"), "shows", ["custom_style_id"], unique=False)
    op.create_foreign_key(
        "fk_shows_custom_style_id_styles",
        "shows",
        "styles",
        ["custom_style_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_shows_custom_style_id_styles", "shows", type_="foreignkey")
    op.drop_index(op.f("ix_shows_custom_style_id"), table_name="shows")
    op.drop_column("shows", "custom_style_id")
    op.drop_index(op.f("ix_styles_user_id"), table_name="styles")
    op.drop_table("styles")
