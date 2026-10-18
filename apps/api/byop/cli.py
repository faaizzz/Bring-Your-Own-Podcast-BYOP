"""Operator commands: `python -m byop.cli <command>`."""

import argparse
import asyncio
import os
import sys
import uuid

from pydantic import SecretStr
from sqlalchemy import select

from byop.config import get_settings
from byop.db import dispose_engine, get_sessionmaker
from byop.models import Item, Show
from byop.services.credentials import (
    CredentialDecryptionError,
    CredentialResolver,
    rotate_credentials,
)
from byop.services.ingest.pipeline import ingest_show
from byop.services.ranking import available_items, rank_items

OLD_KEY_ENV = "OLD_BYOP_SECRET_KEY"


async def _rotate_key(old_key: str) -> int:
    try:
        async with get_sessionmaker()() as session:
            count = await rotate_credentials(
                session, SecretStr(old_key), get_settings().byop_secret_key
            )
    except CredentialDecryptionError as exc:
        print(f"Aborted, nothing changed: {exc}", file=sys.stderr)
        return 1
    finally:
        await dispose_engine()
    print(f"Re-encrypted {count} stored credential(s) with the current BYOP_SECRET_KEY.")
    return 0


async def _ingest(reference: str) -> int:
    """Collect items for one show, given its id or slug, and print what happened."""
    settings = get_settings()
    try:
        async with get_sessionmaker()() as session:
            try:
                condition = Show.id == uuid.UUID(reference)
            except ValueError:
                condition = Show.slug == reference
            show = await session.scalar(select(Show).where(condition))
            if show is None:
                print(f"No show with id or slug '{reference}'.", file=sys.stderr)
                return 1
            result = await ingest_show(
                session, CredentialResolver(session, settings), settings, show.id
            )
    finally:
        await dispose_engine()
    print(
        f"{show.title}: {result.new_items} new, {result.updated_items} updated, "
        f"{result.fetched} fetched, {result.duplicates} duplicates, {result.stale} stale, "
        f"{result.wrong_language} in another language, {result.invalid} invalid."
    )
    for report in result.sources:
        status = f"error: {report.error}" if report.error else f"{report.fetched} items"
        print(f"  - {report.name}: {status}")
    return 0


async def _rank(reference: str) -> int:
    """Show which stories would be chosen for the next episode, without reserving anything."""
    settings = get_settings()
    try:
        async with get_sessionmaker()() as session:
            try:
                condition = Show.id == uuid.UUID(reference)
            except ValueError:
                condition = Show.slug == reference
            show = await session.scalar(select(Show).where(condition))
            if show is None:
                print(f"No show with id or slug '{reference}'.", file=sys.stderr)
                return 1
            candidates = await available_items(session, show)
            selection = await rank_items(
                CredentialResolver(session, settings), settings, show, candidates
            )
            titles = {item.id: item for item in candidates}
    finally:
        await dispose_engine()
    print(
        f"{show.title}: {len(selection.items)} of {selection.candidates} available items chosen "
        f"for an episode of up to {show.items_per_episode}."
    )
    if selection.used_fallback:
        print(f"  (most recent items used instead of the model: {selection.fallback_reason})")
    for position, pick in enumerate(selection.items, start=1):
        item: Item = titles[pick.item_id]
        print(f"{position:>2}. [{pick.score:>4.1f}] {item.title}")
        print(f"      {pick.reason}")
        for other in pick.supporting_item_ids:
            print(f"      also covered by: {titles[other].title}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m byop.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "rotate-key",
        help=f"re-encrypt stored credentials; the previous key is read from {OLD_KEY_ENV}",
    )
    ingest = commands.add_parser("ingest", help="collect fresh items for a show now")
    ingest.add_argument("show", help="the show's id or slug")
    rank = commands.add_parser("rank", help="show the stories that would be chosen for a show")
    rank.add_argument("show", help="the show's id or slug")
    args = parser.parse_args(argv)

    if args.command == "rotate-key":
        old_key = os.environ.get(OLD_KEY_ENV)
        if not old_key:
            print(f"Set {OLD_KEY_ENV} to the previous BYOP_SECRET_KEY.", file=sys.stderr)
            return 2
        return asyncio.run(_rotate_key(old_key))
    if args.command == "ingest":
        return asyncio.run(_ingest(args.show))
    if args.command == "rank":
        return asyncio.run(_rank(args.show))
    return 2


if __name__ == "__main__":
    sys.exit(main())
