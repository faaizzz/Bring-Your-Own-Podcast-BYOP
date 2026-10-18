import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
import respx
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from byop import cli
from byop.models import Item, User
from tests.helpers import make_settings
from tests.models.factories import make_show
from tests.providers.llm.helpers import OPENROUTER_URL, completion
from tests.services.test_ranking import add_items


@pytest.fixture
def cli_db(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> AsyncSession:
    @asynccontextmanager
    async def _session() -> AsyncIterator[AsyncSession]:
        yield db_session

    async def _no_dispose() -> None:
        return None

    monkeypatch.setattr(cli, "get_sessionmaker", lambda: _session)
    monkeypatch.setattr(cli, "dispose_engine", _no_dispose)
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: make_settings(
            openrouter_api_key=SecretStr("sk-or-test-key-123456"),
            default_llm_provider="openrouter",
            default_llm_model="vendor/model",
        ),
    )
    return db_session


@respx.mock
async def test_rank_prints_the_selection_with_reasons_and_merged_coverage(
    cli_db: AsyncSession, admin_user: User, capsys: pytest.CaptureFixture[str]
) -> None:
    show = await make_show(cli_db, admin_user, slug="chips")
    show.items_per_episode = 2
    await add_items(cli_db, show, 5)
    picks = {
        "selections": [
            {"item": 3, "score": 9.5, "reason": "The biggest story.", "supporting": [1]},
            {"item": 2, "score": 6, "reason": "A useful follow-up."},
        ]
    }
    respx.post(OPENROUTER_URL).mock(
        return_value=httpx.Response(200, json=completion(json.dumps(picks)))
    )

    code = await cli._rank("chips")

    out = capsys.readouterr().out
    assert code == 0
    assert "2 of 5 available items chosen" in out
    assert " 1. [ 9.5] Story 3" in out and "The biggest story." in out
    assert "also covered by: Story 1" in out
    assert " 2. [ 6.0] Story 2" in out and "A useful follow-up." in out
    held = await cli_db.scalars(select(Item.reserved_run_id).where(Item.show_id == show.id))
    assert set(held) == {None}  # a dry run reserves nothing


async def test_rank_says_when_it_fell_back_to_recency(
    cli_db: AsyncSession,
    admin_user: User,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "get_settings", make_settings)  # no model configured
    show = await make_show(cli_db, admin_user, slug="chips")
    show.items_per_episode = 2
    await add_items(cli_db, show, 3)

    await cli._rank(str(show.id))

    out = capsys.readouterr().out
    assert "most recent items used instead of the model" in out and "No language model" in out
    assert " 1. [ 0.0] Story 1" in out


async def test_rank_with_an_unknown_show_fails(
    cli_db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await cli._rank("nope") == 1
    assert "No show with id or slug 'nope'" in capsys.readouterr().err


def test_the_rank_command_is_registered() -> None:
    with pytest.raises(SystemExit):
        cli.main(["rank"])  # the show argument is required
