from __future__ import annotations

import json
import math

from fastapi import HTTPException
from pyproj import Transformer
from sqlalchemy.orm import Session

from .models import ProductionAnnotation


PRODUCTION_FAMILIES = {
    "Pole Points": [
        "Pole Top Point", "Pole Base / Ground Point", "Pole Center Point",
        "Pole Centerline Points", "Pole Face / Side Point", "Ground Reference Point",
    ],
    "Structural Points": [
        "Cross Arm Points", "Cross Arm Center Point", "Bracket Point",
        "Transformer Points", "Equipment Mount Point", "Guy Wire Point",
        "Anchor Point", "Riser Point", "Streetlight Attachment Point",
    ],
    "Electrical / Communication Attachment Points": [
        "Insulator Points", "Primary Conductor Points", "Secondary Conductor Points",
        "Neutral Point", "Communication Attachment Points", "Messenger Wire Point",
        "Drip Loop Point", "Span Connection Point",
    ],
    "Measurement / Clearance Points": [
        "Clearance Measurement Point", "Lowest Attachment Point", "Highest Attachment Point",
        "Ground Clearance Point", "Vegetation Clearance Point", "Road / Surface Reference Point",
    ],
}

PRODUCTION_STATUSES = {"NOT_STARTED", "IN_PROGRESS", "COMPLETED", "REWORK", "ON_HOLD", "SUBMITTED_FOR_QC"}

SECTION3_ATTRIBUTE_FIELDS = [
    "feature_id", "parent_feature_id", "pole_internal_id", "item_number", "asset_sub_type",
    "catalog_key", "owner", "arm_no", "usage", "support", "voltage", "anchor_no",
    "guy_nos", "runs_to", "end_type", "environment", "construction_grade", "remarks",
]


def catalogue() -> dict:
    return {
        "families": [{"name": family, "point_types": points} for family, points in PRODUCTION_FAMILIES.items()],
        "statuses": sorted(PRODUCTION_STATUSES),
        "attribute_fields": SECTION3_ATTRIBUTE_FIELDS,
        "measurement_fields": ["vertical_delta", "horizontal_offset", "distance_3d"],
    }


def validate_annotation_values(family: str, feature_type: str, status: str, attributes: dict) -> None:
    if family not in PRODUCTION_FAMILIES:
        raise HTTPException(422, "Unsupported production family")
    if feature_type not in PRODUCTION_FAMILIES[family]:
        raise HTTPException(422, "Point type does not belong to the selected production family")
    if status not in PRODUCTION_STATUSES:
        raise HTTPException(422, "Unsupported production status")
    unknown = sorted(set(attributes) - set(SECTION3_ATTRIBUTE_FIELDS))
    if unknown:
        raise HTTPException(422, f"Unsupported production attribute(s): {', '.join(unknown)}")
    if len(json.dumps(attributes, default=str)) > 20000:
        raise HTTPException(413, "Production attributes exceed the allowed size")


def validate_coordinates(x: float, y: float, z: float) -> None:
    if not all(math.isfinite(value) for value in (x, y, z)):
        raise HTTPException(422, "Annotation coordinates must be finite numbers")


def project_to_wgs84(project_crs: str, x: float, y: float) -> tuple[float, float]:
    try:
        longitude, latitude = Transformer.from_crs(project_crs, "EPSG:4326", always_xy=True).transform(x, y)
    except Exception as exc:
        raise HTTPException(422, f"Project CRS cannot be transformed to WGS84: {project_crs}") from exc
    if not math.isfinite(latitude) or not math.isfinite(longitude) or not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
        raise HTTPException(422, "Picked coordinates do not produce a valid WGS84 latitude/longitude")
    return latitude, longitude


def measurement_values(db: Session, project_id: str, x: float, y: float, z: float, reference_id: str | None) -> tuple[float | None, float | None, float | None]:
    if not reference_id:
        return None, None, None
    reference = db.query(ProductionAnnotation).filter_by(id=reference_id, project_id=project_id).first()
    if not reference:
        raise HTTPException(422, "Measurement reference must be an annotation in the same project")
    vertical = z - reference.z
    horizontal = math.hypot(x - reference.x, y - reference.y)
    return vertical, horizontal, math.sqrt(horizontal * horizontal + vertical * vertical)


def annotation_dict(row: ProductionAnnotation) -> dict:
    return {
        "id": row.id, "project_id": row.project_id, "block_name": row.block_name,
        "family": row.family, "feature_type": row.feature_type,
        "coordinates": {"x": row.x, "y": row.y, "z": row.z},
        "geographic_coordinates": {"latitude": row.latitude, "longitude": row.longitude},
        "pole_internal_id": row.pole_internal_id,
        "reference_annotation_id": row.reference_annotation_id,
        "measurements": {"vertical_delta": row.vertical_delta, "horizontal_offset": row.horizontal_offset, "distance_3d": row.distance_3d},
        "attributes": json.loads(row.attributes_json or "{}"), "status": row.status,
        "created_by": row.created_by, "modified_by": row.modified_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
