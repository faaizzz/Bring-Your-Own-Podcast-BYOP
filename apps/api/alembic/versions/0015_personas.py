"""persona library

A user's reusable speaker personas, each with an optional default voice. Existing users get the
starter personas (new users get them when they are created); a persona is copied into a speaker,
so existing shows and speakers are untouched.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-20 19:35:12.904118
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Kept here, as written when this migration was made: a migration must not change with the code.
STARTERS = (
    (
        "Curious host",
        "The curious lead host. Warm and well prepared; introduces each story, explains why it "
        "matters and asks the questions a listener would ask.",
    ),
    (
        "Expert analyst",
        "The expert. Calm and precise; brings background, numbers and context, separates what is "
        "known from what is guessed, and explains without jargon.",
    ),
    (
        "Friendly sceptic",
        "The friendly sceptic. Good-humoured but hard to impress; asks for evidence, points out "
        "hype and plays devil's advocate without being unkind.",
    ),
    (
        "Storyteller",
        "The storyteller. Paints a picture, uses analogies and small anecdotes, and builds each "
        "story so that the listener wants to know what happens next.",
    ),
    (
        "Plain-language explainer",
        "The explainer. Turns technical news into plain language with simple examples, and checks "
        "that nothing important was lost on the way.",
    ),
)


def upgrade() -> None:
    op.create_table(
        "personas",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("persona", sa.Text(), nullable=False),
        sa.Column("tts_provider", sa.String(length=50), nullable=True),
        sa.Column("voice_id", sa.String(length=200), nullable=True),
        sa.Column(
            "voice_params",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
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
    op.create_index(op.f("ix_personas_user_id"), "personas", ["user_id"], unique=False)

    bind = op.get_bind()
    insert = sa.text(
        "INSERT INTO personas (user_id, name, persona) "
        "SELECT id, :name, :persona FROM users "
        "ON CONFLICT (user_id, name) DO NOTHING"
    )
    for name, persona in STARTERS:
        bind.execute(insert, {"name": name, "persona": persona})


def downgrade() -> None:
    op.drop_index(op.f("ix_personas_user_id"), table_name="personas")
    op.drop_table("personas")
