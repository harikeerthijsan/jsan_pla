"""Canonical v4 domain entities for staging-first migration."""
from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

def utcnow():
    return datetime.now(timezone.utc)

class SourceRecord(Base):
    __tablename__ = "v4_source_records"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    snapshot_id: Mapped[str] = mapped_column(String(120), index=True)
    sheet_name: Mapped[str] = mapped_column(String(120))
    row_number: Mapped[int] = mapped_column(Integer)
    pole_number: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    source_internal_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("project_id","snapshot_id","sheet_name","row_number",name="uq_v4_source_row"),)

class EngineeringAsset(Base):
    __tablename__ = "v4_engineering_assets"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    source_record_id: Mapped[str | None] = mapped_column(ForeignKey("v4_source_records.id"), nullable=True, index=True)
    asset_type: Mapped[str] = mapped_column(String(40), default="POLE", index=True)
    pole_number: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    internal_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    production_state: Mapped[str] = mapped_column(String(40), default="NOT_STARTED", index=True)
    evidence_state: Mapped[str] = mapped_column(String(40), default="UNASSESSED", index=True)
    qc_state: Mapped[str] = mapped_column(String(40), default="NOT_REVIEWED", index=True)
    release_state: Mapped[str] = mapped_column(String(40), default="NOT_ELIGIBLE", index=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class AssetGeometry(Base):
    __tablename__ = "v4_asset_geometries"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("v4_engineering_assets.id"), index=True)
    geometry_role: Mapped[str] = mapped_column(String(40), index=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    elev_ft: Mapped[float | None] = mapped_column(Float, nullable=True)
    crs: Mapped[str] = mapped_column(String(80), default="EPSG:4326")
    evidence_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

class Run(Base):
    __tablename__ = "v4_runs"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    snapshot_id: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(40), default="DRAFT", index=True)

class RunNode(Base):
    __tablename__ = "v4_run_nodes"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("v4_runs.id"), index=True)
    node_type: Mapped[str] = mapped_column(String(40), index=True)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("v4_engineering_assets.id"), nullable=True, index=True)
    sequence_hint: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    elev_ft: Mapped[float | None] = mapped_column(Float, nullable=True)

class RunEdge(Base):
    __tablename__ = "v4_run_edges"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("v4_runs.id"), index=True)
    from_node_id: Mapped[str] = mapped_column(ForeignKey("v4_run_nodes.id"), index=True)
    to_node_id: Mapped[str] = mapped_column(ForeignKey("v4_run_nodes.id"), index=True)
    trace_id: Mapped[str] = mapped_column(String(120), index=True)
    trace_class: Mapped[str] = mapped_column(String(60), default="COMM")
    owner: Mapped[str | None] = mapped_column(String(180), nullable=True)

class RulePack(Base):
    __tablename__ = "v4_rule_packs"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), default="DRAFT", index=True)
    configuration_json: Mapped[str] = mapped_column(Text, default="{}")

class RuleDefinition(Base):
    __tablename__ = "v4_rule_definitions"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    rule_pack_id: Mapped[str] = mapped_column(ForeignKey("v4_rule_packs.id"), index=True)
    family: Mapped[str] = mapped_column(String(60), index=True)
    title: Mapped[str] = mapped_column(String(240))
    automation_class: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(40), index=True)
    blocking: Mapped[bool] = mapped_column(Boolean, default=False)
    source_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluator: Mapped[str] = mapped_column(String(160))
    parameters_json: Mapped[str] = mapped_column(Text, default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

class ValidationResult(Base):
    __tablename__ = "v4_validation_results"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    snapshot_id: Mapped[str] = mapped_column(String(120), index=True)
    rule_id: Mapped[str] = mapped_column(ForeignKey("v4_rule_definitions.id"), index=True)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("v4_engineering_assets.id"), nullable=True, index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("v4_runs.id"), nullable=True, index=True)
    outcome: Mapped[str] = mapped_column(String(40), index=True)
    message: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class EngineeringAmendment(Base):
    __tablename__ = "v4_engineering_amendments"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("v4_engineering_assets.id"), nullable=True, index=True)
    field_path: Mapped[str] = mapped_column(String(240))
    before_json: Mapped[str] = mapped_column(Text, default="null")
    after_json: Mapped[str] = mapped_column(Text, default="null")
    reason: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class Release(Base):
    __tablename__ = "v4_releases"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    snapshot_id: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(40), default="CANDIDATE", index=True)
    manifest_json: Mapped[str] = mapped_column(Text, default="{}")
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
