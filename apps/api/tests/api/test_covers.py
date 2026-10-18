import io
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import get_settings
from byop.services.covers import MAX_UPLOAD_BYTES, CoverInvalid, process_cover
from tests.helpers import make_settings
from tests.models.factories import make_show, make_user


def picture(
    size: tuple[int, int] = (2000, 1000),
    fmt: str = "PNG",
    mode: str = "RGB",
    color: object = (200, 30, 30),
) -> bytes:
    out = io.BytesIO()
    Image.new(mode, size, color).save(out, format=fmt)  # type: ignore[arg-type]
    return out.getvalue()


def open_result(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


@pytest.fixture(autouse=True)
def media(app: FastAPI, tmp_path: Path) -> Path:
    app.dependency_overrides[get_settings] = lambda: make_settings(media_root=str(tmp_path))
    return tmp_path


async def new_show(authed: AsyncClient) -> str:
    response = await authed.post("/api/shows", json={"title": "Daily AI", "topic": "AI"})
    return str(response.json()["id"])


async def upload(
    client: AsyncClient,
    show_id: str,
    data: bytes,
    name: str = "cover.png",
    content_type: str = "image/png",
) -> Response:
    return await client.post(
        f"/api/shows/{show_id}/cover", files={"file": (name, data, content_type)}
    )


# --- image processing ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        ((2000, 1000), 1400),  # cropped to 1000 square, scaled up to the minimum
        ((1500, 1500), 1500),  # already fine: kept
        ((1400, 2200), 1400),
        ((3600, 3400), 3000),  # scaled down to the maximum
        ((700, 650), 1400),  # small but acceptable: scaled up
    ],
)
def test_output_is_a_square_between_1400_and_3000(size: tuple[int, int], expected: int) -> None:
    result = open_result(process_cover(picture(size)))

    assert result.format == "JPEG"
    assert result.size == (expected, expected)


def test_the_crop_is_centred() -> None:
    image = Image.new("RGB", (2000, 1500), (255, 255, 255))
    image.paste((0, 0, 0), (0, 0, 250, 1500))  # a black stripe on the far left: cropped away
    out = io.BytesIO()
    image.save(out, format="PNG")

    result = open_result(process_cover(out.getvalue())).convert("RGB")

    # The 1500 px square starts at x=250, so the stripe is gone and the left edge is white.
    assert min(result.getpixel((2, 700))) > 240
    assert min(result.getpixel((1397, 700))) > 240


def test_transparency_is_flattened_onto_white() -> None:
    data = picture((1400, 1400), mode="RGBA", color=(255, 0, 0, 0))

    result = open_result(process_cover(data)).convert("RGB")

    assert min(result.getpixel((700, 700))) > 240


def test_palette_and_cmyk_images_become_rgb() -> None:
    assert open_result(process_cover(picture((800, 800), mode="P", color=3))).mode == "RGB"
    cmyk = picture((800, 800), fmt="JPEG", mode="CMYK", color=(0, 0, 0, 0))
    assert open_result(process_cover(cmyk)).mode == "RGB"


def test_exif_orientation_is_applied() -> None:
    image = Image.new("RGB", (900, 600), (0, 0, 255))
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° clockwise to display
    out = io.BytesIO()
    image.save(out, format="JPEG", exif=exif)

    result = open_result(process_cover(out.getvalue()))

    assert result.size == (1400, 1400)
    assert "exif" not in result.info  # metadata is not carried over


@pytest.mark.parametrize(
    ("data", "message"),
    [
        pytest.param(b"", "empty", id="empty"),
        pytest.param(b"not an image", "not a readable PNG or JPEG", id="garbage"),
        pytest.param(
            picture((800, 800), fmt="GIF", mode="P", color=1), "this file is GIF", id="gif"
        ),
        pytest.param(picture((800, 800), fmt="WEBP"), "this file is WEBP", id="webp"),
        pytest.param(picture((400, 900)), "too small (400x900)", id="too-small"),
        pytest.param(picture((1500, 1500))[:-200], "not a readable", id="truncated"),
    ],
)
def test_bad_images_get_a_clear_message(data: bytes, message: str) -> None:
    with pytest.raises(CoverInvalid, match=re.escape(message)):
        process_cover(data)


# --- API -----------------------------------------------------------------------------


async def test_upload_stores_a_processed_cover_served_publicly(
    authed: AsyncClient, client: AsyncClient, media: Path
) -> None:
    show_id = await new_show(authed)
    assert (await authed.get(f"/api/shows/{show_id}")).json()["cover_url"] is None

    response = await upload(authed, show_id, picture((2000, 1000)))

    assert response.status_code == 200
    url = response.json()["cover_url"]
    assert url.startswith(f"/api/shows/{show_id}/cover?v=")
    assert (media / "shows" / show_id / "cover.jpg").exists()

    # Anyone can fetch it: use a client without the session cookie.
    client.cookies.clear()
    fetched = await client.get(url)
    assert fetched.status_code == 200
    assert fetched.headers["content-type"] == "image/jpeg"
    assert fetched.headers["cache-control"] == "public, max-age=86400"
    assert int(fetched.headers["content-length"]) == len(fetched.content)
    assert open_result(fetched.content).size == (1400, 1400)


async def test_a_new_upload_replaces_the_cover(authed: AsyncClient) -> None:
    show_id = await new_show(authed)

    await upload(authed, show_id, picture((1500, 1500)))
    second = (await upload(authed, show_id, picture((1600, 1600), color=(0, 0, 0)))).json()[
        "cover_url"
    ]

    fetched = await authed.get(second)
    assert open_result(fetched.content).size == (1600, 1600)  # the newest upload is served


async def test_the_list_and_detail_carry_the_cover_url(authed: AsyncClient) -> None:
    show_id = await new_show(authed)
    await upload(authed, show_id, picture())

    listed = (await authed.get("/api/shows")).json()[0]
    detail = (await authed.get(f"/api/shows/{show_id}")).json()

    assert listed["cover_url"] == detail["cover_url"]
    assert detail["cover_url"] is not None


async def test_jpeg_uploads_work_regardless_of_the_declared_type(authed: AsyncClient) -> None:
    show_id = await new_show(authed)

    response = await upload(
        authed, show_id, picture((1500, 1500), fmt="JPEG"), "x.bin", "application/octet-stream"
    )

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("data", "text"),
    [
        pytest.param(b"not an image", "not a readable", id="garbage"),
        pytest.param(picture((800, 800), fmt="GIF", mode="P", color=1), "PNG or JPEG", id="gif"),
        pytest.param(picture((300, 300)), "too small", id="too-small"),
    ],
)
async def test_invalid_images_are_rejected_with_a_message(
    authed: AsyncClient, data: bytes, text: str
) -> None:
    show_id = await new_show(authed)

    response = await upload(authed, show_id, data)

    assert response.status_code == 422
    assert text in response.json()["detail"]
    assert (await authed.get(f"/api/shows/{show_id}")).json()["cover_url"] is None


async def test_oversized_uploads_are_rejected(authed: AsyncClient) -> None:
    show_id = await new_show(authed)

    response = await upload(authed, show_id, b"\x89PNG" + b"0" * (MAX_UPLOAD_BYTES + 10))

    assert response.status_code == 413
    assert "10 MB" in response.json()["detail"]


async def test_a_missing_file_field_is_a_validation_error(authed: AsyncClient) -> None:
    show_id = await new_show(authed)

    response = await authed.post(f"/api/shows/{show_id}/cover")

    assert response.status_code == 422


async def test_delete_removes_the_cover(authed: AsyncClient, media: Path) -> None:
    show_id = await new_show(authed)
    await upload(authed, show_id, picture())

    response = await authed.delete(f"/api/shows/{show_id}/cover")

    assert response.status_code == 200 and response.json()["cover_url"] is None
    assert not (media / "shows" / show_id / "cover.jpg").exists()
    assert (await authed.get(f"/api/shows/{show_id}/cover")).status_code == 404
    assert (await authed.delete(f"/api/shows/{show_id}/cover")).status_code == 200  # idempotent


async def test_a_show_without_a_cover_or_a_missing_show_is_404(
    authed: AsyncClient, client: AsyncClient
) -> None:
    show_id = await new_show(authed)
    client.cookies.clear()

    assert (await client.get(f"/api/shows/{show_id}/cover")).status_code == 404
    unknown = "00000000-0000-4000-8000-000000000000"
    assert (await client.get(f"/api/shows/{unknown}/cover")).status_code == 404
    assert (await client.get("/api/shows/not-a-uuid/cover")).status_code == 422


async def test_other_users_cannot_change_a_cover(
    authed: AsyncClient, db_session: AsyncSession
) -> None:
    other = await make_user(db_session, "other@example.com")
    theirs = await make_show(db_session, other, slug="theirs")

    assert (await upload(authed, str(theirs.id), picture())).status_code == 404
    assert (await authed.delete(f"/api/shows/{theirs.id}/cover")).status_code == 404


async def test_uploading_needs_a_session(client: AsyncClient) -> None:
    unknown = "00000000-0000-4000-8000-000000000000"

    assert (await upload(client, unknown, picture())).status_code == 401
    assert (await client.delete(f"/api/shows/{unknown}/cover")).status_code == 401


async def test_deleting_the_show_removes_its_cover(authed: AsyncClient, media: Path) -> None:
    show_id = await new_show(authed)
    await upload(authed, show_id, picture())

    await authed.delete(f"/api/shows/{show_id}")

    assert not (media / "shows" / show_id).exists()
