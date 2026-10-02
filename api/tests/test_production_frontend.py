from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_production_bounding_box_controls_and_clipping_are_wired():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")

    assert 'id="productionBoxBtn"' in html
    assert 'id="productionCloseBoxBtn"' in html
    assert "Potree.CameraMode.ORTHOGRAPHIC" in javascript
    assert "Potree.ClipTask.SHOW_INSIDE" in javascript
    assert "Potree.ClipMethod.INSIDE_ANY" in javascript
    assert "scene.removeVolume(state.productionClipVolume)" in javascript
    assert "zoomTo(state.productionClipVolume" in javascript


def test_production_box_tool_supports_the_combined_multi_cloud_model():
    javascript = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")

    # Potree's ScreenBoxSelectTool picks a single point cloud and throws on the
    # combined model, leaving the camera stuck in orthographic mode.
    assert "ScreenBoxSelectTool" not in javascript.replace("Potree's ScreenBoxSelectTool", "")
    assert "function startProductionBox()" in javascript
    assert "function cancelProductionBox(" in javascript
    assert "restoreProductionCamera(tool.previous)" in javascript
    assert "inputHandler.removeInputListener(tool.listener)" in javascript
    assert 'e.key!=="Escape"' in javascript


def test_production_navigation_controls_are_wired():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")

    for view in ("top", "front", "side", "3d"):
        assert f'data-production-view="{view}"' in html
    assert 'id="productionNavModeBtn"' in html
    assert 'id="productionNavHint"' in html
    assert "installProductionNavigation(v)" in javascript
    assert "e.drag.mouse===4" in javascript
    # Saved markers are display-only so a drag over them orbits instead of moving them.
    assert "sphere._listeners={}" in javascript


def test_production_profile_view_is_wired():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")

    for element in (
        "productionProfileBtn", "productionProfileBar", "productionProfileOverlay",
        "productionProfilePrevBtn", "productionProfileNextBtn", "productionProfileRotateBtn",
        "productionProfileDepth", "productionProfileExitBtn",
    ):
        assert f'id="{element}"' in html
    for preset in ("base", "top", "attachment"):
        assert f'data-profile-pick="{preset}"' in html
    assert "function enterProductionProfile(a,b)" in javascript
    assert "p.volume.scale.set(p.len,p.depth" in javascript
    assert "v.orbitControls.rotationSpeed=0" in javascript
    assert "v.orbitControls.rotationSpeed=5" in javascript
    assert "function drawProductionProfileOverlay()" in javascript
    assert "above base" in javascript
    # Picks in the production viewer honour the clip so profile picks stay inside the slab.
    assert "pickClipped:true" in javascript
    # A click that hits no LiDAR point must not create a draft at the origin.
    assert "p.x===0&&p.y===0&&p.z===0" in javascript


def test_production_workbook_poles_and_verified_coordinates_are_wired():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")

    assert 'id="productionWorkbookFile"' in html
    assert 'id="annotationPoleId"' in html
    assert 'id="annotationLat"' in html
    assert 'id="annotationLon"' in html
    assert "/coordinates/to-wgs84" in javascript
    assert 'i===0?"WORKBOOK":"LIDAR_SOURCE"' in javascript
    assert "pole_internal_id:poleId?Number(poleId):null" in javascript
    assert "verified_bottom_elevation" in javascript
    assert "verified_top_elevation" in javascript
    assert "verified_height" in javascript


def test_all_production_lidar_blocks_share_one_combined_viewer():
    javascript = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")

    assert 'textContent="Combined LiDAR model"' in javascript
    assert "Promise.allSettled(blocks.map" in javascript
    assert "loadProductionPointCloud(block,generation,projectId)" in javascript
    assert "productionBlockForCoordinates(state.productionDraft)" in javascript
    assert "No points attached for this combined LiDAR model" in javascript
