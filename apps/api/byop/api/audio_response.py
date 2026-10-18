from fastapi import HTTPException, Response, status
from fastapi.responses import StreamingResponse

from byop.services.byte_ranges import RangeNotSatisfiable, parse_range
from byop.storage import Storage, StorageError, StorageKeyNotFound

NO_AUDIO = "The episode has no audio yet"


async def audio_response(
    storage: Storage,
    key: str,
    range_header: str | None,
    *,
    cache_control: str,
    head: bool = False,
) -> Response:
    """An MP3 from storage, with `Range` support so players can seek (206 for a part).

    With `head` only the headers are sent, as a HEAD request expects.
    """
    try:
        info = await storage.head(key)
        if info is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, NO_AUDIO)
        try:
            wanted = parse_range(range_header, info.size)
        except RangeNotSatisfiable:
            return Response(
                status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
                headers={"Content-Range": f"bytes */{info.size}"},
            )
        headers = {"Accept-Ranges": "bytes", "Cache-Control": cache_control}
        if wanted is None:
            headers["Content-Length"] = str(info.size)
            code = status.HTTP_200_OK
        else:
            headers["Content-Length"] = str(wanted.length)
            headers["Content-Range"] = f"bytes {wanted.start}-{wanted.end}/{info.size}"
            code = status.HTTP_206_PARTIAL_CONTENT
        if head:
            return Response(status_code=code, media_type="audio/mpeg", headers=headers)
        if wanted is None:
            stream = storage.get_stream(key)
        else:
            stream = storage.get_stream(key, start=wanted.start, end=wanted.end)
    except StorageKeyNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_AUDIO) from exc
    except StorageError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Media storage is unavailable") from exc
    return StreamingResponse(stream, status_code=code, media_type="audio/mpeg", headers=headers)
