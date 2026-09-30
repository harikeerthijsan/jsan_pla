from app.sections import project_xyz


def test_profile_projection_matches_known_engineering_frame():
    # Synthetic engineering reference: span axis points east, cross axis north.
    frame = {
        "origin": [1000.0, 2000.0, 500.0],
        "ux": [1.0, 0.0],
        "uy": [0.0, 1.0],
    }
    station, offset, elevation = project_xyz(frame, [1042.5, 1993.0, 537.25])
    assert station == 42.5
    assert offset == -7.0
    assert elevation == 537.25


def test_profile_projection_rotated_frame():
    # 45-degree reference frame; values are deterministic and can be compared
    # against MicroStation/TerraScan during acceptance without inventing tolerances.
    root2 = 2 ** 0.5
    frame = {
        "origin": [0.0, 0.0, 0.0],
        "ux": [1 / root2, 1 / root2],
        "uy": [-1 / root2, 1 / root2],
    }
    station, offset, elevation = project_xyz(frame, [10.0, 0.0, 25.0])
    assert round(station, 6) == round(10 / root2, 6)
    assert round(offset, 6) == round(-10 / root2, 6)
    assert elevation == 25.0
