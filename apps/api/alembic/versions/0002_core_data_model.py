"""core data model: users, credentials, shows, speakers, sources, items, runs, episodes, usage

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-18 12:27:06.563981
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "provider_credentials",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
            "provider IN ('openrouter', 'openai', 'elevenlabs', 'langfuse', 'kokoro', 'openai_compatible')",
            name=op.f("ck_provider_credentials_credential_provider"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_provider_credentials_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_credentials")),
        sa.UniqueConstraint("user_id", "provider", name=op.f("uq_provider_credentials_user_id")),
    )
    op.create_index(
        op.f("ix_provider_credentials_user_id"), "provider_credentials", ["user_id"], unique=False
    )
    op.create_table(
        "shows",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("language", sa.String(length=16), server_default="en", nullable=False),
        sa.Column("target_minutes", sa.Integer(), server_default="10", nullable=False),
        sa.Column("style", sa.String(length=32), server_default="news_briefing", nullable=False),
        sa.Column("prompt_override", sa.Text(), nullable=True),
        sa.Column("llm_provider", sa.String(length=50), nullable=True),
        sa.Column("llm_model", sa.String(length=200), nullable=True),
        sa.Column("items_per_episode", sa.Integer(), server_default="5", nullable=False),
        sa.Column("schedule_kind", sa.String(length=32), server_default="manual", nullable=False),
        sa.Column("schedule_time", sa.Time(), nullable=True),
        sa.Column("schedule_weekday", sa.SmallInteger(), nullable=True),
        sa.Column("schedule_monthday", sa.SmallInteger(), nullable=True),
        sa.Column("timezone", sa.String(length=64), server_default="UTC", nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("auto_publish", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("feed_author", sa.String(length=200), nullable=True),
        sa.Column("feed_email", sa.String(length=320), nullable=True),
        sa.Column("feed_category", sa.String(length=100), nullable=True),
        sa.Column("feed_explicit", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("cover_key", sa.String(length=500), nullable=True),
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
            "schedule_kind IN ('manual', 'daily', 'weekly', 'monthly')",
            name=op.f("ck_shows_schedule_kind"),
        ),
        sa.CheckConstraint(
            "style IN ('news_briefing', 'conversational', 'deep_dive', 'interview')",
            name=op.f("ck_shows_show_style"),
        ),
        sa.CheckConstraint(
            "items_per_episode > 0", name=op.f("ck_shows_items_per_episode_positive")
        ),
        sa.CheckConstraint(
            "schedule_monthday IS NULL OR schedule_monthday BETWEEN 1 AND 31",
            name=op.f("ck_shows_schedule_monthday_range"),
        ),
        sa.CheckConstraint(
            "schedule_weekday IS NULL OR schedule_weekday BETWEEN 0 AND 6",
            name=op.f("ck_shows_schedule_weekday_range"),
        ),
        sa.CheckConstraint("target_minutes > 0", name=op.f("ck_shows_target_minutes_positive")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_shows_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shows")),
        sa.UniqueConstraint("slug", name=op.f("uq_shows_slug")),
    )
    op.create_index(op.f("ix_shows_next_run_at"), "shows", ["next_run_at"], unique=False)
    op.create_index(op.f("ix_shows_user_id"), "shows", ["user_id"], unique=False)
    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("show_id", sa.Uuid(), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="queued", nullable=False),
        sa.Column("stage", sa.String(length=50), nullable=True),
        sa.Column("progress", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("celery_task_id", sa.String(length=64), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('queued', 'running', 'awaiting_review', 'succeeded', 'failed', 'cancelled')",
            name=op.f("ck_runs_run_status"),
        ),
        sa.CheckConstraint("trigger IN ('manual', 'schedule')", name=op.f("ck_runs_run_trigger")),
        sa.CheckConstraint("progress BETWEEN 0 AND 100", name=op.f("ck_runs_progress_range")),
        sa.ForeignKeyConstraint(
            ["show_id"], ["shows.id"], name=op.f("fk_runs_show_id_shows"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_runs_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runs")),
    )
    op.create_index(op.f("ix_runs_show_id"), "runs", ["show_id"], unique=False)
    op.create_index("ix_runs_show_id_created_at", "runs", ["show_id", "created_at"], unique=False)
    op.create_index(op.f("ix_runs_status"), "runs", ["status"], unique=False)
    op.create_index(op.f("ix_runs_user_id"), "runs", ["user_id"], unique=False)
    op.create_table(
        "sources",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("show_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("value", sa.String(length=2048), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("origin", sa.String(length=32), server_default="user", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
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
            "kind IN ('rss', 'url', 'web_search')", name=op.f("ck_sources_source_kind")
        ),
        sa.CheckConstraint(
            "origin IN ('discovered', 'user')", name=op.f("ck_sources_source_origin")
        ),
        sa.ForeignKeyConstraint(
            ["show_id"], ["shows.id"], name=op.f("fk_sources_show_id_shows"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_sources_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sources")),
        sa.UniqueConstraint("show_id", "kind", "value", name=op.f("uq_sources_show_id")),
    )
    op.create_index(op.f("ix_sources_show_id"), "sources", ["show_id"], unique=False)
    op.create_index(op.f("ix_sources_user_id"), "sources", ["user_id"], unique=False)
    op.create_table(
        "speakers",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("show_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("persona", sa.Text(), server_default="", nullable=False),
        sa.Column("tts_provider", sa.String(length=50), nullable=False),
        sa.Column("voice_id", sa.String(length=200), nullable=False),
        sa.Column(
            "voice_params",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("fallback_tts_provider", sa.String(length=50), nullable=True),
        sa.Column("fallback_voice_id", sa.String(length=200), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["show_id"], ["shows.id"], name=op.f("fk_speakers_show_id_shows"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_speakers_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_speakers")),
        sa.UniqueConstraint("show_id", "position", name=op.f("uq_speakers_show_id")),
    )
    op.create_index(op.f("ix_speakers_show_id"), "speakers", ["show_id"], unique=False)
    op.create_index(op.f("ix_speakers_user_id"), "speakers", ["user_id"], unique=False)
    op.create_table(
        "episodes",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("show_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("script", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("audio_key", sa.String(length=500), nullable=True),
        sa.Column("duration_s", sa.Integer(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="draft", nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('draft', 'published', 'rejected')", name=op.f("ck_episodes_episode_status")
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_episodes_run_id_runs"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["show_id"], ["shows.id"], name=op.f("fk_episodes_show_id_shows"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_episodes_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_episodes")),
    )
    op.create_index(op.f("ix_episodes_published_at"), "episodes", ["published_at"], unique=False)
    op.create_index(op.f("ix_episodes_run_id"), "episodes", ["run_id"], unique=False)
    op.create_index(op.f("ix_episodes_show_id"), "episodes", ["show_id"], unique=False)
    op.create_index(op.f("ix_episodes_user_id"), "episodes", ["user_id"], unique=False)
    op.create_table(
        "usage_events",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("show_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("stage", sa.String(length=50), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("characters", sa.Integer(), nullable=True),
        sa.Column(
            "cost_usd", sa.Numeric(precision=12, scale=6), server_default="0", nullable=False
        ),
        sa.Column("cost_source", sa.String(length=32), server_default="unknown", nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
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
            "cost_source IN ('provider', 'price_table', 'unknown')",
            name=op.f("ck_usage_events_cost_source"),
        ),
        sa.CheckConstraint("kind IN ('llm', 'tts')", name=op.f("ck_usage_events_usage_kind")),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_usage_events_run_id_runs"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["show_id"],
            ["shows.id"],
            name=op.f("fk_usage_events_show_id_shows"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_usage_events_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_events")),
    )
    op.create_index(op.f("ix_usage_events_run_id"), "usage_events", ["run_id"], unique=False)
    op.create_index(op.f("ix_usage_events_show_id"), "usage_events", ["show_id"], unique=False)
    op.create_index(op.f("ix_usage_events_user_id"), "usage_events", ["user_id"], unique=False)
    op.create_index(
        "ix_usage_events_user_id_created_at",
        "usage_events",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "items",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("show_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("canonical_url", sa.String(length=2048), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), server_default="", nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("rank_score", sa.Float(), nullable=True),
        sa.Column("used_in_episode_id", sa.Uuid(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["show_id"], ["shows.id"], name=op.f("fk_items_show_id_shows"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_items_source_id_sources"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["used_in_episode_id"],
            ["episodes.id"],
            name=op.f("fk_items_used_in_episode_id_episodes"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_items_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_items")),
        sa.UniqueConstraint("show_id", "canonical_url", name=op.f("uq_items_show_id")),
    )
    op.create_index(op.f("ix_items_show_id"), "items", ["show_id"], unique=False)
    op.create_index(
        "ix_items_show_id_content_hash", "items", ["show_id", "content_hash"], unique=False
    )
    op.create_index(op.f("ix_items_source_id"), "items", ["source_id"], unique=False)
    op.create_index(
        "ix_items_title_trgm",
        "items",
        ["title"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )
    op.create_index(
        op.f("ix_items_used_in_episode_id"), "items", ["used_in_episode_id"], unique=False
    )
    op.create_index(op.f("ix_items_user_id"), "items", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_table("items")
    op.drop_table("usage_events")
    op.drop_table("episodes")
    op.drop_table("speakers")
    op.drop_table("sources")
    op.drop_table("runs")
    op.drop_table("shows")
    op.drop_table("provider_credentials")
    op.drop_table("users")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
