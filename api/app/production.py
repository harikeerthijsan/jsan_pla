from __future__ import annotations

import json
import math
import re

from fastapi import HTTPException
from pyproj import Transformer
from sqlalchemy.orm import Session

from .models import ProductionAnnotation


# Automatically numbered per pole (arm_1, arm_2, …) with no upper limit.
SEQUENCED_ANNOTATION_GROUPS = {
    "crossarms": {"prefix": "arm"},
    "attachments_comm": {"prefix": "comm"},
    "attachments_util": {"prefix": "util"},
    "anchors": {"prefix": "anc"},
    "guys": {"prefix": "guy"},
    "sidewalk_braces": {"prefix": "swb"},
    "equipment": {"prefix": "eq"},
    "span_guys": {"prefix": "sgy"},
    "other_poles": {"prefix": "other"},
}


def is_sequenced_feature_type(family: str, feature_type: str) -> bool:
    specification = SEQUENCED_ANNOTATION_GROUPS[family]
    return re.fullmatch(rf"{re.escape(specification['prefix'])}_[1-9]\d*", feature_type or "", re.IGNORECASE) is not None


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
    # Numbered groups have no fixed list; their point types are validated by is_sequenced_feature_type.
    **{family: [] for family in SEQUENCED_ANNOTATION_GROUPS},
    "poles": ["Pole_Base", "Pole_Top"],
}

PRODUCTION_ANNOTATION_GROUPS = [
    {"id": "crossarms", "label": "crossarms", "relationship": "Parent"},
    {"id": "attachments_comm", "label": "Attachments — communication", "relationship": "Child"},
    {"id": "attachments_util", "label": "Attachments — utility", "relationship": "Child"},
    {"id": "anchors", "label": "anchors", "relationship": "Parent"},
    {"id": "guys", "label": "guys", "relationship": "Child"},
    {"id": "sidewalk_braces", "label": "sidewalk_braces", "relationship": "Child"},
    {"id": "equipment", "label": "equipment", "relationship": None},
    {"id": "span_guys", "label": "span_guys", "relationship": None},
    {"id": "poles", "label": "Poles", "relationship": None},
    {"id": "other_poles", "label": "Other_Poles", "relationship": None},
]

PRODUCTION_STATUSES = {"NOT_STARTED", "IN_PROGRESS", "COMPLETED", "REWORK", "ON_HOLD", "SUBMITTED_FOR_QC"}

SECTION3_ATTRIBUTE_FIELDS = [
    "feature_id", "parent_feature_id", "pole_internal_id", "item_number", "asset_sub_type",
    "catalog_key", "owner", "arm_no", "usage", "support", "voltage", "anchor_no",
    "guy_nos", "runs_to", "end_type", "environment", "construction_grade", "remarks",
    "relationship",
]


def catalogue() -> dict:
    return {
        "families": [{"name": family, "point_types": points} for family, points in PRODUCTION_FAMILIES.items()],
        "annotation_groups": [
            {**group, **SEQUENCED_ANNOTATION_GROUPS.get(group["id"], {}),
             "automatic_numbering": group["id"] in SEQUENCED_ANNOTATION_GROUPS,
             "point_types": PRODUCTION_FAMILIES[group["id"]]}
            for group in PRODUCTION_ANNOTATION_GROUPS
        ],
        "statuses": sorted(PRODUCTION_STATUSES),
        "attribute_fields": SECTION3_ATTRIBUTE_FIELDS,
        "measurement_fields": ["vertical_delta", "horizontal_offset", "distance_3d"],
    }


def next_annotation_feature_type(
    db: Session,
    project_id: str,
    pole_internal_id: int,
    family: str,
    exclude_annotation_id: str | None = None,
) -> str:
    specification = SEQUENCED_ANNOTATION_GROUPS.get(family)
    if not specification:
        raise HTTPException(422, "The selected annotation group is not automatically numbered")
    query = db.query(ProductionAnnotation).filter_by(
        project_id=project_id, pole_internal_id=pole_internal_id, family=family
    )
    if exclude_annotation_id:
        query = query.filter(ProductionAnnotation.id != exclude_annotation_id)
    pattern = re.compile(rf"^{re.escape(specification['prefix'])}_(\d+)$", re.IGNORECASE)
    numbers = []
    for (feature_type,) in query.with_entities(ProductionAnnotation.feature_type).all():
        match = pattern.fullmatch(feature_type or "")
        if match:
            numbers.append(int(match.group(1)))
    return f"{specification['prefix']}_{max(numbers, default=0) + 1}"


def validate_annotation_values(family: str, feature_type: str, status: str, attributes: dict) -> None:
    if family not in PRODUCTION_FAMILIES:
        raise HTTPException(422, "Unsupported production family")
    valid_type = (is_sequenced_feature_type(family, feature_type) if family in SEQUENCED_ANNOTATION_GROUPS
                  else feature_type in PRODUCTION_FAMILIES[family])
    if not valid_type:
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
