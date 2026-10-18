import uuid
from pathlib import Path

import pytest

from byop.services.storage import LocalStorage, show_prefix


async def test_delete_prefix_removes_only_that_tree(tmp_path: Path) -> None:
    (tmp_path / "shows" / "a").mkdir(parents=True)
    (tmp_path / "shows" / "a" / "x.mp3").write_bytes(b"1")
    (tmp_path / "shows" / "ab").mkdir()
    (tmp_path / "shows" / "ab" / "y.mp3").write_bytes(b"2")

    await LocalStorage(tmp_path).delete_prefix("shows/a")

    assert not (tmp_path / "shows" / "a").exists()
    assert (tmp_path / "shows" / "ab" / "y.mp3").exists()


async def test_a_missing_prefix_is_not_an_error(tmp_path: Path) -> None:
    await LocalStorage(tmp_path).delete_prefix("shows/nothing")


@pytest.mark.parametrize("prefix", ["../outside", "shows/../..", ".", ""])
async def test_it_never_deletes_outside_or_the_root(tmp_path: Path, prefix: str) -> None:
    root = tmp_path / "media"
    root.mkdir()
    (tmp_path / "outside").mkdir()

    with pytest.raises(ValueError):
        await LocalStorage(root).delete_prefix(prefix)

    assert root.exists() and (tmp_path / "outside").exists()


def test_show_prefix_is_namespaced_by_id() -> None:
    show_id = uuid.uuid4()
    assert show_prefix(show_id) == f"shows/{show_id}"
