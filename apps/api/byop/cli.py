"""Operator commands: `python -m byop.cli <command>`."""

import argparse
import asyncio
import os
import sys

from pydantic import SecretStr

from byop.config import get_settings
from byop.db import dispose_engine, get_sessionmaker
from byop.services.credentials import CredentialDecryptionError, rotate_credentials

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m byop.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "rotate-key",
        help=f"re-encrypt stored credentials; the previous key is read from {OLD_KEY_ENV}",
    )
    args = parser.parse_args(argv)

    if args.command == "rotate-key":
        old_key = os.environ.get(OLD_KEY_ENV)
        if not old_key:
            print(f"Set {OLD_KEY_ENV} to the previous BYOP_SECRET_KEY.", file=sys.stderr)
            return 2
        return asyncio.run(_rotate_key(old_key))
    return 2


if __name__ == "__main__":
    sys.exit(main())
