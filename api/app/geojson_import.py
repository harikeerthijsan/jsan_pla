"""Client GeoJSON import for Production datasets.

The uploaded file is untrusted. Coordinates are transformed explicitly from the
GeoJSON CRS (RFC 7946 WGS84 unless a legacy named ``crs`` member says otherwise)
into the project CRS, and every feature keeps its source geometry next to the
transformed one so the conversion stays auditable.
"""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict

from pyproj import CRS, Transformer
from sqlalchemy.orm import Session

from .models import Pole, ProductionGeoFeature, Project


GEOMETRY_TYPES = {"Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"}
MAX_FEATURES = 200_000
DEFAULT_CRS = "OGC:CRS84"


class GeoJSONError(ValueError):
    """The GeoJSON cannot be imported; the message is safe to show to the user."""


def _is_feet(units: str | None) -> bool:
    text = (units or "").lower()
    return "foot" in text or "feet" in text or text.strip() == "ft"


def match_tolerances(units: str | None) -> tuple[float, float]:
    """(nearest-pole fallback radius, maximum plausible distance for an ID match) in project units."""
    return (10.0, 1000.0) if _is_feet(units) else (3.0, 300.0)


def source_crs(document: dict) -> str:
    crs = document.get("crs")
    if crs is None:
        return DEFAULT_CRS
    properties = crs.get("properties") if isinstance(crs, dict) else None
    if not isinstance(crs, dict) or crs.get("type") != "name" or not isinstance(properties, dict):
        raise GeoJSONError('Unsupported GeoJSON "crs" member: only a named CRS is accepted')
    name = str(properties.get("name", "")).strip()
    if re.search(r"CRS84$", name, re.I):
        return DEFAULT_CRS
    match = re.search(r"EPSG:+(\d+)$", name, re.I)  # EPSG:6424 or urn:ogc:def:crs:EPSG::6424
    if not match:
        raise GeoJSONError(f"Unsupported GeoJSON CRS name: {name[:120]}")
    return f"EPSG:{match.group(1)}"


def normalise_id(value) -> str | None:
    if value is None or isinstance(value, (dict, list, bool)):
        return None
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        if value.is_integer():
            value = int(value)
    text = str(value).strip().upper()
    if re.fullmatch(r"-?\d+\.0+", text):
        text = text.split(".")[0]
    return text or None


def _positions(coordinates, geometry_type: str):
    """Yield every position, validating structure for the declared geometry type."""
    depth = {"Point": 0, "MultiPoint": 1, "LineString": 1, "MultiLineString": 2, "Polygon": 2, "MultiPolygon": 3}[geometry_type]

    def walk(value, level):
        if level == 0:
            if not isinstance(value, list) or len(value) < 2 or not all(isinstance(n, (int, float)) and not isinstance(n, bool) for n in value[:3]):
                raise GeoJSONError(f"Invalid {geometry_type} coordinates")
            if not all(math.isfinite(float(n)) for n in value[:3]):
                raise GeoJSONError(f"{geometry_type} coordinates must be finite numbers")
            yield value
            return
        if not isinstance(value, list) or not value:
            raise GeoJSONError(f"Invalid {geometry_type} coordinates")
        for item in value:
            yield from walk(item, level - 1)

    yield from walk(coordinates, depth)


def _transform_coordinates(coordinates, transform):
    if coordinates and isinstance(coordinates[0], (int, float)):
        x, y = transform(float(coordinates[0]), float(coordinates[1]))
        return [x, y]
    return [_transform_coordinates(item, transform) for item in coordinates]


def parse_features(raw: bytes | str, project_crs: str) -> tuple[str, list[dict]]:
    try:
        document = json.loads(raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GeoJSONError("GeoJSON is not valid UTF-8 JSON") from exc
    if not isinstance(document, dict):
        raise GeoJSONError("GeoJSON must be a FeatureCollection or Feature object")
    if document.get("type") == "Feature":
        features = [document]
    elif document.get("type") == "FeatureCollection" and isinstance(document.get("features"), list):
        features = document["features"]
    else:
        raise GeoJSONError("GeoJSON must be a FeatureCollection or Feature object")
    if len(features) > MAX_FEATURES:
        raise GeoJSONError(f"GeoJSON has {len(features)} features; the limit is {MAX_FEATURES}")

    crs = source_crs(document)
    try:
        geographic = CRS.from_user_input(crs).is_geographic
        transformer = Transformer.from_crs(crs, project_crs, always_xy=True)
    except Exception as exc:
        raise GeoJSONError(f"GeoJSON CRS {crs} cannot be transformed to the project CRS {project_crs}") from exc

    def transform(x: float, y: float) -> tuple[float, float]:
        if geographic and not (-180 <= x <= 180 and -90 <= y <= 90):
            raise GeoJSONError("GeoJSON longitude/latitude is out of range; check the file CRS")
        px, py = transformer.transform(x, y)
        if not (math.isfinite(px) and math.isfinite(py)):
            raise GeoJSONError("GeoJSON coordinates cannot be transformed to the project CRS")
        return px, py

    parsed = []
    for index, feature in enumerate(features):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise GeoJSONError(f"Feature {index} is not a GeoJSON Feature")
        geometry = feature.get("geometry")
        if geometry is None:
            continue  # unlocated features carry no spatial information to overlay
        if not isinstance(geometry, dict) or geometry.get("type") not in GEOMETRY_TYPES:
            raise GeoJSONError(f"Feature {index} has an unsupported geometry type")
        properties = feature.get("properties") or {}
        if not isinstance(properties, dict):
            raise GeoJSONError(f"Feature {index} properties must be an object")
        list(_positions(geometry.get("coordinates"), geometry["type"]))
        projected = _transform_coordinates(geometry["coordinates"], transform)
        flat = list(_positions(projected, geometry["type"]))
        parsed.append({
            "feature_index": index,
            "geometry_type": geometry["type"],
            "source_geometry": {"type": geometry["type"], "coordinates": geometry["coordinates"]},
            "geometry": {"type": geometry["type"], "coordinates": projected},
            "x": sum(p[0] for p in flat) / len(flat),
            "y": sum(p[1] for p in flat) / len(flat),
            "properties": properties,
        })
    return crs, parsed


def match_to_poles(features: list[dict], poles: list[dict], units: str | None) -> dict:
    """Attach pole_internal_id/match fields to Point features in place and return the match summary.

    ``poles`` items: ``internal_id``, ``pole_number``, ``x``, ``y`` (x/y may be None).
    """
    nearest_radius, id_max_distance = match_tolerances(units)
    points = [f for f in features if f["geometry_type"] == "Point"]
    by_target = {"pole_number": defaultdict(list), "internal_id": defaultdict(list)}
    for pole in poles:
        for target in by_target:
            key = normalise_id(pole.get(target))
            if key:
                by_target[target][key].append(pole)

    def distance(feature, pole):
        if pole.get("x") is None or pole.get("y") is None:
            return None
        return math.hypot(feature["x"] - pole["x"], feature["y"] - pole["y"])

    def id_candidate(feature, prop, target):
        candidates = by_target[target].get(normalise_id(feature["properties"].get(prop)) or "", [])
        scored = [(distance(feature, pole), pole) for pole in candidates]
        # An ID match must also be spatially plausible, so a generic OBJECTID cannot pose as a pole ID.
        scored = [(d, pole) for d, pole in scored if d is None or d <= id_max_distance]
        if not scored:
            return None
        return min(scored, key=lambda item: math.inf if item[0] is None else item[0])

    best = (0, None, None)
    keys = sorted({key for feature in points for key in feature["properties"]})
    for target in ("pole_number", "internal_id"):  # pole_number wins ties
        for prop in keys:
            count = sum(1 for feature in points if id_candidate(feature, prop, target))
            if count > best[0]:
                best = (count, prop, target)
    _, match_property, match_target = best

    grid = defaultdict(list)
    for pole in poles:
        if pole.get("x") is not None and pole.get("y") is not None:
            grid[(math.floor(pole["x"] / nearest_radius), math.floor(pole["y"] / nearest_radius))].append(pole)

    summary = {"features": len(features), "points": len(points), "matched_id": 0, "matched_nearest": 0, "unmatched_points": 0,
               "match_property": match_property, "match_target": match_target}
    for feature in features:
        feature.update(pole_internal_id=None, match_method=None, match_property=None, match_distance=None)
    for feature in points:
        hit = id_candidate(feature, match_property, match_target) if match_property else None
        if hit:
            feature.update(pole_internal_id=hit[1]["internal_id"], match_method="ID", match_property=match_property, match_distance=hit[0])
            summary["matched_id"] += 1
            continue
        cx, cy = math.floor(feature["x"] / nearest_radius), math.floor(feature["y"] / nearest_radius)
        nearby = [pole for dx in (-1, 0, 1) for dy in (-1, 0, 1) for pole in grid.get((cx + dx, cy + dy), [])]
        scored = [(distance(feature, pole), pole) for pole in nearby]
        scored = [item for item in scored if item[0] is not None and item[0] <= nearest_radius]
        if scored:
            d, pole = min(scored, key=lambda item: item[0])
            feature.update(pole_internal_id=pole["internal_id"], match_method="NEAREST", match_distance=d)
            summary["matched_nearest"] += 1
        else:
            summary["unmatched_points"] += 1
    return summary


def pole_locations(project: Project, poles: list[Pole]) -> list[dict]:
    """Project-CRS pole locations: LiDAR-verified X/Y when present, otherwise the workbook latitude/longitude."""
    to_project = Transformer.from_crs("EPSG:4326", project.crs, always_xy=True)
    out = []
    for pole in poles:
        x = y = workbook_x = workbook_y = None
        if pole.corrected_lat is not None and pole.corrected_lon is not None:
            workbook_x, workbook_y = to_project.transform(float(pole.corrected_lon), float(pole.corrected_lat))
            if not (math.isfinite(workbook_x) and math.isfinite(workbook_y)):
                workbook_x = workbook_y = None
        if pole.verified_x is not None and pole.verified_y is not None:
            x, y = pole.verified_x, pole.verified_y
        else:
            x, y = workbook_x, workbook_y
        out.append({"internal_id": pole.internal_id, "pole_number": pole.pole_number, "x": x, "y": y,
                    "workbook_x": workbook_x, "workbook_y": workbook_y, "pole": pole})
    return out


def import_project_geojson(db: Session, project: Project, source_file_id: str, raw: bytes | str) -> dict:
    """Replace the project's derived GeoJSON features. Raises GeoJSONError for an unusable file."""
    crs, features = parse_features(raw, project.crs)
    poles = pole_locations(project, db.query(Pole).filter_by(project_id=project.id).all())
    summary = match_to_poles(features, poles, project.units)
    summary["source_crs"] = crs
    summary["project_crs"] = project.crs
    db.query(ProductionGeoFeature).filter_by(project_id=project.id).delete()
    for feature in features:
        db.add(ProductionGeoFeature(
            project_id=project.id, source_file_id=source_file_id, feature_index=feature["feature_index"],
            geometry_type=feature["geometry_type"], source_crs=crs,
            source_geometry_json=json.dumps(feature["source_geometry"]), geometry_json=json.dumps(feature["geometry"]),
            x=feature["x"], y=feature["y"], properties_json=json.dumps(feature["properties"], default=str),
            pole_internal_id=feature["pole_internal_id"], match_method=feature["match_method"],
            match_property=feature["match_property"], match_distance=feature["match_distance"],
        ))
    return summary


def summary_message(summary: dict) -> str:
    return (f"GeoJSON: {summary['features']} features ({summary['points']} points) · "
            f"{summary['matched_id']} matched by ID · {summary['matched_nearest']} by nearest pole · "
            f"{summary['unmatched_points']} unmatched")


def geo_feature_dict(row: ProductionGeoFeature, location: dict | None) -> dict:
    offsets = {"verified": None, "workbook": None}
    if location and row.x is not None and row.y is not None:
        pole = location["pole"]
        if pole.verified_x is not None and pole.verified_y is not None:
            offsets["verified"] = math.hypot(row.x - pole.verified_x, row.y - pole.verified_y)
        if location["workbook_x"] is not None:
            offsets["workbook"] = math.hypot(row.x - location["workbook_x"], row.y - location["workbook_y"])
    return {
        "id": row.id, "feature_index": row.feature_index, "geometry_type": row.geometry_type,
        "source_crs": row.source_crs, "geometry": json.loads(row.geometry_json),
        "source_geometry": json.loads(row.source_geometry_json), "x": row.x, "y": row.y,
        "properties": json.loads(row.properties_json or "{}"), "pole_internal_id": row.pole_internal_id,
        "match_method": row.match_method, "match_property": row.match_property, "match_distance": row.match_distance,
        "offsets": offsets,
    }
