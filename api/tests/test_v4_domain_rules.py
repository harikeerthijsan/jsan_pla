from app.v4_rules import incomplete_has_xyz, internal_id_limit, internal_ids_sequential, unmeasured_without_internal_id
from app.v4_release import evaluate_release_gate

def test_no_id_source_row_is_valid_when_unmeasured():
    ok, evidence = unmeasured_without_internal_id({"measurement_complete": False, "internal_id": None})
    assert ok
    assert evidence["internal_id"] is None

def test_unmeasured_record_must_not_receive_internal_id():
    ok, _ = unmeasured_without_internal_id({"measurement_complete": False, "internal_id": 51})
    assert not ok

def test_internal_ids_are_contiguous_and_limited():
    rows = [{"internal_id": 1}, {"internal_id": 2}, {"internal_id": None}, {"internal_id": 3}]
    assert internal_ids_sequential(rows)[0]
    assert internal_id_limit(rows)[0]
    assert not internal_ids_sequential([{"internal_id": 1}, {"internal_id": 3}])[0]

def test_incomplete_requires_coordinates():
    ok, _ = incomplete_has_xyz({
        "first_pole": "Incomplete",
        "prev_inc_lat": 1.0,
        "prev_inc_lon": 2.0,
        "prev_inc_elev_ft": 3.0,
        "last_pole": None,
    })
    assert ok
    bad, _ = incomplete_has_xyz({"last_pole": "Incomplete", "next_inc_lat": 1.0})
    assert not bad

def test_release_gate_blocks_blocking_failures():
    gate = evaluate_release_gate([
        {"rule_id": "A", "blocking": True, "outcome": "FAIL"},
        {"rule_id": "B", "blocking": False, "outcome": "WARNING"},
    ])
    assert not gate.ready
    assert len(gate.blockers) == 1
    clean = evaluate_release_gate([{"rule_id": "B", "blocking": False, "outcome": "WARNING"}])
    assert clean.ready
