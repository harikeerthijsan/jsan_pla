"""Versioned v4 baseline rule catalogue and deterministic evaluators."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable

@dataclass(frozen=True)
class RuleSpec:
    id: str
    family: str
    title: str
    automation_class: str
    severity: str
    blocking: bool
    evaluator: str
    source_reference: str

RULES: tuple[RuleSpec, ...] = (
    RuleSpec("SRC-001","SOURCE","Source row retained","DETERMINISTIC","CRITICAL",True,"source_row_retained","QC Process §1"),
    RuleSpec("ID-001","SEQUENCE","Measured internal IDs are sequential","DETERMINISTIC","CRITICAL",True,"internal_ids_sequential","QC Process §3"),
    RuleSpec("ID-002","SEQUENCE","Maximum 150 internal IDs per file","DETERMINISTIC","CRITICAL",True,"internal_id_limit","QC Process §3"),
    RuleSpec("ID-003","IDENTITY","Unmeasured pole has no internal ID","DETERMINISTIC","CRITICAL",True,"unmeasured_without_internal_id","QC Process §7"),
    RuleSpec("TOPO-001","RUN","Run has no orphan measured segment","DETERMINISTIC","CRITICAL",True,"run_has_no_orphans","QC Process §4"),
    RuleSpec("TOPO-002","RUN","Yes endpoint requires dead-end topology","EVIDENCE_ASSISTED","CRITICAL",True,"yes_requires_deadend","QC Process §4"),
    RuleSpec("INC-001","INCOMPLETE","Incomplete endpoint has XYZ","DETERMINISTIC","CRITICAL",True,"incomplete_has_xyz","SOW §3.1.2"),
    RuleSpec("GEO-001","GEOMETRY","Pole coordinate agrees with LiDAR evidence","EVIDENCE_ASSISTED","MAJOR",True,"coordinate_displacement","QC Process §6"),
    RuleSpec("COV-001","COVERAGE","LiDAR-missing state agrees with coverage","EVIDENCE_ASSISTED","MAJOR",True,"lidar_missing_coverage","QC Process §7"),
    RuleSpec("TRACE-001","TRACE","Communication trace continuity preserved","EVIDENCE_ASSISTED","CRITICAL",True,"trace_continuity","QC Process §8"),
    RuleSpec("OWNER-001","OWNER","Connected trace owner follows validated majority","EVIDENCE_ASSISTED","MAJOR",True,"owner_majority","QC Process §8"),
    RuleSpec("LUT-001","LUT","Support values belong to approved LUT","DETERMINISTIC","MAJOR",True,"support_lut","QC Process §9"),
    RuleSpec("GUY-001","GUY","Guy references an existing anchor","DETERMINISTIC","MAJOR",True,"guy_anchor_reference","SOW §3.6"),
    RuleSpec("BRACE-001","BRACE","Sidewalk brace references guy(s) and anchor","DETERMINISTIC","MAJOR",True,"brace_references","SOW §3.7"),
    RuleSpec("SPAN-001","SPAN","Span-guy endpoints are reciprocal Support/Load","DETERMINISTIC","MAJOR",True,"span_reciprocal","SOW §3.8"),
    RuleSpec("LINEAGE-001","LINEAGE","Working attachment retains source-slot provenance","DETERMINISTIC","CRITICAL",True,"attachment_lineage","QC Process §8-9"),
    RuleSpec("REL-001","RELEASE","No unresolved blocking validation results","DETERMINISTIC","CRITICAL",True,"release_blockers","v4 release policy"),
)

def internal_ids_sequential(records: list[dict[str, Any]]) -> tuple[bool, dict[str, Any]]:
    ids = sorted(int(r["internal_id"]) for r in records if r.get("internal_id") is not None)
    if not ids:
        return True, {"ids": []}
    expected = list(range(1, len(ids) + 1))
    return ids == expected, {"actual": ids, "expected": expected}

def internal_id_limit(records: list[dict[str, Any]], maximum: int = 150) -> tuple[bool, dict[str, Any]]:
    ids = [int(r["internal_id"]) for r in records if r.get("internal_id") is not None]
    return len(ids) <= maximum and all(1 <= x <= maximum for x in ids), {"count": len(ids), "maximum": maximum}

def unmeasured_without_internal_id(record: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    measured = bool(record.get("measurement_complete"))
    internal_id = record.get("internal_id")
    return measured or internal_id is None, {"measurement_complete": measured, "internal_id": internal_id}

def incomplete_has_xyz(record: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    checks = []
    for side, marker in (("prev", record.get("first_pole")), ("next", record.get("last_pole"))):
        if str(marker or "").strip().lower() == "incomplete":
            xyz = (record.get(f"{side}_inc_lat"), record.get(f"{side}_inc_lon"), record.get(f"{side}_inc_elev_ft"))
            checks.append((side, all(v is not None and v != "" for v in xyz), xyz))
    return all(x[1] for x in checks), {"endpoints": checks}

DETERMINISTIC_EVALUATORS: dict[str, Callable[..., tuple[bool, dict[str, Any]]]] = {
    "internal_ids_sequential": internal_ids_sequential,
    "internal_id_limit": internal_id_limit,
    "unmeasured_without_internal_id": unmeasured_without_internal_id,
    "incomplete_has_xyz": incomplete_has_xyz,
}
