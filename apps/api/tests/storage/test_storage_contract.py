from pathlib import Path

import httpx
import pytest

from byop.storage import Storage, StorageKeyNotFound


async def collect(storage: Storage, key: str, chunk_size: int = 65536) -> list[bytes]:
    return [chunk async for chunk in storage.get_stream(key, chunk_size=chunk_size)]


async def test_put_then_get_round_trips_and_overwrites(storage: Storage) -> None:
    assert await storage.get("shows/a/cover.jpg") is None

    await storage.put("shows/a/cover.jpg", b"one", content_type="image/jpeg")
    assert await storage.get("shows/a/cover.jpg") == b"one"
    await storage.put("shows/a/cover.jpg", b"two!", content_type="image/jpeg")
    assert await storage.get("shows/a/cover.jpg") == b"two!"


async def test_empty_objects_are_allowed(storage: Storage) -> None:
    await storage.put("empty.bin", b"")

    assert await storage.get("empty.bin") == b""
    info = await storage.head("empty.bin")
    assert info is not None and info.size == 0


async def test_head_reports_size_and_content_type(storage: Storage) -> None:
    await storage.put("shows/a/cover.jpg", b"x" * 1234, content_type="image/jpeg")

    info = await storage.head("shows/a/cover.jpg")

    assert info is not None
    assert info.size == 1234
    assert info.content_type == "image/jpeg"
    assert await storage.head("shows/a/missing.jpg") is None


async def test_exists(storage: Storage) -> None:
    assert not await storage.exists("a/b.txt")
    await storage.put("a/b.txt", b"x")
    assert await storage.exists("a/b.txt")


async def test_stream_yields_the_whole_object_in_chunks(storage: Storage) -> None:
    payload = bytes(range(256)) * 1000  # 256,000 bytes
    await storage.put("shows/a/episode.mp3", payload, content_type="audio/mpeg")

    chunks = await collect(storage, "shows/a/episode.mp3", chunk_size=50_000)

    assert b"".join(chunks) == payload
    assert len(chunks) > 1
    assert all(len(chunk) <= 50_000 for chunk in chunks)


async def test_streaming_a_missing_object_raises(storage: Storage) -> None:
    with pytest.raises(StorageKeyNotFound):
        await collect(storage, "shows/a/nothing.mp3")


async def test_delete_removes_one_object_and_ignores_missing_ones(storage: Storage) -> None:
    await storage.put("a/one.txt", b"1")
    await storage.put("a/two.txt", b"2")

    await storage.delete("a/one.txt")
    await storage.delete("a/one.txt")
    await storage.delete("never/existed.txt")

    assert await storage.get("a/one.txt") is None
    assert await storage.get("a/two.txt") == b"2"


async def test_delete_prefix_removes_the_whole_tree_but_not_siblings(storage: Storage) -> None:
    await storage.put("shows/a/cover.jpg", b"c")
    await storage.put("shows/a/episodes/1/audio.mp3", b"e1")
    await storage.put("shows/a/episodes/2/audio.mp3", b"e2")
    await storage.put("shows/ab/cover.jpg", b"sibling")
    await storage.put("shows/b/cover.jpg", b"other")

    await storage.delete_prefix("shows/a")

    assert await storage.get("shows/a/cover.jpg") is None
    assert await storage.get("shows/a/episodes/1/audio.mp3") is None
    assert await storage.get("shows/a/episodes/2/audio.mp3") is None
    assert await storage.get("shows/ab/cover.jpg") == b"sibling"
    assert await storage.get("shows/b/cover.jpg") == b"other"


async def test_delete_prefix_handles_more_than_one_page_of_objects(storage: Storage) -> None:
    for number in range(30):
        await storage.put(f"bulk/item-{number:02d}.txt", b"x")

    await storage.delete_prefix("bulk")

    assert not await storage.exists("bulk/item-00.txt")
    assert not await storage.exists("bulk/item-29.txt")


async def test_deleting_a_prefix_with_nothing_under_it_is_fine(storage: Storage) -> None:
    await storage.delete_prefix("shows/none")


@pytest.mark.parametrize(
    "key", ["", "/abs", "../x", "a/../../x", "a//b", "a/./b", "a\\b", "a/\x00b", "."]
)
async def test_unsafe_keys_are_rejected_everywhere(storage: Storage, key: str) -> None:
    with pytest.raises(ValueError):
        await storage.put(key, b"x")
    with pytest.raises(ValueError):
        await storage.get(key)
    with pytest.raises(ValueError):
        await storage.head(key)
    with pytest.raises(ValueError):
        await storage.delete(key)
    with pytest.raises(ValueError):
        await storage.delete_prefix(key)
    with pytest.raises(ValueError):
        await storage.url_for(key)


async def test_url_for_is_a_working_direct_link_or_none(storage: Storage) -> None:
    await storage.put("shows/a/cover.jpg", b"image-bytes", content_type="image/jpeg")

    url = await storage.url_for("shows/a/cover.jpg", expires_in=60)

    if url is None:  # local storage: the API serves the bytes
        return
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
    assert response.status_code == 200
    assert response.content == b"image-bytes"


async def test_files_go_in_and_out_without_being_read_into_memory(
    storage: Storage, tmp_path: Path
) -> None:
    source = tmp_path / "episode.mp3"
    payload = bytes(range(256)) * 4096  # 1 MB
    source.write_bytes(payload)

    await storage.put_file("shows/a/episode.mp3", source, content_type="audio/mpeg")

    assert await storage.get("shows/a/episode.mp3") == payload
    info = await storage.head("shows/a/episode.mp3")
    assert info is not None and info.size == len(payload) and info.content_type == "audio/mpeg"
    copy = tmp_path / "copy.mp3"
    assert await storage.get_file("shows/a/episode.mp3", copy) is True
    assert copy.read_bytes() == payload


async def test_put_file_replaces_and_get_file_reports_a_missing_object(
    storage: Storage, tmp_path: Path
) -> None:
    first, second = tmp_path / "one", tmp_path / "two"
    first.write_bytes(b"one")
    second.write_bytes(b"second")

    await storage.put_file("a/file.bin", first)
    await storage.put_file("a/file.bin", second)

    assert await storage.get("a/file.bin") == b"second"
    target = tmp_path / "out"
    assert await storage.get_file("a/missing.bin", target) is False
    assert not target.exists()


async def test_file_keys_are_validated_too(storage: Storage, tmp_path: Path) -> None:
    source = tmp_path / "f"
    source.write_bytes(b"x")

    with pytest.raises(ValueError):
        await storage.put_file("../escape", source)
    with pytest.raises(ValueError):
        await storage.get_file("/abs", tmp_path / "out")
