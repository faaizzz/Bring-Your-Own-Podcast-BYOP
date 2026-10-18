# Backup and restore

State lives in three places. Back up all three together:

| What | Where | Why |
| --- | --- | --- |
| The database | the `postgres` volume | shows, runs, episodes, usage, encrypted provider keys |
| The media | the `media` volume, or your S3 bucket | episode audio, covers, branding clips |
| `BYOP_SECRET_KEY` and `.env` | your `.env` | decrypts the stored provider keys; without it you must enter them again |

Redis holds only caches and queues; nothing in it needs backing up (a run that was in progress when
you stop is failed by the reaper after `RUN_TIMEOUT_MINUTES`).

## Back up

From the project directory, with the stack running:

```sh
mkdir -p backup
# 1. the database (a plain SQL dump; restorable on any PostgreSQL 16)
docker compose exec -T postgres pg_dump -U byop -d byop --no-owner > backup/byop.sql
# 2. local media (skip with STORAGE_BACKEND=s3: back up the bucket with your provider's tools)
docker compose exec -T api tar -C /data/media -cf - . > backup/media.tar
# 3. your configuration
cp .env backup/env
```

Use `POSTGRES_USER` / `POSTGRES_DB` from your `.env` if you changed them. Keep `backup/env` somewhere
safe: it holds secrets. To automate it, run the three commands from cron and rotate the files.

## Restore

On a new machine (or after `make down` and deleting the volumes), with the same project files:

```sh
cp backup/env .env
docker compose up -d postgres redis                      # database first
docker compose exec -T postgres psql -U byop -d byop < backup/byop.sql
docker compose up -d --build                             # api migrates anything newer
docker compose exec -T api tar -C /data/media -xf - < backup/media.tar
```

Then sign in. If the restored database is from an older version of BYOP, starting the API upgrades
it (`alembic upgrade head`). Restoring into a database that already has tables fails; start from an
empty one (`docker compose down -v` deletes the volumes, so only do that on the machine you are
restoring to).

Check: the shows are there, an episode plays, **Settings › Integrations › Test connection**
succeeds. If the providers show *Error*, `BYOP_SECRET_KEY` differs from the one the backup was made
with: put the original back, or enter the keys again.

## Moving media to S3 later

Copy the files under `shows/` to the bucket with the same keys (`aws s3 sync` from the extracted
`media.tar`), set `STORAGE_BACKEND=s3` and the `S3_*` values, restart ([storage](storage.md)).
