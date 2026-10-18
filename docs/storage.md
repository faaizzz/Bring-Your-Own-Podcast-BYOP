# Media storage

Covers, previews and (later) episode audio live in object storage behind one interface,
`byop.storage.Storage` (`put`, `get`, `get_stream` (whole object or an inclusive byte range), `head`, `exists`, `delete`,
`delete_prefix`, `url_for`). Keys are paths; everything a show owns is under
`shows/<show id>/`, so deleting a show removes that prefix on any backend.

## Backends

| `STORAGE_BACKEND` | Where files live |
| --- | --- |
| `local` (default) | Files below `MEDIA_ROOT` (the `media` volume in compose). |
| `s3` | Any S3-compatible service: AWS S3, MinIO, RustFS, Cloudflare R2, ... |

For `s3` set `S3_BUCKET`, `S3_ACCESS_KEY_ID` and `S3_SECRET_ACCESS_KEY` (startup fails with a
clear message if one is missing), plus `S3_ENDPOINT_URL` for anything that is not AWS and
`S3_REGION` if it matters. With an endpoint URL the client uses path-style addressing
and creates the bucket on first write if it does not exist (never on AWS). `S3_PUBLIC_ENDPOINT_URL`
is for presigned links handed to browsers when the server is reachable under another name than
`S3_ENDPOINT_URL` (for example `http://s3:9000` inside Docker, `http://localhost:9000` outside).

### Trying S3 locally: the `minio` profile

```sh
make up-minio          # or: docker compose --profile minio up -d
```

starts an S3-compatible server (service `s3`, `http://s3:9000` inside the compose network,
data in the `s3data` volume). Then in `.env`:

```sh
STORAGE_BACKEND=s3
S3_ENDPOINT_URL=http://s3:9000
S3_BUCKET=byop
S3_ACCESS_KEY_ID=byop-local
S3_SECRET_ACCESS_KEY=byop-local-secret   # the service reads the same two variables
```

and `docker compose up -d` to restart the api and worker. Change the secret before exposing
the service anywhere. The profile keeps the name `minio`, but the image is
[RustFS](https://github.com/rustfs/rustfs) (Apache-2.0, S3 API compatible, pinned by tag and
digest) because MinIO no longer publishes container images; anything that speaks S3 works the
same, so you can also point `S3_ENDPOINT_URL` at a MinIO you run yourself.

Switching backends does not move existing files; copy them first (for example with `rclone`
or `aws s3 sync` from the media volume to the bucket, keeping the key layout).

## Tests

`tests/storage/` runs one contract suite against all backends: local files, S3 through an
in-process mock server (`moto`), and a real S3-compatible container started with
testcontainers. The container variant is skipped when Docker is not available.

## Covers

`POST /api/shows/{id}/cover` takes a multipart `file` (PNG or JPEG, at most 10 MB, at least
600×600 pixels). It is centre-cropped to a square, scaled to between 1400 and 3000 pixels
(what podcast directories require), flattened onto white if it has transparency, stripped of
metadata and stored as `shows/<id>/cover.jpg`. Anything else is rejected with a message that
says why (`422`; `413` for oversized files). `DELETE` removes it.

`GET /api/shows/{id}/cover` is public (feeds and directories fetch it without a session) and
streams from storage. Show responses carry `cover_url`, a versioned URL
(`/api/shows/<id>/cover?v=<timestamp>`) so changing the cover busts caches.
