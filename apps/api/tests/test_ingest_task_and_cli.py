import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import respx
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from byop import cli
from byop.config import Settings
from byop.models import Item, Source, User
from byop.models.enums import SourceKind
from byop.redis_client import get_redis_client
from byop.tasks import ingest as ingest_task
from tests.helpers import make_settings
from tests.models.factories import make_show

pytestmark = pytest.mark.usefixtures("fake_dns")

FEED = (
    b'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title><item>'
    b"<title>Researchers map the deep ocean floor with new sonar</title>"
    b"<link>https://a.example.com/1</link><description>Scientists explained how the new sonar "
    b"works and why the map matters for the community.</description></item></channel></rss>"
)


async def show_with_feed(session: AsyncSession, user: User, slug: str = "ocean") -> uuid.UUID:
    show = await make_show(session, user, slug=slug)
    session.add(
        Source(
            user_id=user.id,
            show_id=show.id,
            kind=SourceKind.RSS,
            value="https://a.example.com/feed",
        )
    )
    await session.flush()
    respx.get("https://a.example.com/feed").respond(
        200, content=FEED, headers={"content-type": "application/rss+xml"}
    )
    return show.id


@respx.mock
async def test_the_task_body_runs_ingest_and_returns_json_counts(
    db_session: AsyncSession, admin_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    show_id = await show_with_feed(db_session, admin_user)

    @asynccontextmanager
    async def deps() -> AsyncIterator[tuple[AsyncSession, Redis, Settings]]:
        yield db_session, get_redis_client(), make_settings()

    monkeypatch.setattr(ingest_task, "task_deps", deps)

    summary = await ingest_task._run(show_id, None)

    assert summary["new_items"] == 1 and summary["fetched"] == 1
    sources = summary["sources"]
    assert isinstance(sources, list) and sources[0]["error"] is None
    assert (
        await db_session.scalar(select(Item.title))
        == "Researchers map the deep ocean floor with new sonar"
    )


@pytest.fixture
def cli_db(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> AsyncSession:
    @asynccontextmanager
    async def _session() -> AsyncIterator[AsyncSession]:
        yield db_session

    async def _no_dispose() -> None:
        return None

    monkeypatch.setattr(cli, "get_sessionmaker", lambda: _session)
    monkeypatch.setattr(cli, "dispose_engine", _no_dispose)
    monkeypatch.setattr(cli, "get_settings", make_settings)
    return db_session


@respx.mock
async def test_cli_ingest_reports_counts_and_sources(
    cli_db: AsyncSession, admin_user: User, capsys: pytest.CaptureFixture[str]
) -> None:
    await show_with_feed(cli_db, admin_user)

    code = await cli._ingest("ocean")

    out = capsys.readouterr().out
    assert code == 0
    assert "1 new" in out and "1 fetched" in out and "https://a.example.com/feed: 1 items" in out


@respx.mock
async def test_cli_ingest_accepts_an_id_and_repeats_safely(
    cli_db: AsyncSession, admin_user: User, capsys: pytest.CaptureFixture[str]
) -> None:
    show_id = await show_with_feed(cli_db, admin_user)

    await cli._ingest(str(show_id))
    await cli._ingest(str(show_id))

    lines = [line for line in capsys.readouterr().out.splitlines() if "new," in line]
    assert "1 new" in lines[0] and "0 new" in lines[1] and "1 duplicates" in lines[1]


async def test_cli_ingest_with_an_unknown_show_fails(
    cli_db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await cli._ingest("no-such-show") == 1
    assert "No show with id or slug 'no-such-show'" in capsys.readouterr().err


def test_the_ingest_command_is_registered() -> None:
    with pytest.raises(SystemExit):
        cli.main(["ingest"])  # the show argument is required


def test_the_celery_task_parses_its_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[uuid.UUID, uuid.UUID | None]] = []

    async def fake(show_id: uuid.UUID, run_id: uuid.UUID | None) -> dict[str, object]:
        seen.append((show_id, run_id))
        return {"new_items": 0}

    monkeypatch.setattr(ingest_task, "_run", fake)
    show, run = uuid.uuid4(), uuid.uuid4()

    assert ingest_task.ingest_show_task.run(str(show)) == {"new_items": 0}
    ingest_task.ingest_show_task.run(str(show), str(run))

    assert seen == [(show, None), (show, run)]
    assert ingest_task.ingest_show_task.name == "byop.ingest_show"
