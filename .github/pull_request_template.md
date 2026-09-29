## Change

## User impact

## Tests run
- [ ] CI green (`test`, `hygiene`, `image-app`, `image-worker`)
- [ ] `cd api && pytest -q`
- [ ] `python -m compileall api/app api/worker.py`
- [ ] `node --check web/assets/app.js`
- [ ] Frontend changed: 1920×1080 four-view layout + maximize/minimize/restore checked

## LiDAR / CRS impact
- [ ] None
- [ ] Tested against representative non-production data
- [ ] Compared with MicroStation/TerraScan where profile logic changed

## Environment / data impact
- [ ] Target branch is `staging` (feature work) or this is a `staging` → `main` promotion
- [ ] No production secrets/data in this PR
- [ ] No Dockerfile PDAL/GDAL/SQLite pin changes, or they are explained below
- [ ] Backward compatible
- [ ] Migration included and reviewed
- [ ] New/changed Railway variables listed below (names only, never values)

## Staging evidence (promotion PRs only)
- Staging deployment ID / commit SHA:
- Verify deployment run:

## Rollback
