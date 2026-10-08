"""Canonical identity/location detection for untrusted customer tabular data."""
from __future__ import annotations

import re


ALIASES = {
    # "Pole ID" is deliberately not an alias: customers often use it for the pole tag number.
    "internal_id": {"internal id", "internalid", "pole internal id", "internal pole id"},
    "pole_number": {"pole number", "polenumber", "pole no", "pole num", "pole number id"},
    "latitude": {"latitude", "lat", "pole latitude", "pole lat"},
    "longitude": {"longitude", "lon", "lng", "long", "pole longitude", "pole lon", "pole lng"},
    "x": {"x", "easting", "east", "x coordinate", "x coord"},
    "y": {"y", "northing", "north", "y coordinate", "y coord"},
    # "Height" is pole length, not ground elevation, so it stays an ordinary attribute.
    "z": {"z", "elevation", "elev", "z coordinate", "z coord"},
}


def normalize_header(value) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-z]+", " ", str(value or "").strip().casefold())).strip()


def field_key(value) -> str:
    return normalize_header(value).replace(" ", "_")


def canonical_field(value) -> str | None:
    normalized = normalize_header(value)
    return next((name for name, aliases in ALIASES.items() if normalized in aliases), None)


def header_map(headers) -> dict[str, int]:
    """Return canonical field -> zero-based index and reject ambiguous aliases."""
    found: dict[str, int] = {}
    for index, header in enumerate(headers):
        canonical = canonical_field(header)
        if not canonical:
            continue
        if canonical in found:
            raise ValueError(f"Multiple columns represent {canonical.replace('_', ' ')}")
        found[canonical] = index
    return found


def has_location(columns: dict[str, int]) -> bool:
    return {"latitude", "longitude"} <= columns.keys() or {"x", "y"} <= columns.keys()


def detect_pole_sheet(workbook, *, require_location: bool = True):
    candidates = []
    for order, worksheet in enumerate(workbook.worksheets):
        headers = [cell.value for cell in next(worksheet.iter_rows(min_row=1, max_row=1), ())]
        try:
            columns = header_map(headers)
        except ValueError as exc:
            raise ValueError(f"Worksheet {worksheet.title!r}: {exc}") from exc
        if {"internal_id", "pole_number"} <= columns.keys() and (has_location(columns) or not require_location):
            preferred = normalize_header(worksheet.title) in {"poles", "pole", "pole catalogue", "pole catalog"}
            candidates.append((not preferred, not has_location(columns), order, worksheet, columns))
    if not candidates:
        location = " and either latitude/longitude or X/Y" if require_location else ""
        raise ValueError(f"Workbook must contain a pole catalogue with Internal ID, Pole Number{location}")
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    if len(candidates) > 1 and candidates[0][:2] == candidates[1][:2]:
        names = ", ".join(repr(item[3].title) for item in candidates)
        raise ValueError(f"Workbook has multiple possible pole catalogue worksheets: {names}")
    return candidates[0][3], candidates[0][4]


def value_for(mapping: dict, canonical: str):
    matches = [value for key, value in mapping.items() if canonical_field(key) == canonical]
    nonblank = [value for value in matches if value is not None and str(value).strip()]
    if len(nonblank) > 1 and len({str(value).strip() for value in nonblank}) > 1:
        return None
    return nonblank[0] if nonblank else None


def manifest_coordinates(manifest: dict) -> tuple[object, object, object]:
    return value_for(manifest or {}, "x"), value_for(manifest or {}, "y"), value_for(manifest or {}, "z")
