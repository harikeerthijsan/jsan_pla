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
    assert "function productionPointAt(px,py)" in javascript
    assert "function startProductionProfileLine()" in javascript
    assert 'toast("Now click the end of the section line."' in javascript
    assert "function enterProductionProfile(a,b)" in javascript
    assert "p.volume.scale.set(p.len,p.depth" in javascript
    assert "startProductionProfileBox" not in javascript
    assert "production-profile-rect" not in javascript
    assert "v.orbitControls.rotationSpeed=0" in javascript
    assert "v.orbitControls.rotationSpeed=5" in javascript
    assert "function drawProductionProfileOverlay()" in javascript
    assert "above base" in javascript
    # Picks in the production viewer honour the clip so profile picks stay inside the slab.
    assert "pickClipped:true" in javascript
    # A click that hits no LiDAR point must not create a draft at the origin.
    assert 'if(!hit){toast("No LiDAR point under the cursor' in javascript


def test_production_pick_lets_the_user_navigate_and_geojson_markers_are_large():
    javascript = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "assets" / "app.css").read_text(encoding="utf-8")

    # Pick mode places a point only on a click; a drag rotates or pans the view.
    assert "Math.hypot(e.clientX-start.x,e.clientY-start.y)>4)return" in javascript
    assert "measuringTool.startInsertion" not in javascript
    assert "drag to move the view · Esc to cancel" in javascript
    assert "cancelProductionPick();resetAnnotationForm({poleId:$(\"annotationPoleId\").value})" in javascript
    # GeoJSON poles are drawn as large screen-space pins with labels in every view.
    assert "function drawProductionGeoMarkers()" in javascript
    assert "startProductionGeoMarkerLoop()" in javascript
    assert ".production-geo-markers{" in css
    assert "canvas.production-picking{cursor:crosshair}" in css


def test_production_workbook_poles_and_verified_coordinates_are_wired():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")

    assert 'id="productionWorkbookFile"' in html
    assert 'id="annotationPoleId"' in html
    assert 'id="annotationLat"' in html
    assert 'id="annotationLon"' in html
    assert 'id="annotationStreetView"' in html
    assert 'class="geographic-readout" aria-live="polite"' in html
    assert html.index('class="geographic-readout"') < html.index('id="productionChecklist"')
    assert "/coordinates/to-wgs84" in javascript
    assert "map_action=pano&viewpoint=" in javascript
    assert 'window.open(`https://www.google.com/maps/' in javascript
    assert 'document.querySelector("#annotationForm .coordinate-readout")?.classList.add("hidden")' in javascript
    assert '{file:workbook,role:"WORKBOOK"}' in javascript
    assert 'lidar.map(file=>({file,role:"LIDAR_SOURCE"}))' in javascript
    assert "pole_internal_id:Number(poleId)" in javascript
    assert 'id="annotationFamily"' in html
    assert 'id="annotationFeature"' in html
    assert 'id="annotationItemNo"' not in html
    assert 'id="annotationOwner"' not in html
    assert 'id="annotationReference"' not in html
    assert 'id="annotationStatus"' not in html
    assert 'id="annotationRemarks"' not in html
    assert 'function productionAnnotationGroups()' in javascript
    assert 'function nextProductionFeature(group)' in javascript
    assert 'assigned automatically' in javascript
    assert 'family:"poles",feature:"Pole_Base"' in javascript
    assert 'family:"poles",feature:"Pole_Top"' in javascript
    assert "verified_bottom_elevation" in javascript
    assert "verified_top_elevation" in javascript
    assert "verified_height" in javascript


def test_production_geojson_upload_overlay_and_details_are_wired():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")

    assert 'id="productionGeojsonFile"' in html
    assert 'GeoJSON is not required' not in html
    assert 'id="productionGeoToggleBtn"' in html
    assert 'id="productionGeoCard"' in html
    assert '{file:geojson,role:"GEOJSON"}' in javascript
    assert "async function checkGeojsonFile(file)" in javascript
    assert "/production-geo-features" in javascript
    assert 'id="productionAnnotationsDownload"' in html
    assert "/production-annotations.geojson" in javascript
    assert "async function downloadProductionAnnotations()" in javascript
    assert "function renderProductionGeoOverlay()" in javascript
    assert "function selectProductionGeoAt(px,py)" in javascript
    # GeoJSON properties are untrusted and must be rendered escaped.
    assert "<dt>${esc(k)}</dt><dd>${esc(" in javascript
    # A click that ends a pick, bounding box or profile rectangle must not also open the details card.
    assert "busy:Boolean(state.productionPicking||state.productionBoxTool||state.productionProfileLine)" in javascript
    # A missing verified latitude/longitude must show "—", not 0.00000000.
    assert "function coordinateText(latitude,longitude){return latitude!=null&&longitude!=null&&" in javascript


def test_production_pole_workflow_is_wired():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "assets" / "app.css").read_text(encoding="utf-8")

    for element in ("productionPoleList", "productionPoleSearch", "productionPoleProgress", "productionPolePrev",
                    "productionPoleNext", "productionPoleTitle", "productionChecklist", "productionContextMeta"):
        assert f'id="{element}"' in html
    for pole_filter in ("all", "todo", "done"):
        assert f'data-pole-filter="{pole_filter}"' in html
    # One pole selection drives everything: the Points form's own picker is hidden, not duplicated.
    assert '<label class="hidden">Pole Number<select id="annotationPoleId"' in html
    assert 'id="annotationForm" class="annotation-form" novalidate' in html
    assert "production-nav-tools" not in html  # view buttons live in the single top toolbar
    assert "function selectProductionPole(id" in javascript
    assert "function renderProductionChecklist()" in javascript
    assert "function flyToProductionPole(pole)" in javascript
    assert "renderProductionPoleWorkflow();" in javascript
    assert ".production-side .workbook-pole-label" in css
    # The QC workspace owns .pole-row; Production must not restyle it.
    assert "production-pole-row status-" in javascript
    assert ".production-pole-row{" in css
    # A "Full LiDAR model" entry returns to the whole model and shows every saved point in 3D.
    assert "function showFullProductionModel()" in javascript
    assert "root.appendChild(productionFullModelRow(!selected))" in javascript
    assert 'rows=$("annotationPoleId").value?selectedPoleAnnotations():state.productionAnnotations' in javascript


def test_qc_banner_runs_qc_on_production_lidar():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "assets" / "app.css").read_text(encoding="utf-8")

    assert 'id="qcProductionBanner"' in html
    assert "function renderQcProductionBanner()" in javascript
    assert "renderQcProductionBanner();" in javascript
    # Run QC asks for a QC Excel and creates a linked QC dataset that shares the Production LiDAR.
    for element in ("qcRunDialog", "qcRunExcel", "qcRunGeojson", "replaceExcelDialog", "replaceExcelFile", "productionReplaceExcelBtn"):
        assert f'id="{element}"' in html
    assert "/qc-dataset`,{method:\"POST\",body:JSON.stringify({include_geojson:" in javascript
    assert 'await sendFile(qcId,file,"WORKBOOK",0,1,report)' in javascript
    assert "/production-workbook/prepare`" in javascript
    assert "/production-workbook/${fileId}/apply`" in javascript
    # Running QC uploads a QC Excel, so only roles that may upload see the button.
    assert "canRun=can(\"upload.create\")&&can(\"processing.run\")" in javascript
    # The banner floats over the QC evidence area so the four-view grid rows are untouched.
    assert ".qc-production-banner{position:absolute" in css


def test_delivery_pipeline_connects_production_and_qc():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")

    assert 'id="deliveryPipeline"' in html
    assert "function renderDeliveryPipeline()" in javascript
    assert "/pipeline`" in javascript
    # Delivery acts on the QC dataset of the pair; corrections open the Production pole to fix.
    assert "state.deliveryProjectId=state.pipeline.delivery?.project_id||state.projectId" in javascript
    assert "openInProduction(production.id,Number(b.dataset.pole))" in javascript
    assert "versions/${v.id}/approve" in javascript and "state.deliveryProjectId||state.projectId" in javascript
    # Production lists Production datasets only; QC never shows unchecked Production poles as PASS.
    assert 'state.workspace==="PRODUCTION"?state.projects.filter(p=>p.production_dataset)' in javascript
    assert "if(summary.production_dataset){poles=[];" in javascript


def test_all_production_lidar_blocks_share_one_combined_viewer():
    javascript = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")
    workbook_editor = (ROOT / "web" / "assets" / "workbook-editor.js").read_text(encoding="utf-8")

    assert 'import "./workbook-editor.js?v=' in javascript
    assert 'data-annotation-tab="workbook"' in workbook_editor
    assert 'id="workbookPoleSearch"' in workbook_editor
    assert 'poleSearch.addEventListener("input",syncPoleOptions)' in workbook_editor
    assert 'id="poleWorkbookBusy"' in workbook_editor
    assert 'setBusy("Loading workbook data…")' in workbook_editor
    assert 'setBusy("Saving workbook changes…")' in workbook_editor
    assert 'loadedContext===key' in workbook_editor
    assert 'const selected=poleSelect.value||workbookPole.value' in workbook_editor
    assert 'id="workbookPoleSelect"' in workbook_editor
    assert '/workbook-download' in workbook_editor
    assert 'snapshot_file_id:snapshot.snapshot_file_id' in workbook_editor
    assert 'column===sheet.pole_number_column' in workbook_editor
    assert 'productionWorkbookPoleForGeoFeature(feature)' in javascript
    assert 'if(exactWorkbookPole)chooseProductionPole(exactWorkbookPole)' in javascript
    assert 'function selectedPoleAnnotations()' in javascript
    assert 'rows=selectedPoleAnnotations()' in javascript
    assert 'Select a Pole Number to view its saved points.' in javascript
    assert 'textContent="Combined LiDAR model"' in javascript
    assert "Promise.allSettled(blocks.map" in javascript
    assert "loadProductionPointCloud(block,generation,projectId)" in javascript
    assert "productionBlockForCoordinates(state.productionDraft)" in javascript
    assert "No points saved for this pole." in javascript


def test_login_page_has_brand_and_animated_background_without_api_url():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")
    background = (ROOT / "web" / "assets" / "login-background.js").read_text(encoding="utf-8")

    assert "<h1>JSAN PoleGrid</h1>" in html and "<p>LiDAR Utility Engineering Platform</p>" in html
    assert '<div class="login-page-brand"><img src="assets/logo.jpg" width="174" height="56" alt="JSAN" /></div>' in html
    assert (ROOT / "web" / "assets" / "logo.jpg").read_bytes()[:3] == b"\xff\xd8\xff"
    assert '<div class="brand-mark">J</div>' not in html
    assert "JSAN CONSULTING" not in html
    assert 'id="apiUrl"' not in html and "API URL" not in html
    assert '<canvas id="loginBackground" class="login-background" aria-hidden="true"></canvas>' in html
    # The animation runs only while the sign-in page is shown and honours reduced motion.
    assert "stopLoginBackground=startLoginBackground($(\"loginBackground\"))" in javascript
    assert "if(stopLoginBackground){stopLoginBackground();stopLoginBackground=null}" in javascript
    assert "export function startLoginBackground(canvas)" in background
    assert "(prefers-reduced-motion: reduce)" in background
    assert "return function stop()" in background
