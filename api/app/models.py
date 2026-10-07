from datetime import datetime, timezone
from sqlalchemy import String, Integer, Float, Text, DateTime, ForeignKey, UniqueConstraint, BigInteger, Boolean, false, true
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def now_utc():
    return datetime.now(timezone.utc)

def iso_utc(value):
    """ISO 8601 with an explicit UTC offset. SQLite returns naive datetimes; they are stored as UTC."""
    if value is None:
        return None
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)).isoformat()

class User(Base):
    __tablename__='users'
    id: Mapped[int]=mapped_column(Integer, primary_key=True)
    email: Mapped[str]=mapped_column(String(255), unique=True, index=True)
    username: Mapped[str|None]=mapped_column(String(80), unique=True, index=True, nullable=True)
    name: Mapped[str]=mapped_column(String(255), default='Reviewer')
    role: Mapped[str]=mapped_column(String(40), default='QC_REVIEWER')
    password_hash: Mapped[str]=mapped_column(Text)
    must_change_password: Mapped[bool]=mapped_column(Boolean, default=False, server_default=false())
    # Bumped on password change/reset or deactivation; tokens carrying an older value are refused.
    token_version: Mapped[int]=mapped_column(Integer, default=0, server_default='0')
    is_active: Mapped[bool]=mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now_utc)

class Project(Base):
    __tablename__='projects'
    id: Mapped[str]=mapped_column(String(80), primary_key=True)
    name: Mapped[str]=mapped_column(String(255))
    customer: Mapped[str]=mapped_column(String(255), default='PLA')
    crs: Mapped[str]=mapped_column(String(80), default='EPSG:6424')
    units: Mapped[str]=mapped_column(String(80), default='US survey foot')
    status: Mapped[str]=mapped_column(String(40), default='UPLOADING')
    source_workbook_key: Mapped[str|None]=mapped_column(Text, nullable=True)
    # Set on a QC dataset created from a Production dataset; it shares that dataset's converted LiDAR.
    source_project_id: Mapped[str|None]=mapped_column(String(80), nullable=True, index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

class DatasetFile(Base):
    __tablename__='dataset_files'
    id: Mapped[str]=mapped_column(String(120), primary_key=True)
    project_id: Mapped[str]=mapped_column(ForeignKey('projects.id'), index=True)
    filename: Mapped[str]=mapped_column(String(500))
    role: Mapped[str]=mapped_column(String(40))  # WORKBOOK, LIDAR_SOURCE, COPC
    object_key: Mapped[str]=mapped_column(Text)
    content_type: Mapped[str|None]=mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int|None]=mapped_column(BigInteger, nullable=True)
    status: Mapped[str]=mapped_column(String(40), default='PENDING')
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now_utc)

class ProcessingJob(Base):
    __tablename__='processing_jobs'
    id: Mapped[str]=mapped_column(String(120), primary_key=True)
    project_id: Mapped[str]=mapped_column(ForeignKey('projects.id'), index=True)
    job_type: Mapped[str]=mapped_column(String(40), default='INGEST', index=True)
    payload_json: Mapped[str]=mapped_column(Text, default='{}')
    result_key: Mapped[str|None]=mapped_column(Text, nullable=True)
    status: Mapped[str]=mapped_column(String(40), default='QUEUED', index=True)
    progress: Mapped[int]=mapped_column(Integer, default=0)
    stage: Mapped[str]=mapped_column(String(120), default='Queued')
    message: Mapped[str|None]=mapped_column(Text, nullable=True)
    error: Mapped[str|None]=mapped_column(Text, nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now_utc)
    started_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True), nullable=True)

class LidarBlock(Base):
    __tablename__='lidar_blocks'
    id: Mapped[int]=mapped_column(Integer, primary_key=True)
    project_id: Mapped[str]=mapped_column(ForeignKey('projects.id'), index=True)
    name: Mapped[str]=mapped_column(String(160), index=True)
    source_object_key: Mapped[str|None]=mapped_column(Text, nullable=True)
    object_key: Mapped[str]=mapped_column(Text)
    point_count: Mapped[int|None]=mapped_column(BigInteger, nullable=True)
    x_min: Mapped[float]=mapped_column(Float)
    y_min: Mapped[float]=mapped_column(Float)
    x_max: Mapped[float]=mapped_column(Float)
    y_max: Mapped[float]=mapped_column(Float)
    zmin: Mapped[float|None]=mapped_column(Float, nullable=True)
    zmax: Mapped[float|None]=mapped_column(Float, nullable=True)
    poles_json: Mapped[str]=mapped_column(Text, default='[]')
    __table_args__=(UniqueConstraint('project_id','name',name='uq_project_block'),)

class ProductionAnnotation(Base):
    __tablename__='production_annotations'
    id: Mapped[str]=mapped_column(String(120), primary_key=True)
    project_id: Mapped[str]=mapped_column(ForeignKey('projects.id'), index=True)
    block_name: Mapped[str]=mapped_column(String(160), index=True)
    family: Mapped[str]=mapped_column(String(160), index=True)
    feature_type: Mapped[str]=mapped_column(String(160), index=True)
    x: Mapped[float]=mapped_column(Float)
    y: Mapped[float]=mapped_column(Float)
    z: Mapped[float]=mapped_column(Float)
    latitude: Mapped[float|None]=mapped_column(Float, nullable=True)
    longitude: Mapped[float|None]=mapped_column(Float, nullable=True)
    pole_internal_id: Mapped[int|None]=mapped_column(Integer, nullable=True, index=True)
    reference_annotation_id: Mapped[str|None]=mapped_column(String(120), nullable=True, index=True)
    vertical_delta: Mapped[float|None]=mapped_column(Float, nullable=True)
    horizontal_offset: Mapped[float|None]=mapped_column(Float, nullable=True)
    distance_3d: Mapped[float|None]=mapped_column(Float, nullable=True)
    attributes_json: Mapped[str]=mapped_column(Text, default='{}')
    status: Mapped[str]=mapped_column(String(40), default='IN_PROGRESS', index=True)
    # Increments on every edit so a save based on an older copy is refused instead of overwriting.
    revision: Mapped[int]=mapped_column(Integer, default=1, server_default='1')
    created_by: Mapped[str]=mapped_column(String(255))
    modified_by: Mapped[str]=mapped_column(String(255))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

class ProductionGeoFeature(Base):
    __tablename__='production_geo_features'
    id: Mapped[int]=mapped_column(Integer, primary_key=True)
    project_id: Mapped[str]=mapped_column(ForeignKey('projects.id'), index=True)
    source_file_id: Mapped[str]=mapped_column(String(120), index=True)
    feature_index: Mapped[int]=mapped_column(Integer)
    geometry_type: Mapped[str]=mapped_column(String(40), index=True)
    source_crs: Mapped[str]=mapped_column(String(80))
    source_geometry_json: Mapped[str]=mapped_column(Text)
    geometry_json: Mapped[str]=mapped_column(Text)  # transformed to the project CRS
    x: Mapped[float|None]=mapped_column(Float, nullable=True)
    y: Mapped[float|None]=mapped_column(Float, nullable=True)
    properties_json: Mapped[str]=mapped_column(Text, default='{}')
    pole_internal_id: Mapped[int|None]=mapped_column(Integer, nullable=True, index=True)
    match_method: Mapped[str|None]=mapped_column(String(20), nullable=True)  # ID, NEAREST
    match_property: Mapped[str|None]=mapped_column(String(160), nullable=True)
    match_distance: Mapped[float|None]=mapped_column(Float, nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now_utc)

class Pole(Base):
    __tablename__='poles'
    id: Mapped[int]=mapped_column(Integer, primary_key=True)
    project_id: Mapped[str]=mapped_column(ForeignKey('projects.id'), index=True)
    internal_id: Mapped[int]=mapped_column(Integer, index=True)
    pole_number: Mapped[str|None]=mapped_column(String(120), nullable=True)
    block_name: Mapped[str|None]=mapped_column(String(160), nullable=True)
    corrected_lat: Mapped[float|None]=mapped_column(Float, nullable=True)
    corrected_lon: Mapped[float|None]=mapped_column(Float, nullable=True)
    verified_lat: Mapped[float|None]=mapped_column(Float, nullable=True)
    verified_lon: Mapped[float|None]=mapped_column(Float, nullable=True)
    verified_x: Mapped[float|None]=mapped_column(Float, nullable=True)
    verified_y: Mapped[float|None]=mapped_column(Float, nullable=True)
    verified_z: Mapped[float|None]=mapped_column(Float, nullable=True)
    verified_bottom_elevation: Mapped[float|None]=mapped_column(Float, nullable=True)
    verified_top_elevation: Mapped[float|None]=mapped_column(Float, nullable=True)
    verified_height: Mapped[float|None]=mapped_column(Float, nullable=True)
    verified_block_name: Mapped[str|None]=mapped_column(String(160), nullable=True)
    verified_annotation_id: Mapped[str|None]=mapped_column(String(120), nullable=True)
    verified_bottom_annotation_id: Mapped[str|None]=mapped_column(String(120), nullable=True)
    verified_top_annotation_id: Mapped[str|None]=mapped_column(String(120), nullable=True)
    location_verified_by: Mapped[str|None]=mapped_column(String(255), nullable=True)
    location_verified_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True), nullable=True)
    bottom_elev_ft: Mapped[float|None]=mapped_column(Float, nullable=True)
    top_elev_ft: Mapped[float|None]=mapped_column(Float, nullable=True)
    qc_status: Mapped[str]=mapped_column(String(40), default='PASS')
    qc_fail: Mapped[int]=mapped_column(Integer, default=0)
    qc_review: Mapped[int]=mapped_column(Integer, default=0)
    qc_unverifiable: Mapped[int]=mapped_column(Integer, default=0)
    remarks: Mapped[str|None]=mapped_column(Text, nullable=True)
    manifest_json: Mapped[str]=mapped_column(Text, default='{}')
    __table_args__=(UniqueConstraint('project_id','internal_id',name='uq_project_internal'),)

class Finding(Base):
    __tablename__='findings'
    id: Mapped[str]=mapped_column(String(120), primary_key=True)
    project_id: Mapped[str]=mapped_column(ForeignKey('projects.id'), index=True)
    rule_id: Mapped[str]=mapped_column(String(80), index=True)
    severity: Mapped[str]=mapped_column(String(40), index=True)
    internal_id: Mapped[int]=mapped_column(Integer, index=True)
    pole_number: Mapped[str|None]=mapped_column(String(120), nullable=True)
    sheet: Mapped[str]=mapped_column(String(120))
    field: Mapped[str]=mapped_column(String(160))
    message: Mapped[str]=mapped_column(Text)
    actual: Mapped[str|None]=mapped_column(Text, nullable=True)
    expected: Mapped[str|None]=mapped_column(Text, nullable=True)
    related_poles_json: Mapped[str]=mapped_column(Text, default='[]')
    status: Mapped[str]=mapped_column(String(40), default='OPEN')

class SceneFeature(Base):
    __tablename__='scene_features'
    id: Mapped[int]=mapped_column(Integer, primary_key=True)
    project_id: Mapped[str]=mapped_column(ForeignKey('projects.id'), index=True)
    internal_id: Mapped[int]=mapped_column(Integer, index=True)
    feature_type: Mapped[str]=mapped_column(String(60), index=True)
    payload_json: Mapped[str]=mapped_column(Text)

class ReviewDecision(Base):
    __tablename__='review_decisions'
    id: Mapped[int]=mapped_column(Integer, primary_key=True)
    finding_id: Mapped[str]=mapped_column(ForeignKey('findings.id'), index=True)
    reviewer_email: Mapped[str]=mapped_column(String(255))
    decision: Mapped[str]=mapped_column(String(60))
    comment: Mapped[str|None]=mapped_column(Text, nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now_utc)

class AuditLog(Base):
    __tablename__='audit_logs'
    id: Mapped[int]=mapped_column(Integer, primary_key=True)
    actor: Mapped[str]=mapped_column(String(255))
    action: Mapped[str]=mapped_column(String(120))
    entity_type: Mapped[str]=mapped_column(String(80))
    entity_id: Mapped[str]=mapped_column(String(160))
    detail_json: Mapped[str]=mapped_column(Text, default='{}')
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now_utc)

class PoleAssignment(Base):
    """Which user a pole is assigned to in a Production dataset. Guidance only: it does not lock the pole."""
    __tablename__='pole_assignments'
    id: Mapped[int]=mapped_column(Integer, primary_key=True)
    project_id: Mapped[str]=mapped_column(ForeignKey('projects.id'))
    pole_internal_id: Mapped[int]=mapped_column(Integer)
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id'))
    assigned_by: Mapped[str]=mapped_column(String(255))
    assigned_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now_utc)
    __table_args__=(UniqueConstraint('project_id','pole_internal_id',name='uq_pole_assignment'),)

class PolePresence(Base):
    """Heartbeat of the pole each person has open, so others see "Open by …"."""
    __tablename__='pole_presence'
    id: Mapped[int]=mapped_column(Integer, primary_key=True)
    project_id: Mapped[str]=mapped_column(ForeignKey('projects.id'))
    user_email: Mapped[str]=mapped_column(String(255))
    pole_internal_id: Mapped[int|None]=mapped_column(Integer, nullable=True)
    last_seen: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now_utc)
    __table_args__=(UniqueConstraint('project_id','user_email',name='uq_pole_presence_user'),)

class Notification(Base):
    """In-app notification for one user; read_at is set when they open or dismiss it."""
    __tablename__='notifications'
    id: Mapped[int]=mapped_column(Integer, primary_key=True)
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id'))
    kind: Mapped[str]=mapped_column(String(60))
    title: Mapped[str]=mapped_column(String(300))
    body: Mapped[str|None]=mapped_column(Text, nullable=True)
    project_id: Mapped[str|None]=mapped_column(String(80), nullable=True)
    pole_internal_id: Mapped[int|None]=mapped_column(Integer, nullable=True)
    link_json: Mapped[str]=mapped_column(Text, default='{}')
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now_utc)
    read_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True), nullable=True)
