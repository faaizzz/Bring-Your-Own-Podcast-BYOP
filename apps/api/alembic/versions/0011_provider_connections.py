"""provider connections

Replaces the single `openai_compatible` credential with any number of named connections. An
existing credential becomes one connection called "OpenAI-compatible", and the shows that used it
are repointed at `conn:<id>`.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-20 09:12:04.118233
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from byop.config import get_settings
from byop.security.crypto import CryptoError, decrypt_json, encrypt_json

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY = "openai_compatible"
MIGRATED_NAME = "OpenAI-compatible"
# Where an old credential whose key can no longer be read is parked: disabled, for the user to fix.
PLACEHOLDER_URL = "http://localhost:11434/v1"


def upgrade() -> None:
    op.create_table(
        "provider_connections",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("base_url", sa.String(length=2048), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("llm", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("tts", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("web_search", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
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
            ["user_id"],
            ["users.id"],
            name=op.f("fk_provider_connections_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_connections")),
        sa.UniqueConstraint("user_id", "name", name=op.f("uq_provider_connections_user_id")),
    )
    op.create_index(
        op.f("ix_provider_connections_user_id"), "provider_connections", ["user_id"], unique=False
    )
    op.alter_column(
        "usage_events",
        "provider",
        existing_type=sa.String(length=50),
        type_=sa.String(length=100),
        existing_nullable=False,
    )
    _move_legacy_credentials()


def _secret_key() -> object | None:
    try:
        return get_settings().byop_secret_key
    except Exception:  # no usable settings: the old credentials cannot be read
        return None


def _move_legacy_credentials() -> None:
    bind = op.get_bind()
    secret = _secret_key()
    rows = bind.execute(
        sa.text(
            "SELECT user_id, secret_encrypted, enabled FROM provider_credentials "
            "WHERE provider = :p"
        ),
        {"p": LEGACY},
    ).all()
    for user_id, token, enabled in rows:
        base_url, api_key, usable = PLACEHOLDER_URL, None, False
        try:
            if secret is None:
                raise CryptoError("no key")
            payload = decrypt_json(token, secret)  # type: ignore[arg-type]
            url = payload.get("base_url")
            if isinstance(url, str) and url:
                base_url, usable = url, bool(enabled)
            key = payload.get("api_key")
            api_key = key if isinstance(key, str) and key else None
        except CryptoError:
            pass
        connection_id = uuid.uuid4()
        document: dict[str, object] = {"api_key": api_key, "headers": []}
        sealed = encrypt_json(document, secret) if secret is not None else token  # type: ignore[arg-type]
        bind.execute(
            sa.text(
                "INSERT INTO provider_connections "
                "(id, user_id, name, base_url, secret_encrypted, llm, tts, web_search, enabled) "
                "VALUES (:id, :user_id, :name, :base_url, :secret, true, false, false, :enabled)"
            ),
            {
                "id": connection_id,
                "user_id": user_id,
                "name": MIGRATED_NAME,
                "base_url": base_url,
                "secret": sealed,
                "enabled": usable,
            },
        )
        bind.execute(
            sa.text(
                "UPDATE shows SET llm_provider = :ref WHERE user_id = :u AND llm_provider = :old"
            ),
            {"ref": f"conn:{connection_id}", "u": user_id, "old": LEGACY},
        )
    bind.execute(sa.text("DELETE FROM provider_credentials WHERE provider = :p"), {"p": LEGACY})


def downgrade() -> None:
    bind = op.get_bind()
    secret = _secret_key()
    # Best effort: the first LLM connection of each user becomes the single credential again, and
    # its shows point at it. Voices on connections cannot be expressed before this revision.
    rows = bind.execute(
        sa.text(
            "SELECT DISTINCT ON (user_id) id, user_id, base_url, secret_encrypted, enabled "
            "FROM provider_connections WHERE llm ORDER BY user_id, created_at"
        )
    ).all()
    for connection_id, user_id, base_url, token, enabled in rows:
        api_key = None
        if secret is not None:
            try:
                key = decrypt_json(token, secret).get("api_key")  # type: ignore[arg-type]
                api_key = key if isinstance(key, str) and key else None
            except CryptoError:
                pass
            sealed = encrypt_json(
                {"api_key": api_key, "base_url": base_url, "extra": {}},
                secret,  # type: ignore[arg-type]
            )
            bind.execute(
                sa.text(
                    "INSERT INTO provider_credentials "
                    "(id, user_id, provider, secret_encrypted, enabled) "
                    "VALUES (gen_random_uuid(), :u, :p, :s, :e)"
                ),
                {"u": user_id, "p": LEGACY, "s": sealed, "e": enabled},
            )
        bind.execute(
            sa.text(
                "UPDATE shows SET llm_provider = :old WHERE user_id = :u AND llm_provider = :ref"
            ),
            {"old": LEGACY, "u": user_id, "ref": f"conn:{connection_id}"},
        )
    # What still points at a connection cannot be resolved any more.
    bind.execute(
        sa.text(
            "UPDATE shows SET llm_provider = NULL, llm_model = NULL "
            "WHERE llm_provider LIKE 'conn:%'"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE speakers SET fallback_tts_provider = NULL, "
            "fallback_voice_id = NULL WHERE fallback_tts_provider LIKE 'conn:%'"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE speakers SET tts_provider = 'kokoro', voice_id = 'af_bella', "
            "voice_params = '{}'::jsonb WHERE tts_provider LIKE 'conn:%'"
        )
    )
    bind.execute(sa.text("UPDATE usage_events SET provider = left(provider, 50)"))
    op.alter_column(
        "usage_events",
        "provider",
        existing_type=sa.String(length=100),
        type_=sa.String(length=50),
        existing_nullable=False,
    )
    op.drop_index(op.f("ix_provider_connections_user_id"), table_name="provider_connections")
    op.drop_table("provider_connections")
