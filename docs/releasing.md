# Releases and upgrades

## Running a published release

Every release is published as multi-arch (amd64 and arm64) images on GitHub Container Registry:
`ghcr.io/faaizzz/byop-api` (api, worker and beat) and `ghcr.io/faaizzz/byop-web`, tagged with the
version (`0.1.0`), the minor (`0.1`) and `latest`. To run one instead of building from source, set
`BYOP_VERSION` in `.env` and use the production compose file on its own (without the development
override, which mounts the source):

```sh
echo "BYOP_VERSION=0.1.0" >> .env
docker compose -f docker-compose.yml pull
docker compose -f docker-compose.yml up -d
```

You only need `docker-compose.yml`, `.env` and the `docker/` folder for this; no source tree.
Without `BYOP_VERSION` the images are built from the checkout and tagged `local`.

## Upgrading

Back up first ([backup](backup.md)), then read the [changelog](../CHANGELOG.md) for anything that
needs your attention, set the new `BYOP_VERSION`, and run the same two commands. The API applies
database migrations when it starts, so there is nothing else to do. To go back, restore the backup
and the previous version (migrations are not reversed automatically).

## Cutting a release (maintainers)

1. Make sure `main` is green (CI, including the end-to-end test, and the audit).
2. Move the entries of the new version in `CHANGELOG.md` out of "unreleased": replace "unreleased" in
   the version heading with the date. The text of that section becomes the release notes
   (`scripts/release-notes.sh 0.1.0` prints it).
3. Make sure the versions in `apps/api/pyproject.toml` and `apps/web/package.json` match.
4. Tag and push: `git tag -a v0.1.0 -m "BYOP 0.1.0" && git push origin v0.1.0`.

The `Release` workflow then builds and publishes both images and creates the GitHub release from the
changelog. Run it by hand from the Actions tab with *Publish* off to test the multi-arch build
without publishing. After the first release make the two packages public (GitHub → Packages →
package settings → Change visibility) so that `docker compose pull` works without logging in.
Pre-release tags (`v0.2.0-rc.1`) are published without the `latest` tag and marked as pre-releases.

## Dependency audits

`pip-audit` (locked runtime dependencies of the API) and `npm audit --audit-level=high` (web) run in
the `Audit` workflow on every push, pull request and weekly. A finding of high severity or above
fails it; fix it by updating the dependency (and the lock file) rather than ignoring it.
