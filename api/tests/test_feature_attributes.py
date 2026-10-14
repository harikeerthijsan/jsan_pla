"""Attribute fields from the "Feature and required attribute fields" workbook: served per group, validated on save."""
import pytest
from fastapi import HTTPException

from app.feature_attributes import FEATURE_ATTRIBUTES
from app.production import catalogue, validate_annotation_values


def fields(family):
    return {f["key"]: f for f in FEATURE_ATTRIBUTES[family]}


def test_every_workbook_block_maps_to_a_production_group():
    groups = {g["id"]: g for g in catalogue()["annotation_groups"]}
    for family in FEATURE_ATTRIBUTES:
        assert family in groups, family
        assert groups[family]["fields"] == FEATURE_ATTRIBUTES[family]
    assert set(fields("poles")) == {"first_pole", "last_pole", "environment", "other_type", "other_id", "other_attach_N",
                                   "prev_inc_lat", "prev_inc_lon", "prev_inc_elev_ft", "next_inc_lat", "next_inc_lon", "next_inc_elev_ft"}
    assert set(fields("attachments_util")) == {"util_size", "util_support", "util_owner", "util_1_usage", "util_arm_no"}
    assert set(fields("span_guys")) == {"sgy_key", "sgy_runs_to", "sgy_end_type", "sgy_owner"}


def test_workbook_details_are_kept():
    assert fields("poles")["first_pole"]["options"] == ["INCOMPLETE", "YES"]           # "INCOMPLETE / YES" cell
    assert fields("poles")["other_id"]["manual"] and not fields("poles")["other_id"]["options"]  # "MANUAL ENTRY"
    assert fields("poles")["first_pole"]["features"] == ["Pole_Base"]
    owners = fields("attachments_util")["util_owner"]["options"]
    assert len(owners) == len(set(owners))                                                   # duplicates removed
    assert fields("span_guys")["sgy_runs_to"]["options"] == ["PREV", "NEXT", "OTHER_1", "OTHER_2"]
    assert fields("crossarms")["arm_key"]["options"][0].startswith("Fiberglass")


def test_picked_and_typed_values_are_accepted():
    validate_annotation_values("crossarms", "arm_1", "IN_PROGRESS", {"arm_key": 'Steel - 7\'-6"', "arm_owner": "AT&T"})
    # "Other": any short text.
    validate_annotation_values("crossarms", "arm_2", "IN_PROGRESS", {"arm_owner": "City of Long Beach"})
    validate_annotation_values("poles", "Pole_Base", "IN_PROGRESS", {"first_pole": "YES", "other_id": "P-1234", "placement": "lidar"})


def test_bad_feature_values_are_refused():
    with pytest.raises(HTTPException) as too_long:
        validate_annotation_values("crossarms", "arm_1", "IN_PROGRESS", {"arm_owner": "x" * 201})
    assert too_long.value.status_code == 422
    with pytest.raises(HTTPException) as not_text:
        validate_annotation_values("crossarms", "arm_1", "IN_PROGRESS", {"arm_owner": {"nested": True}})
    assert not_text.value.status_code == 422
    # Pole base fields belong to the pole base point only, and fields stay within their own group.
    with pytest.raises(HTTPException):
        validate_annotation_values("poles", "Pole_Top", "IN_PROGRESS", {"first_pole": "YES"})
    with pytest.raises(HTTPException):
        validate_annotation_values("guys", "guy_1", "IN_PROGRESS", {"arm_owner": "AT&T"})


def test_guys_and_sidewalk_braces_have_anchor_and_typed_fields():
    guys, braces = fields("guys"), fields("sidewalk_braces")
    assert list(guys) == ["guy_key", "guy_owner", "guy_anchor_no"]
    assert list(braces) == ["swb_key", "swb_owner", "swb_anchor_no", "swb_length_ft", "swb_guy_nos"]
    # The anchor fields list the pole's saved anchor points (filled in by the app), the others are typed.
    assert guys["guy_anchor_no"]["source"] == "anchors" and braces["swb_anchor_no"]["source"] == "anchors"
    assert braces["swb_length_ft"]["manual"] and braces["swb_guy_nos"]["manual"]
    validate_annotation_values("guys", "guy_1", "IN_PROGRESS", {"guy_anchor_no": "anc_1"})
    validate_annotation_values("sidewalk_braces", "swb_1", "IN_PROGRESS", {"swb_anchor_no": "anc_2", "swb_length_ft": "8.5", "swb_guy_nos": "guy_1, guy_2"})


def test_attachment_arm_number_lists_the_poles_crossarms():
    comm, util = fields("attachments_comm"), fields("attachments_util")
    # Same choices as the attachment's Parent: the crossarms saved on the pole, or "pole" (filled in by the app).
    assert comm["comm_arm_no"]["source"] == "crossarms" and not comm["comm_arm_no"]["manual"]
    assert util["util_arm_no"]["source"] == "crossarms" and not util["util_arm_no"]["manual"]
    validate_annotation_values("attachments_comm", "comm_1", "IN_PROGRESS", {"comm_arm_no": "arm_2"})
    validate_annotation_values("attachments_util", "util_1", "IN_PROGRESS", {"util_arm_no": "pole"})


def test_incoming_line_fields_follow_incomplete_and_are_numbers():
    poles = fields("poles")
    assert poles["prev_inc_lat"]["show_when"] == {"first_pole": "INCOMPLETE"} and poles["prev_inc_lat"]["pick"] == "prev_inc"
    assert poles["next_inc_elev_ft"]["show_when"] == {"last_pole": "INCOMPLETE"} and poles["next_inc_elev_ft"]["features"] == ["Pole_Base"]
    validate_annotation_values("poles", "Pole_Base", "IN_PROGRESS", {"first_pole": "INCOMPLETE", "prev_inc_lat": "34.37", "prev_inc_lon": -118.9, "prev_inc_elev_ft": "1012.5"})
    for bad in ({"prev_inc_lat": "north"}, {"prev_inc_lat": "95"}, {"next_inc_lon": "-200"}):
        with pytest.raises(HTTPException):
            validate_annotation_values("poles", "Pole_Base", "IN_PROGRESS", bad)
    with pytest.raises(HTTPException):  # only on the pole base point
        validate_annotation_values("poles", "Pole_Top", "IN_PROGRESS", {"prev_inc_lat": "34.37"})


def test_numbered_other_entries_are_validated_on_the_pole_base():
    validate_annotation_values("poles", "Pole_Base", "IN_PROGRESS", {"other_1_type": "OTHER_POLE", "other_1_scope": "IN_SCOPE", "other_1_id": "P-1",
                                                                     "other_2_scope": "OUT_OF_SCOPE", "other_2_lat": "34.1", "other_2_lon": "-118.2", "other_2_elev_ft": "40"})
    for bad in ({"other_1_scope": "MAYBE"}, {"other_2_lat": "north"}, {"other_2_lon": "-181"}, {"other_0_type": "OTHER_POLE"}, {"other_51_id": "x"}):
        with pytest.raises(HTTPException):
            validate_annotation_values("poles", "Pole_Base", "IN_PROGRESS", bad)
    with pytest.raises(HTTPException):
        validate_annotation_values("poles", "Pole_Top", "IN_PROGRESS", {"other_1_type": "OTHER_POLE"})
    with pytest.raises(HTTPException):  # only the pole group accepts them
        validate_annotation_values("guys", "guy_1", "IN_PROGRESS", {"other_1_type": "OTHER_POLE"})
