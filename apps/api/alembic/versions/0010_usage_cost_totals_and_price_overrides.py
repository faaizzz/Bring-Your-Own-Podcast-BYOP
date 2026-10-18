"""usage cost totals and price overrides

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-18 19:41:32.783645
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "price_overrides",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("input_per_million", sa.Numeric(precision=14, scale=6), nullable=True),
        sa.Column("output_per_million", sa.Numeric(precision=14, scale=6), nullable=True),
        sa.Column("per_million_chars", sa.Numeric(precision=14, scale=6), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('llm', 'tts')", name=op.f("ck_price_overrides_price_override_kind")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_price_overrides_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_overrides")),
        sa.UniqueConstraint("user_id", "kind", "name", name=op.f("uq_price_overrides_user_id")),
    )
    op.create_index(
        op.f("ix_price_overrides_user_id"), "price_overrides", ["user_id"], unique=False
    )
    op.add_column(
        "runs",
        sa.Column(
            "cost_usd", sa.Numeric(precision=12, scale=6), server_default="0", nullable=False
        ),
    )
    op.add_column(
        "runs",
        sa.Column(
            "llm_cost_usd", sa.Numeric(precision=12, scale=6), server_default="0", nullable=False
        ),
    )
    op.add_column(
        "runs",
        sa.Column(
            "tts_cost_usd", sa.Numeric(precision=12, scale=6), server_default="0", nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("runs", "tts_cost_usd")
    op.drop_column("runs", "llm_cost_usd")
    op.drop_column("runs", "cost_usd")
    op.drop_index(op.f("ix_price_overrides_user_id"), table_name="price_overrides")
    op.drop_table("price_overrides")
