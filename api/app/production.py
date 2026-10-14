from __future__ import annotations

import json
import math
import re
from .feature_attributes import FEATURE_ATTRIBUTES
from datetime import datetime, timezone

from fastapi import HTTPException
from pyproj import Transformer
from sqlalchemy.orm import Session

from .models import Pole, ProductionAnnotation, Project, iso_utc


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
    {"id": "equipment", "label": "equipment", "relationship": "Child"},
    {"id": "span_guys", "label": "span_guys", "relationship": None},
    {"id": "poles", "label": "Poles", "relationship": None},
    {"id": "other_poles", "label": "Other_Poles", "relationship": None},
]

# Which saved points a point may hang from (same pole). Points of other groups, or with no parent chosen, belong
# to the pole itself.
PARENT_FAMILIES = {
    "attachments_comm": ("crossarms",),
    "attachments_util": ("crossarms",),
    "equipment": ("crossarms",),
    "guys": ("anchors",),
}
POLE_PARENT = "pole"
OTHER_ENTRY_KEY = re.compile(r"^other_(\d+)_(type|scope|id|attach_N|lat|lon|elev_ft)$")
OTHER_SCOPES = {"IN_SCOPE", "OUT_OF_SCOPE"}
MAX_OTHER_ENTRIES = 50

PRODUCTION_STATUSES = {"NOT_STARTED", "IN_PROGRESS", "COMPLETED", "REWORK", "ON_HOLD", "SUBMITTED_FOR_QC"}

# How a point's coordinates were obtained: snapped to a LiDAR return, or placed in open space on a working plane
# (the profile section, a vertical plane through the pole, a level plane at ground height, or the view's pivot depth).
POINT_PLACEMENTS = {"lidar", "map", "section_plane", "pole_plane", "ground_plane", "view_plane"}

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
             "fields": FEATURE_ATTRIBUTES.get(group["id"], []),
             "point_types": PRODUCTION_FAMILIES[group["id"]],
             "parent_families": list(PARENT_FAMILIES.get(group["id"], ()))}
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
    feature_fields = {f["key"]: f for f in FEATURE_ATTRIBUTES.get(family, [])}
    other_keys = {k for k in attributes if family == "poles" and OTHER_ENTRY_KEY.match(k)}
    unknown = sorted(set(attributes) - set(SECTION3_ATTRIBUTE_FIELDS) - {"placement"} - set(feature_fields) - other_keys)
    if unknown:
        raise HTTPException(422, f"Unsupported production attribute(s): {', '.join(unknown)}")
    if len(json.dumps(attributes, default=str)) > 20000:
        raise HTTPException(413, "Production attributes exceed the allowed size")
    # Feature fields from the attribute workbook: a picked option or a typed value ("Other"), as short text,
    # and only on the point types they belong to (pole base fields on Pole_Base, for example).
    for key, field in feature_fields.items():
        if key not in attributes:
            continue
        value = attributes[key]
        if value is not None and not isinstance(value, (str, int, float)):
            raise HTTPException(422, f"{field['label']} must be text")
        if value is not None and len(str(value)) > 200:
            raise HTTPException(422, f"{field['label']} is longer than 200 characters")
        if field.get("features") and feature_type not in field["features"]:
            raise HTTPException(422, f"{field['label']} does not apply to {feature_type}")
        # Picked coordinates (prev_inc_* / next_inc_*) must be numbers, and lat/lon must be valid WGS84.
        if field.get("pick") and value not in (None, ""):
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise HTTPException(422, f"{field['label']} must be a number") from None
            limit = 90 if key.endswith("_lat") else 180 if key.endswith("_lon") else None
            if not math.isfinite(number) or (limit is not None and abs(number) > limit):
                raise HTTPException(422, f"{field['label']} is outside the valid range")
    # Other poles / structures on the pole base: other_N_type, other_N_scope (OTHER_POLE: in or out of scope),
    # other_N_id / other_N_attach_N (in scope) or other_N_lat / _lon / _elev_ft (out of scope, picked on the LiDAR).
    for key in sorted(other_keys):
        n, part = OTHER_ENTRY_KEY.match(key).groups()
        value = attributes[key]
        if feature_type != "Pole_Base":
            raise HTTPException(422, f"{key} does not apply to {feature_type}")
        if int(n) < 1 or int(n) > MAX_OTHER_ENTRIES:
            raise HTTPException(422, f"{key}: use other_1 to other_{MAX_OTHER_ENTRIES}")
        if value in (None, ""):
            continue
        if not isinstance(value, (str, int, float)) or len(str(value)) > 200:
            raise HTTPException(422, f"{key} must be short text")
        if part == "scope" and value not in OTHER_SCOPES:
            raise HTTPException(422, f"{key} must be one of: {', '.join(sorted(OTHER_SCOPES))}")
        if part in ("lat", "lon", "elev_ft"):
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise HTTPException(422, f"{key} must be a number") from None
            limit = 90 if part == "lat" else 180 if part == "lon" else None
            if not math.isfinite(number) or (limit is not None and abs(number) > limit):
                raise HTTPException(422, f"{key} is outside the valid range")
    if "placement" in attributes and attributes["placement"] not in POINT_PLACEMENTS:
        raise HTTPException(422, f"Unsupported point placement (use one of: {', '.join(sorted(POINT_PLACEMENTS))})")


def resolve_parent(db: Session, project_id: str, family: str, pole_internal_id: int | None, reference_id: str | None):
    """The parent point a child hangs from, validated; None means the pole. Other groups keep free references."""
    allowed = PARENT_FAMILIES.get(family)
    if allowed is None or not reference_id:
        return None
    parent = db.query(ProductionAnnotation).filter_by(id=reference_id, project_id=project_id).first()
    if not parent or parent.family not in allowed:
        names = " or ".join(group["label"] for group in PRODUCTION_ANNOTATION_GROUPS if group["id"] in allowed)
        raise HTTPException(422, f"This point can only hang from a {names} point, or from the pole")
    if parent.pole_internal_id != pole_internal_id:
        raise HTTPException(422, "The parent point must be on the same pole")
    return parent


def parent_attributes(family: str, parent: ProductionAnnotation | None) -> dict:
    """parent_feature_id recorded with every numbered point: the parent's name (arm_1, anc_2) or "pole"."""
    if family not in SEQUENCED_ANNOTATION_GROUPS:
        return {}
    return {"parent_feature_id": parent.feature_type if parent else POLE_PARENT}


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


def wgs84_to_project(project_crs: str, latitude: float, longitude: float) -> tuple[float, float]:
    """Transform a map click into the project's explicit CRS without browser-side CRS guessing."""
    if not math.isfinite(latitude) or not math.isfinite(longitude) or not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
        raise HTTPException(422, "Map coordinates must be valid WGS84 latitude/longitude")
    try:
        x, y = Transformer.from_crs("EPSG:4326", project_crs, always_xy=True).transform(longitude, latitude)
    except Exception as exc:
        raise HTTPException(422, f"WGS84 cannot be transformed to the project CRS: {project_crs}") from exc
    if not math.isfinite(x) or not math.isfinite(y):
        raise HTTPException(422, "Map coordinates do not produce valid project coordinates")
    return x, y


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
        "revision": row.revision or 1,
        "created_by": row.created_by, "modified_by": row.modified_by,
        "created_at": iso_utc(row.created_at),
        "updated_at": iso_utc(row.updated_at),
    }


def annotations_feature_collection(db: Session, project: Project, rows: list[ProductionAnnotation]) -> dict:
    """GeoJSON FeatureCollection (WGS84 lon/lat, Z in project units) of saved Production points."""
    pole_numbers = {pole.internal_id: pole.pole_number for pole in db.query(Pole).filter_by(project_id=project.id).all()}
    features = []
    for row in rows:
        latitude, longitude = row.latitude, row.longitude
        if latitude is None or longitude is None:
            latitude, longitude = project_to_wgs84(project.crs, row.x, row.y)
        details = annotation_dict(row)
        properties = {
            "annotation_id": row.id,
            "pole_number": pole_numbers.get(row.pole_internal_id),
            "pole_internal_id": row.pole_internal_id,
            "point_name": row.feature_type,
            "annotation_group": row.family,
            "block_name": row.block_name,
            "project_crs": project.crs,
            "x": row.x, "y": row.y, "z": row.z,
            "verified_latitude": latitude, "verified_longitude": longitude,
            "status": row.status,
            "reference_annotation_id": row.reference_annotation_id,
            **details["measurements"],
            **details["attributes"],
            "created_by": row.created_by, "modified_by": row.modified_by,
            "created_at": details["created_at"], "updated_at": details["updated_at"],
        }
        features.append({"type": "Feature", "id": row.id, "geometry": {"type": "Point", "coordinates": [longitude, latitude, row.z]}, "properties": properties})
    return {
        "type": "FeatureCollection",
        "name": f"{project.name} production annotation points",
        "project_id": project.id,
        "source_crs": project.crs,
        "feature_count": len(features),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "features": features,
    }
