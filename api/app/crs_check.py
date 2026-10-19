"""Which coordinate system a dataset's files are in, so a wrong Source CRS is caught instead of misplacing poles.

LiDAR (LAS/LAZ/COPC) carries its CRS in the header VLRs: a WKT string (record 2112) or GeoTIFF keys (record 34735,
ProjectedCSTypeGeoKey 3072). Only the header is read (a few hundred KB at most), never the points.
"""
from __future__ import annotations

import re
import struct

from pyproj import CRS

HEADER_LIMIT = 4 * 1024 * 1024  # VLRs live before the point data; LAS files keep this small


def crs_epsg(text) -> int | None:
    """EPSG code of a CRS given as "EPSG:6426", a URN, WKT or an int; the horizontal part of a compound CRS."""
    if text is None or str(text).strip() == "":
        return None
    try:
        crs = CRS.from_user_input(int(text) if str(text).strip().isdigit() else str(text).strip())
    except Exception:
        return None
    if crs.is_compound and crs.sub_crs_list:
        crs = crs.sub_crs_list[0]
    code = crs.to_epsg(min_confidence=70)
    return int(code) if code else None


def crs_name(code: int | None) -> str | None:
    if not code:
        return None
    try:
        return CRS.from_epsg(code).name
    except Exception:
        return None


def describe(code: int | None) -> str:
    name = crs_name(code)
    return f"EPSG:{code}" + (f" ({name})" if name else "") if code else "an unknown CRS"


def _wkt_epsg(wkt: str) -> int | None:
    code = crs_epsg(wkt)
    if code:
        return code
    # Fall back to the projected CRS's own authority: the last EPSG id inside the PROJCS / PROJCRS block.
    start = max(wkt.find("PROJCS["), wkt.find("PROJCRS["))
    if start < 0:
        return None
    depth, end = 0, len(wkt)
    for index in range(start, len(wkt)):
        if wkt[index] == "[":
            depth += 1
        elif wkt[index] == "]":
            depth -= 1
            if depth == 0:
                end = index
                break
    ids = re.findall(r'(?:AUTHORITY|ID)\[\s*"EPSG"\s*,\s*"?(\d+)"?\s*\]', wkt[start:end + 1])
    return int(ids[-1]) if ids else None


def las_epsg(header: bytes) -> int | None:
    """Horizontal EPSG code from the start of a LAS/LAZ/COPC file (header + VLRs), or None when it carries none."""
    if len(header) < 227 or header[:4] != b"LASF":
        raise ValueError("Not a LAS/LAZ file")
    header_size = struct.unpack_from("<H", header, 94)[0]
    vlr_count = struct.unpack_from("<I", header, 100)[0]
    offset, wkt, geokey = header_size, None, None
    for _ in range(vlr_count):
        if offset + 54 > len(header):
            break
        record_id, length = struct.unpack_from("<HH", header, offset + 18)
        data = header[offset + 54: offset + 54 + length]
        user = header[offset + 2: offset + 18].split(b"\0", 1)[0]
        if user == b"LASF_Projection" and record_id == 2112:
            wkt = data.split(b"\0", 1)[0].decode("utf-8", "replace")
        elif user == b"LASF_Projection" and record_id == 34735 and len(data) >= 8:
            keys = struct.unpack_from(f"<{len(data) // 2}H", data)
            for i in range(4, 4 + keys[3] * 4, 4):
                if i + 3 < len(keys) and keys[i] == 3072 and keys[i + 1] == 0 and 1024 <= keys[i + 3] < 32767:
                    geokey = keys[i + 3]
        offset += 54 + length
    if wkt:
        code = _wkt_epsg(wkt)
        if code:
            return code
    return geokey


def header_length(first: bytes) -> int:
    """How many bytes cover the header and VLRs (offset to point data), capped."""
    if len(first) < 100 or first[:4] != b"LASF":
        raise ValueError("Not a LAS/LAZ file")
    return min(HEADER_LIMIT, struct.unpack_from("<I", first, 96)[0])


def object_lidar_epsg(key: str) -> int | None:
    """EPSG of a stored LiDAR object, from a ranged read of its header only."""
    from .storage import read_range
    first = read_range(key, 0, 375)
    return las_epsg(read_range(key, 0, header_length(first)))


def lidar_mismatch_message(filename: str, file_code: int, project_crs: str) -> str:
    return (f"{filename} is in {describe(file_code)}, but this dataset's Source CRS is {describe(crs_epsg(project_crs))}. "
            f"Nothing was converted. Import again with Source CRS EPSG:{file_code}, or ask an admin to change this dataset's CRS.")
