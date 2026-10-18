"""Scratch files of a run (audio chunks and the like), outside the database and the storage.

They live under `MEDIA_ROOT/work/<run id>/`, which every worker of the deployment shares, and
are removed when the run ends, whichever way.
"""

import shutil
import uuid
from pathlib import Path

import anyio
import anyio.to_thread


def work_dir(media_root: str | Path, run_id: uuid.UUID) -> Path:
    return Path(media_root) / "work" / str(run_id)


async def reset_dir(path: Path) -> Path:
    """An empty directory at `path`, so a retried stage never mixes in files from an earlier try."""
    await anyio.to_thread.run_sync(shutil.rmtree, path, True)
    await anyio.Path(path).mkdir(parents=True)
    return path


async def remove_work_dir(media_root: str | Path, run_id: uuid.UUID) -> None:
    await anyio.to_thread.run_sync(shutil.rmtree, work_dir(media_root, run_id), True)
