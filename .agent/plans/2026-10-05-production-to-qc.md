# ExecPlan: QC on Production LiDAR with its own Excel, and Production Excel replacement

## Outcome

- QC never uses the Production Excel. From a Production dataset, "Run QC now" asks for a QC Excel and creates a linked QC dataset that shares the Production LiDAR (and, optionally, its GeoJSON) by reference. QC runs there; Production data is never written by QC.
- QC is never started automatically.
- In Production, "Replace Excel" swaps a wrongly imported workbook for the correct one and re-imports poles automatically.

## Current behavior (before this change)

- Production import (`LIDAR_INGEST`) converted LiDAR and imported the Production workbook; an interim build also queued QC on the Production Excel automatically.
- QC `INGEST` deleted and recreated poles and reconverted all LiDAR.
- A wrongly imported Production Excel could only be fixed by importing the whole dataset again.

## Constraints / invariants

- The Production Excel, poles, saved points, verification and GeoJSON are never modified by QC.
- Source files stay immutable: a replaced Excel and its editor revisions are marked `SUPERSEDED`, never deleted.
- Shared LiDAR is referenced, not copied or reconverted.
- `processing.run` starts QC; `upload.create` + `processing.run` replace a Production Excel.
- Additive migration only (`projects.source_project_id`).

## Design

1. `projects.source_project_id` (migration `20261005_0006`) links a QC dataset to its Production dataset.
2. A dataset that ran `LIDAR_INGEST` is a Production dataset. `POST /process` refuses it (409) so its Excel is never QC'd.
3. `POST /projects/{id}/qc-dataset` `{include_geojson}` creates (or returns) the linked QC dataset: new project and version, `LIDAR_SOURCE` (and optional `GEOJSON`) file records pointing at the same object keys, and copies of the `LidarBlock` rows (same COPC keys). The QC Excel is then uploaded through the normal upload flow and `/process` runs QC.
4. Processor: converted COPC is reused per source object; QC upserts poles instead of recreating; QC imports an attached GeoJSON (non-fatal); no automatic follow-up QC job.
5. `POST /projects/{id}/production-workbook/prepare` + `/{file_id}/apply`: upload the correct Excel without attaching it until applied; apply supersedes the current `WORKBOOK`/`WORKBOOK_EDITED`, attaches the new file and queues `LIDAR_INGEST`. The re-import removes poles that are no longer in the Excel unless they have saved points or verification (kept and reported).
6. `/summary` reports `production_dataset`, `qc_dataset`, `source_project`, `has_geojson`, `qc_runs`, `qc_job_id`; the QC banner uses them (Run QC now → Excel dialog, Open QC dataset, Upload QC Excel / Run QC now on a waiting QC dataset, progress while running).

## Decision log

- 2026-10-05: First build ran QC on the Production dataset and auto-queued it after import. Superseded at the user's direction: QC uses its own Excel, LiDAR (and optionally GeoJSON) is linked, nothing is automatic.
- 2026-10-05: A separate linked QC dataset was chosen over a second workbook on the same dataset because poles are shared per dataset; a QC Excel would otherwise overwrite Production poles.
- 2026-10-05: QC results that Sample2 received from its Production Excel were removed; Production data verified unchanged.

## Progress

- [x] Schema, endpoints, processor, banner, Replace Excel dialog.
- [x] Tests: `test_production_qc.py` (no auto QC; Excel replacement keeps verified/annotated poles and supersedes old Excel + edits; QC dataset shares LiDAR, uses only its Excel, optional GeoJSON; `/process` refused on Production; unauthenticated/wrong-role/happy-path for each new action).
- [x] Browser end-to-end: Production import (no auto QC) → Replace Excel (27 → 22 poles) → QC tab Run QC now with QC Excel + GeoJSON → linked QC dataset with results → Production dataset links to it. Sample2 Production data and its four workbook edits unchanged.
- [ ] Staging with S3: confirm shared COPC keys resolve for the QC dataset and no LAS download occurs.
