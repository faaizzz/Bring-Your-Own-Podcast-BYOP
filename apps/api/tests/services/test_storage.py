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


async def test_write_then_read_round_trips_and_overwrites(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)

    assert await storage.read("previews/a.mp3") is None
    await storage.write("previews/a.mp3", b"one")
    assert await storage.read("previews/a.mp3") == b"one"
    await storage.write("previews/a.mp3", b"two")
    assert await storage.read("previews/a.mp3") == b"two"
    assert [p.name for p in (tmp_path / "previews").iterdir()] == ["a.mp3"]  # no temp files left


@pytest.mark.parametrize("key", ["../x", "a/../../x", ""])
async def test_read_and_write_refuse_keys_outside_the_root(tmp_path: Path, key: str) -> None:
    storage = LocalStorage(tmp_path / "media")

    with pytest.raises(ValueError):
        await storage.write(key, b"x")
    with pytest.raises(ValueError):
        await storage.read(key)


async def test_reading_a_directory_is_a_miss(tmp_path: Path) -> None:
    (tmp_path / "dir").mkdir()

    assert await LocalStorage(tmp_path).read("dir") is None
