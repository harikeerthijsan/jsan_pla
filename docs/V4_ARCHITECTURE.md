# JSAN PLA Engineering Operations Platform — v4.0

**Product promise:** Source-to-release engineering with evidence, automated validation, independent QC and immutable traceability.

## Architecture freeze
v4.0 is a domain-model reset, not a UI patch. The existing v3.4 synchronized Plan / Longitudinal Profile / Cross Section / 3D viewer is retained as the Engineering Evidence component.

## Non-negotiable design rules
1. Every source workbook row receives a permanent source_record_id even when internal_id is blank.
2. internal_id is a nullable run-sequence attribute, never the primary identity of a pole.
3. Excel is an import/export contract; PostgreSQL/PostGIS is the system of record.
4. Customer source files are immutable.
5. Engineering state changes create auditable snapshots/amendments rather than overwriting historical truth.
6. Run topology is modeled explicitly as nodes and edges.
7. Validation rules are versioned in rule packs and declare deterministic, evidence-assisted or engineering-decision behavior.
8. QC never directly edits production engineering values.
9. A release is generated only through a machine-enforced release gate and is immutable after creation.
10. Every delivered value must be traceable to source, transformation, evidence, actor, validation result and release.

## Workspaces
Operations | Production | Validation | QC | Release | Analytics | Admin

## Canonical identity model
- source_record_id: permanent identity for each source row
- asset_id: permanent JSAN identity for the physical/logical pole
- internal_id: nullable run order
- pole_number: customer/field identifier; not guaranteed unique
- trace_id: stable identity for a wire/communication trace
- snapshot_id: immutable engineering-state version
- rule_pack_id: exact validation specification applied
- release_id: immutable delivery identity

## Data flow
SOURCE -> INGEST & NORMALIZE -> ENGINEERING PRODUCTION -> CONTINUOUS VALIDATION -> INDEPENDENT QC -> RELEASE GATE -> IMMUTABLE DELIVERY

QC exceptions create amendments to canonical records. They do not create a parallel rework application.

## Preserve from v3.4
FastAPI, PostgreSQL, object storage, multipart upload, LAS/LAZ to COPC, PDAL sections, Potree 3D, synchronized evidence views, worker leases/heartbeats and named-user RBAC.

## Replace
internal_id-as-identity assumptions, dropping no-ID source rows, hard-coded QC rules, single qc_status, correction/revision-as-workflow, and API+worker coupling.

## Release acceptance
No production promotion until Sample 1 and Sample 2 golden regressions, no-ID row round trip, lineage round trip, topology rules, profile parity, release gate, role isolation and migration rehearsal all pass.
