"""Production points record how they were placed: snapped to LiDAR, or in open space on a working plane."""
import pytest
from fastapi import HTTPException

from app.production import POINT_PLACEMENTS, validate_annotation_values

FAMILY, FEATURE = "Pole Points", "Pole Base / Ground Point"


@pytest.mark.parametrize("placement", sorted(POINT_PLACEMENTS))
def test_every_known_placement_is_accepted(placement):
    validate_annotation_values(FAMILY, FEATURE, "IN_PROGRESS", {"placement": placement})


def test_placement_is_optional_for_older_points():
    validate_annotation_values(FAMILY, FEATURE, "IN_PROGRESS", {})


def test_unknown_placement_or_attribute_is_refused():
    with pytest.raises(HTTPException) as bad_value:
        validate_annotation_values(FAMILY, FEATURE, "IN_PROGRESS", {"placement": "guessed"})
    assert bad_value.value.status_code == 422 and "placement" in bad_value.value.detail
    with pytest.raises(HTTPException) as bad_key:
        validate_annotation_values(FAMILY, FEATURE, "IN_PROGRESS", {"placement": "lidar", "made_up": 1})
    assert bad_key.value.status_code == 422 and "made_up" in bad_key.value.detail


def test_the_frontend_offers_the_same_placements():
    from pathlib import Path
    import re

    js = (Path(__file__).resolve().parents[2] / "web" / "assets" / "modules" / "production-placement.js").read_text(encoding="utf-8")
    labels = set(re.findall(r"^\s+(\w+): \"", js.split("PLACEMENT_LABELS = {")[1].split("};")[0], flags=re.M))
    assert labels == POINT_PLACEMENTS
