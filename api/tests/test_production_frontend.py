from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def web_javascript() -> str:
    """The reviewer UI's JavaScript: the app.js entry plus every feature module it loads."""
    assets = ROOT / "web" / "assets"
    files = [assets / "app.js", *sorted((assets / "modules").glob("*.js"))]
    return "\n".join(path.read_text(encoding="utf-8") for path in files)


def test_production_bounding_box_controls_and_clipping_are_wired():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    javascript = web_javascript()

    assert 'id="productionBoxBtn"' in html
    assert 'id="productionCloseBoxBtn"' in html
    assert "Potree.CameraMode.ORTHOGRAPHIC" in javascript
    assert "Potree.ClipTask.SHOW_INSIDE" in javascript
    assert "Potree.ClipMethod.INSIDE_ANY" in javascript
    assert "scene.removeVolume(state.productionClipVolume)" in javascript
    assert "zoomTo(state.productionClipVolume" in javascript


def test_production_box_tool_supports_the_combined_multi_cloud_model():
    javascript = web_javascript()

    # Potree's ScreenBoxSelectTool picks a single point cloud and throws on the
    # combined model, leaving the camera stuck in orthographic mode.
    assert "ScreenBoxSelectTool" not in javascript.replace("Potree's ScreenBoxSelectTool", "")
    assert "function startProductionBox(" in javascript
    assert "function cancelProductionBox(" in javascript
    assert "restoreProductionCamera(tool.previous)" in javascript
    assert "inputHandler.removeInputListener(tool.listener)" in javascript
    assert 'e.key!=="Escape"' in javascript


def test_production_box_fits_the_local_lidar_height_before_zooming():
    view = (ROOT / "web" / "assets" / "modules" / "production-view.js").read_text(encoding="utf-8")

    # The clip box must not inherit the full project's vertical range: one
    # distant bad elevation would make a small selection look like a tower and
    # force Potree to zoom far away from the selected points.
    assert "function productionBoxElevations(" in view
    assert "getMousePointCloudIntersection(mouse,camera,v,v.scene.pointclouds)" in view
    assert "function fittedProductionBoxRange(" in view
    assert "volume.position.set(frame.center.x,frame.center.y,range.center)" in view
    assert "volume.scale.set(frame.width,frame.height,range.depth)" in view
    assert "bounds.max.z-bounds.min.z+20" not in view
    assert "v.zoomTo(volume,.72,450)" in view


def test_production_box_offers_rectangle_and_four_point_polygon_modes():
    view = (ROOT / "web" / "assets" / "modules" / "production-view.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "assets" / "app.css").read_text(encoding="utf-8")

    assert "function installProductionBoxModeMenu()" in view
    assert 'data-box-mode="rectangle"' in view
    assert 'data-box-mode="polygon"' in view
    assert "function startProductionPolygonBox(" in view
    assert "if(points.length<4)" in view
    assert "function orientedProductionBox(points)" in view
    assert 'applyProductionBoxVolume(frame,a,b,returnCamera,"polygon",elevations)' in view
    assert "if(hit?.location&&inside(hit.location))" in view
    assert ".production-box-mode-menu" in css
    assert ".production-polygon-box" in css


def test_closing_production_box_returns_to_the_pre_box_pole_or_region():
    view = (ROOT / "web" / "assets" / "modules" / "production-view.js").read_text(encoding="utf-8")

    assert "returnCamera=state.productionBoxTool?.previous" in view
    assert "volume.plaReturnCamera=returnCamera" in view
    assert "const returnCamera=state.productionClipVolume?.plaReturnCamera" in view
    assert "clearProductionClip(false);restoreProductionCamera(returnCamera)" in view
    assert 'clearProductionClip(true);toast("Bounding box removed.' not in view


def test_production_navigation_controls_are_wired():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    javascript = web_javascript()
    app = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")
    direction = (ROOT / "web" / "assets" / "modules" / "production-direction.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "assets" / "app.css").read_text(encoding="utf-8")

    for view in ("top", "front", "side", "3d"):
        assert f'data-production-view="{view}"' in html
    assert 'id="productionNavModeBtn"' in html
    assert 'id="productionNavHint"' in html
    assert "installProductionNavigation(v)" in javascript
    assert "e.drag.mouse===4" in javascript
    # Saved markers are display-only so a drag over them orbits instead of moving them.
    assert "sphere._listeners={}" in javascript
    assert "initProductionDirection" in app and "./modules/production-direction.js" in app
    for direction_name in ("north", "south", "east", "west"):
        assert f'data-production-direction="{direction_name}"' in direction
    assert "function moveProductionDirection(direction)" in direction
    assert "vector.x*distance,vector.y*distance,0" in direction
    assert "view.position.add(offset)" in direction
    assert "radius*.4" in direction
    assert ".production-direction-pad" in css


def test_pole_line_navigation_option_is_removed():
    # "Line nav" (forward/back along the pole line) was removed from the viewer toolbar at the user's request.
    app = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "assets" / "app.css").read_text(encoding="utf-8")
    assert not (ROOT / "web" / "assets" / "modules" / "production-route.js").exists()
    assert "production-route.js" not in app and "initProductionRoute" not in app
    assert "productionRouteNavBtn" not in web_javascript() and ".production-route-bar" not in css


def test_production_profile_view_is_wired():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    javascript = web_javascript()

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
    assert 'setProductionView("top",{yaw:v.scene.view.yaw,pitch:-Math.PI/2})' in javascript
    assert 'toast("Top view: move the line and click the end of the profile."' in javascript
    assert 'addProductionMeasurement([point,point],{name:"Profile preview"' in javascript
    assert 'if(point)marker.setPosition(1,point)' in javascript
    assert 'dom.addEventListener("mousemove",onMove)' in javascript
    assert 'dom.removeEventListener("mousemove",onMove)' in javascript
    assert "function enterProductionProfile(a,b,previousCamera=null)" in javascript
    assert "if(restore)restoreProductionCamera(line.previous)" in javascript
    assert "p.volume.scale.set(p.len,p.depth" in javascript
    assert "startProductionProfileBox" not in javascript
    assert "production-profile-rect" not in javascript
    assert "v.orbitControls.rotationSpeed=0" in javascript
    assert "v.orbitControls.rotationSpeed=5" in javascript
    assert "function drawProductionProfileOverlay()" in javascript
    assert "above base" in javascript
    # Picks in the production viewer honour the clip so profile picks stay inside the slab.
    assert "pickClipped:true" in javascript
    # A click that can be neither snapped to LiDAR nor placed on a working plane must not create a draft at the origin.
    assert 'if(spot.error){toast(spot.error,"error",4500);return}' in javascript


def test_production_pick_lets_the_user_navigate_and_geojson_markers_are_large():
    javascript = web_javascript()
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
    javascript = web_javascript()

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
    javascript = web_javascript()

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
    javascript = web_javascript()
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


def test_selected_pole_focus_uses_the_original_workflow():
    production = (ROOT / "web" / "assets" / "modules" / "production-poles.js").read_text(encoding="utf-8")
    qc = (ROOT / "web" / "assets" / "modules" / "qc-scene.js").read_text(encoding="utf-8")

    # Keep the legacy selection camera behavior: the experimental height-based
    # close-focus implementation caused improper jumps in real datasets.
    assert "function productionPoleFocus(pole)" not in production
    assert "target=productionPoleTarget(pole)" in production
    assert 'view.radius=productionUnitLabel()==="ft"?120:36' in production
    assert "function poleFocusFrame(feature)" not in qc
    assert "const c=featureCenter(f)" in qc
    assert "c[0]+48,c[1]-48,c[2]+30" in qc


def test_qc_banner_runs_qc_on_production_lidar():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    javascript = web_javascript()
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
    javascript = web_javascript()

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
    javascript = web_javascript()
    workbook_editor = (ROOT / "web" / "assets" / "workbook-editor.js").read_text(encoding="utf-8")

    assert 'import "./workbook-editor.js?v=' in javascript
    assert 'data-annotation-tab="workbook"' in workbook_editor
    assert 'data-annotation-tab="geojson"' in workbook_editor
    assert 'id="poleGeojsonProperties"' in workbook_editor
    assert '/production-geo-features' in workbook_editor
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


def test_profile_import_manager_is_grouped_and_lidar_source_list_is_view_only():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    javascript = web_javascript()
    css = (ROOT / "web" / "assets" / "app.css").read_text(encoding="utf-8")

    assert 'id="profileImportsCard"' in html
    assert 'id="profileImports"' in html
    assert 'id="profileImportCount"' in html
    assert 'api("/api/admin/imports")' in javascript
    assert 'data-delete-import=' in javascript
    assert 'method:"DELETE"' in javascript and 'encodeURIComponent(projectId)' in javascript
    assert 'LIDAR_SOURCE:"LiDAR"' in javascript and 'GEOJSON:"GeoJSON"' in javascript and 'WORKBOOK:"Excel"' in javascript
    assert ".profile-import-row" in css and ".profile-import-files" in css
    # The Manage LiDAR shortcut was removed: imports are managed from the Profile page only.
    assert "productionManageLidarBtn" not in html and "productionManageLidarBtn" not in javascript
    assert 'sources.querySelector(".lidar-delete-btn")' not in javascript
    assert "deleteProductionLidar" not in javascript
    assert "lidar-delete-btn" not in javascript
    assert ".lidar-delete-btn" not in css
    assert '/uploads/${encodeURIComponent(file.id)}`' not in javascript


def test_login_page_has_brand_and_animated_background_without_api_url():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    javascript = web_javascript()
    background = (ROOT / "web" / "assets" / "login-background.js").read_text(encoding="utf-8")

    assert '<h1>JSAN PoleGrid<sup class="tm">™</sup></h1>' in html and "<p>LiDAR Utility Engineering Platform</p>" in html
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
    lidar_background = (
        Path(__file__).resolve().parents[2] / "web" / "assets" / "lidar-login-scene.js"
    ).read_text(encoding="utf-8")
    for feature in (
        "buildLidarScene",
        "drawPointCloud",
        "drawInfrastructure",
        "drawPoleGuides",
        "drawStreetViewCar",
        "drawPoleMeasurement",
        "drawViewerChrome",
    ):
        assert f"function {feature}(" in lidar_background
    assert "LIDAR CORRIDOR SCAN" in lidar_background
    assert "LIVE POINT CLOUD" in lidar_background
    assert "VIEWER TELEMETRY" in lidar_background
    assert "VISIBLE RETURNS" in lidar_background
    assert 'const modes = ["PLAN", "PROFILE", "CROSS", "3D"]' in lidar_background
    assert "Recognisable trees" in lidar_background
    assert "point-cloud building shells" in lidar_background
    assert "cylindrical transformer" in lidar_background
    assert "function drawScanPlane(" not in lidar_background
    assert "function cameraInspectionState(" in lidar_background
    assert "AUTO POLE ANALYSIS · LOCKED" in lidar_background
    assert "POLE MEASUREMENT LOCK" in lidar_background
    assert "const measuredHeight = topPoint.y - basePoint.y" in lidar_background
    assert "requestAnimationFrame" in lidar_background
    assert "ResizeObserver" in lidar_background
    assert "<video" not in html
    assert ".mp4" not in lidar_background
    assert ".webm" not in lidar_background


def test_team_progress_page_has_kpis_chart_leaders_and_sortable_table():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    javascript = web_javascript()
    css = (ROOT / "web" / "assets" / "app.css").read_text(encoding="utf-8")

    for element in ("teamSummary", "teamChart", "teamLeaders", "teamTable", "teamSearch", "teamShowIdle", "teamRefreshBtn", "teamBackBtn"):
        assert f'id="{element}"' in html
    assert all(f'data-team-days="{days}"' in html for days in (7, 14, 30))
    for function in ("renderTeamKpis", "renderTeamChart", "renderTeamLeaders", "renderTeamTable", "teamCountUp"):
        assert f"function {function}(" in javascript
    assert 'data-team-sort="${k}"' in javascript and "aria-sort" in javascript
    # Motion is decorative only: reduced-motion users get the final state without animation.
    assert "@media (prefers-reduced-motion:reduce){.team-page *{animation:none!important" in css
    # Pages never stretch past the viewport because of a wide header.
    assert ".app-shell{grid-template-columns:minmax(0,1fr)}" in css


def test_qc_workspace_layout_fixes_are_kept():
    css = (ROOT / "web" / "assets" / "app.css").read_text(encoding="utf-8")
    # Potree's canvas sits in a container that already starts below the 32px header; offsetting it again
    # left a blank band and cut off the bottom of the 3D view.
    assert "#qcWorkspace .three-card #potree_render_area>canvas{top:0}" in css
    # The other evidence canvases are still positioned from the 32px header.
    assert ".view-card canvas{position:absolute;left:0;right:0;top:32px;" in css
    # The pole search keeps its height in the flex column; the QC Evidence title no longer wraps.
    assert "#qcWorkspace .search{flex:0 0 auto;height:38px;" in css
    assert "#qcWorkspace .qc-panel .panel-head{display:grid;grid-template-columns:minmax(0,1fr) 128px" in css
    # KPI cards fit the 70px strip row instead of overflowing into the panels below.
    assert "#qcKpis{gap:12px;padding:5px 12px;" in css and "height:100%;padding:6px 14px 6px 18px" in css


def test_profile_page_keeps_its_ids_and_adds_password_helpers():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    javascript = web_javascript()

    # IDs the account, password and admin handlers depend on are all still present.
    for element in ("profileUsername", "profileEmail", "profileRole", "profileName", "profileNameForm", "passwordForm", "currentPassword",
                    "newPassword", "confirmPassword", "profileForcedNote", "profileBackBtn", "profileUsersCard", "profileUsers",
                    "profileCreateUserForm", "profileCreatePassword", "profileCreateConfirmPassword"):
        assert f'id="{element}"' in html
    for element in ("profileAvatar", "profileRoleChip", "profileHandleChip", "pwStrengthBar", "profileGeneratePassword", "profileUserSearch"):
        assert f'id="{element}"' in html
    assert all(f'data-pw-toggle="{field}"' in html for field in ("currentPassword", "newPassword", "confirmPassword"))
    for function in ("renderProfileHero", "updatePasswordHelpers", "renderProfileUsers", "loadProfileUsers"):
        assert f"function {function}(" in javascript
    # Temporary passwords come from the browser's cryptographic generator, never Math.random.
    generator = javascript[javascript.index('$("profileGeneratePassword").onclick'):]
    generator = generator[:generator.index("\n")]
    assert "crypto.getRandomValues" in generator and "Math.random" not in generator


def test_datasets_are_created_only_from_production_import():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    javascript = web_javascript()
    # QC and Delivery work on datasets imported in Production (QC links to the Production LiDAR); they have no
    # separate "New dataset" entry point.
    assert 'id="newDatasetBtn"' not in html and "newDatasetBtn" not in javascript
    assert 'id="productionUploadBtn"' in html
    # With no datasets yet, an admin is taken to Production's Import LiDAR instead of the old QC upload dialog.
    assert 'if(state.workspace!=="PRODUCTION"){state.workspace="PRODUCTION";' in javascript
    assert '$("productionUploadDialog").showModal()}return}' in javascript


def test_saved_points_have_quick_edit_and_remove_actions():
    javascript = web_javascript()
    pick = (ROOT / "web" / "assets" / "modules" / "production-pick.js").read_text(encoding="utf-8")
    points = (ROOT / "web" / "assets" / "modules" / "production-points.js").read_text(encoding="utf-8")
    # One remove path: open the point and run the existing Delete flow (confirmation, revision and parent checks).
    assert 'export function removeSavedPoint(id){' in javascript and '$("annotationDeleteBtn").click()' in javascript
    # Clicking a saved point in the 3D view opens its menu before GeoJSON pin selection.
    # Order: a saved point opens its menu, a pin head opens the GeoJSON card, anything else places a new point.
    assert "if(openPointMenuAt(px,py)||selectProductionGeoAt(px,py))return;placeProductionPointAt(px,py)" in javascript
    assert 'data-point-action="edit"' in javascript and 'data-point-action="delete"' in javascript
    # The saved-point action menu must not share the point-display settings ID. The settings document-level
    # mousedown handler otherwise hides the action menu before Edit or Delete receives its click.
    assert 'menu.id="productionPointActionMenu"' in pick
    assert '#productionPointActionMenu' in pick
    assert '$("productionPointMenu")' not in pick
    assert '$("productionPointMenu")' in points
    # Saved points list rows and the Pole base / top checklist rows offer delete directly.
    assert "data-row-delete" in javascript and "removeSavedPoint(row.id)" in javascript
    assert 'data-check-delete="${esc(row.id)}"' in javascript and "removeSavedPoint(button.dataset.checkDelete)" in javascript


def test_network_access_controls_are_wired():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    javascript = web_javascript()
    for element in ("profileNetworkCard", "networkEnabled", "networkYourIp", "networkAddMine", "networkList", "networkAddForm"):
        assert f'id="{element}"' in html
    # Users cut off mid-session are signed out with the reason; admins toggle per-user remote access.
    assert 'data?.detail==="network_not_allowed"){logout("Your account can only be used from the office network.' in javascript
    assert "data-remote-user=" in javascript and "remote_access:allow" in javascript


def test_sign_in_page_extras_are_wired():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    login = (ROOT / "web" / "assets" / "modules" / "login-experience.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "assets" / "login-lidar.css").read_text(encoding="utf-8")
    scene = (ROOT / "web" / "assets" / "lidar-login-scene.js").read_text(encoding="utf-8")
    for element in ('id="loginServerStatus"', 'id="passwordToggle"', 'id="capsLockNote"', 'class="login-spinner"', 'id="loginTicker"'):
        assert element in html, element
    # Enter submits, the button is busy while signing in, and the status comes from the public info endpoint.
    assert '"/api/system/info"' in login and 'button.click()' in login and 'classList.add("busy")' in login
    assert 'getModifierState("CapsLock")' in login
    # The card moves aside on wide screens so the pole inspection stays visible, and motion is optional.
    assert "place-items: center end" in css and "prefers-reduced-motion: reduce" in css
    assert "function drawStreetViewCar(" in scene and "function cardClearX(" in scene
    assert "function drawLaserSwath(" not in scene and "airborne" not in scene.lower()
    # The car is a mobile LiDAR mapping vehicle with a roof-mounted, spinning scanner head.
    assert "Mobile LiDAR mapping car" in scene and "spinning LiDAR head" in scene


def test_sign_in_entrance_plays_over_the_loading_app():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    core = (ROOT / "web" / "assets" / "modules" / "core.js").read_text(encoding="utf-8")
    login = (ROOT / "web" / "assets" / "modules" / "login-experience.js").read_text(encoding="utf-8")
    scene = (ROOT / "web" / "assets" / "lidar-login-scene.js").read_text(encoding="utf-8")
    assert 'id="loginEnter"' in html and 'PoleGrid<sup class="tm">™</sup> World' in html and 'id="loginEnterHello"' in html
    assert "`Welcome ${first}, now entering`" in login
    # Only a fresh sign-in (login page visible, scene running) gets the entrance; the app loads underneath.
    assert 'const entering=Boolean(entrance&&stopLoginBackground?.enter&&!loginView.classList.contains("hidden"))' in core
    assert "stopLoginBackground?.leave?.()" in core
    assert "setEntrance(playEntrance)" in login
    assert "stop.enter = (target = null) => new Promise" in scene and "function drawWarp(" in scene


def test_brand_line_decodes_engineering():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    brand = (ROOT / "web" / "assets" / "modules" / "brand.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "assets" / "app.css").read_text(encoding="utf-8")
    assert 'LiDAR Utility <span class="brand-engineering-wrap"><span id="brandEngineering"' in html and ">ENGINEERING</span></span> Platform</div>" in html
    assert 'const WORD = "ENGINEERING"' in brand and "prefers-reduced-motion: reduce" in brand
    assert ".brand-engineering{" in css and "@keyframes brandShimmer" in css


def test_super_admin_directory_tab_is_wired():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    module = (ROOT / "web" / "assets" / "modules" / "employee-directory.js").read_text(encoding="utf-8")
    super_admin = (ROOT / "web" / "assets" / "modules" / "super-admin.js").read_text(encoding="utf-8")
    assert 'data-super-tab="directory"' in html and 'id="superDirectoryView"' in html
    for element in ("dirSearch", "dirAccess", "dirRole", "dirDept", "dirDesig", "dirHrRole", "dirBulkGrant", "dirGrantDialog", "dirCredsDialog", "dirEditDialog", "dirImportFile"):
        assert f'id="{element}"' in html, element
    # All three roles can be granted from the directory, one at a time or in bulk.
    assert html.count('value="SUPER_ADMIN"') >= 3
    assert 'if(tab==="directory")loadDirectory()' in super_admin
    # Account changes reuse the guarded account route; temporary passwords are dropped when the dialog closes.
    assert "/api/users/${encodeURIComponent(e.account.id)}" in module and 'dir.creds = []; $("dirCredsBody").innerHTML = ""' in module


def test_validation_errors_are_readable_and_username_patterns_are_valid_for_chrome():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    core = (ROOT / "web" / "assets" / "modules" / "core.js").read_text(encoding="utf-8")
    # An unescaped trailing "-" makes Chrome (v-flag patterns) ignore the rule, letting bad usernames reach the API.
    assert 'pattern="[A-Za-z0-9._-]' not in html and html.count('pattern="[A-Za-z0-9._\\-]') == 4
    assert "export function errorText(detail)" in core and "new Error(errorText(data?.detail)" in core
    assert 'string_pattern_mismatch"?"may use only letters, numbers, dot, dash and underscore (no spaces)"' in core


def test_production_quick_save_card_and_measurement_tool():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "web" / "assets" / "app.css").read_text(encoding="utf-8")
    quick = (ROOT / "web" / "assets" / "modules" / "production-quicksave.js").read_text(encoding="utf-8")
    measure = (ROOT / "web" / "assets" / "modules" / "production-measure.js").read_text(encoding="utf-8")
    pick = (ROOT / "web" / "assets" / "modules" / "production-pick.js").read_text(encoding="utf-8")
    # Saving happens in the card next to the picked point; it drives the existing form so its rules still apply.
    assert "#annotationForm .annotation-actions{display:none}" in css
    assert '$("annotationForm").requestSubmit()' in quick and '$("annotationCancelBtn").click()' in quick and '$("annotationDeleteBtn").click()' in quick
    # Measurement section sits under the pole / attachments checklist; two picks, line + tag in 3D, values in the panel.
    assert html.index('id="productionChecklist"') < html.index('id="productionMeasurePanel"')
    assert "export function startProductionMeasure()" in measure and "function values(a, b)" in measure
    assert "horizontal" in measure and "vertical" in measure and "measure-label" in measure
    # Display units are selectable without altering source coordinates or stored tape values.
    assert 'Object.freeze({ ft: 0.3048, m: 1, cm: 0.01, mm: 0.001 })' in measure
    assert "export function convertMeasurementValue(" in measure
    assert 'data-measure-unit aria-label="Measurement display unit"' in measure
    for unit in ("ft", "mm", "cm", "m"):
        assert f'["{unit}",' in measure
    assert "refreshMeasurementLabels();" in measure
    assert ".measure-unit{" in css
    assert "cancelProductionMeasure();const v=state.productionViewer" in pick


def test_production_colour_modes_and_hidden_more_fields():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    colour = (ROOT / "web" / "assets" / "modules" / "production-colour.js").read_text(encoding="utf-8")
    data = (ROOT / "web" / "assets" / "modules" / "production-data.js").read_text(encoding="utf-8")
    # The colour dropdown and point-size controls sit right before the Top / Front / Side / 3D buttons, in the viewer toolbar.
    toolbar = html.index('class="production-viewer-tools"')
    assert toolbar < html.index('id="productionColourMode"') < html.index('id="productionPointSmaller"') < html.index('data-production-view="top"') < html.index('id="productionProfileBtn"')
    for value, label in (("intensity", "Intensity view"), ("rgb", "RGB view"), ("elevation", "Elevation view")):
        assert f'<option value="{value}"' in html and label in html
    assert 'const MODES = { intensity: "intensity", rgb: "rgba", elevation: "elevation" }' in colour
    assert "colourProductionPointCloud(e.pointcloud)" in data and 'activeAttributeName="elevation"' not in data
    # "More fields" stays in the page for the save card to mirror, but is no longer shown.
    assert '<details class="production-more hidden" aria-hidden="true">' in html


def test_production_point_size_shape_and_detail_controls():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    points = (ROOT / "web" / "assets" / "modules" / "production-points.js").read_text(encoding="utf-8")
    data = (ROOT / "web" / "assets" / "modules" / "production-data.js").read_text(encoding="utf-8")
    workspace = (ROOT / "web" / "assets" / "modules" / "workspace.js").read_text(encoding="utf-8")
    for element in ("productionPointSmaller", "productionPointBigger", "productionPointSlider", "productionPointMenu"):
        assert f'id="{element}"' in html, element
    assert 'data-point-shape="round"' in html and 'data-point-detail="ultra"' in html
    # Close-up squares came from a 2.2M point budget running out; detail is now a setting (default 5M) and squares are capped.
    assert "high: 5_000_000" in points and "m.uniforms.maxSize.value" in points and "Potree.maxNodesLoading = 8" in points
    assert "styleProductionPointCloud(e.pointcloud)" in data and "applyProductionPointSettings()" in workspace


def test_points_can_be_placed_in_open_space():
    pick = (ROOT / "web" / "assets" / "modules" / "production-pick.js").read_text(encoding="utf-8")
    placement = (ROOT / "web" / "assets" / "modules" / "production-placement.js").read_text(encoding="utf-8")
    measure = (ROOT / "web" / "assets" / "modules" / "production-measure.js").read_text(encoding="utf-8")
    # No more "No LiDAR point under the cursor": snap first, otherwise a working plane.
    assert "No LiDAR point under the cursor" not in pick and "spot=pickOrPlace(" in pick
    assert 'placement:state.productionDraftPlacement||"lidar"' in pick
    assert 'button.id = "productionPlacementModeBtn"' in placement
    assert 'forceOpen: state.productionPlacementMode === "free"' in placement
    assert "pickOrPlace(px,py,annotationPickOptions())" in pick
    for plane in ("section_plane", "pole_plane", "ground_plane", "view_plane"):
        assert f'placement: "{plane}"' in placement or f'"{plane}"' in placement, plane
    assert "pickOrPlace(event.clientX - r.left, event.clientY - r.top)" in measure


def test_clicking_the_lidar_places_a_point_and_the_card_asks_what_it_is():
    css = (ROOT / "web" / "assets" / "app.css").read_text(encoding="utf-8")
    pick = (ROOT / "web" / "assets" / "modules" / "production-pick.js").read_text(encoding="utf-8")
    quick = (ROOT / "web" / "assets" / "modules" / "production-quicksave.js").read_text(encoding="utf-8")
    geo = (ROOT / "web" / "assets" / "modules" / "production-geo.js").read_text(encoding="utf-8")
    # The Pole / Attachments & structure checklist is no longer shown in the side panel.
    assert "#productionChecklist{display:none}" in css
    assert "export function placeProductionPointAt(px,py){" in pick and "productionPoleTarget(pole)" in pick
    # The card keeps it simple: the Group and Point / variable selects say what the point is; the pole is chosen
    # automatically (the selected pole near the click, else the nearest pole).
    assert 'id="qsFamily"' in quick and 'id="qsFeature"' in quick
    assert "qsTypes" not in quick and "qsPole" not in quick
    # Pins open their card from the head only, so clicks on the pole itself place points.
    assert "d=Math.max(0,Math.hypot(px-head.x,py-head.y)-head.r);if(d<=6" in geo


def test_coordinates_and_street_view_live_in_the_save_card():
    css = (ROOT / "web" / "assets" / "app.css").read_text(encoding="utf-8")
    quick = (ROOT / "web" / "assets" / "modules" / "production-quicksave.js").read_text(encoding="utf-8")
    # The side panel no longer shows latitude / longitude, X / Y / Z or the Street View button.
    assert "#annotationForm .geographic-readout,#annotationForm .coordinate-readout{display:none!important}" in css
    # The card shows them, each value copies on click, "Copy all" copies everything, Street View uses the existing button.
    for key in ("X", "Y", "Z", "Lat", "Lon"):
        assert f'data-qs-copy="{key}"' in quick and f'id="qs{key}"' in quick, key
    # Each value copies on its own (no "Copy all").
    assert 'data-qs="copyall"' not in quick and quick.count('class="qs-copy-icon"') == 5
    assert 'data-qs="streetview"' in quick and '$("annotationStreetView").click()' in quick
    assert "navigator.clipboard.writeText(text)" in quick


def test_map_picker_preserves_lidar_elevation_and_uses_server_crs_transform():
    app = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "assets" / "app.css").read_text(encoding="utf-8")
    quick = (ROOT / "web" / "assets" / "modules" / "production-quicksave.js").read_text(encoding="utf-8")
    map_picker = (ROOT / "web" / "assets" / "modules" / "production-map.js").read_text(encoding="utf-8")
    config = (ROOT / "web" / "config.js").read_text(encoding="utf-8")
    assert "initProductionMap" in app
    assert 'data-qs="map"' in quick and "openProductionMapPicker()" in quick
    assert "/coordinates/from-wgs84" in map_picker and "/coordinates/to-wgs84" in map_picker
    assert 'const button = $("productionMapUseBtn"), z = state.productionDraft.z;' in map_picker
    assert 'setAnnotationDraft({ x: result.x, y: result.y, z })' in map_picker
    assert 'state.productionDraftPlacement = "map"' in map_picker
    assert "tile.openstreetmap.org/{z}/{x}/{y}.png" in config
    assert "ol.Attribution" in map_picker and ".production-map-dialog" in css


def test_georeferenced_map_overlay_has_toggle_tile_cap_and_intensity_control():
    # OpenStreetMap attribution stays visible, but is positioned independently
    # so the intensity control cannot collide with viewer navigation controls.
    core = (ROOT / "web" / "assets" / "modules" / "core.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "assets" / "app.css").read_text(encoding="utf-8")
    map_overlay = (ROOT / "web" / "assets" / "modules" / "production-map.js").read_text(encoding="utf-8")
    assert 'button.id = "productionMapOverlayBtn"' in map_overlay
    assert 'id="productionMapIntensity"' in map_overlay and "applyOverlayIntensity()" in map_overlay
    assert 'attribution.id = "productionMapAttribution"' in map_overlay
    assert 'attribution.textContent = "© OpenStreetMap"' in map_overlay
    assert "control.innerHTML = `<label><span>Map intensity</span>" in map_overlay
    assert "const MAX_OVERLAY_TILES = 64" in map_overlay
    assert "/coordinates/from-wgs84/batch" in map_overlay
    assert 'new THREE.MeshBasicMaterial({ map: texture' in map_overlay
    assert 'state.productionMapOverlayIntensity = Number(event.target.value) / 100' in map_overlay
    assert "productionMapOverlayVisible:false" in core
    assert ".production-map-intensity" in css
    assert ".production-map-attribution" in css
    assert ".production-map-intensity a" not in css


def test_automatic_sign_out_after_five_idle_minutes():
    app = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")
    idle = (ROOT / "web" / "assets" / "modules" / "idle-timeout.js").read_text(encoding="utf-8")
    assert "initIdleTimeout" in app
    assert "export const IDLE_MINUTES = 5;" in idle and "logout(" in idle
    # Warns for the last minute, shares activity between tabs, and never signs out during a request in progress.
    assert "const WARN_MS = 60 * 1000;" in idle and 'const SHARED_KEY = "pla_last_activity";' in idle
    assert "if (inFlight > 0) { touch(); return; }" in idle


def test_login_mapping_car_drives_into_the_entrance_logo():
    scene = (ROOT / "web" / "assets" / "lidar-login-scene.js").read_text(encoding="utf-8")
    login = (ROOT / "web" / "assets" / "modules" / "login-experience.js").read_text(encoding="utf-8")
    assert "function drawStreetViewCar(" in scene and "function carPose(" in scene and "function drawLogoPulse(" in scene
    assert "stop.enter = (target = null) =>" in scene and "logoTarget" in scene
    assert 'document.querySelector("#loginEnter .login-enter-mark")' in login and "await warp(target)" in login


def test_save_card_shows_the_workbook_attribute_fields():
    quick = (ROOT / "web" / "assets" / "modules" / "production-quicksave.js").read_text(encoding="utf-8")
    pick = (ROOT / "web" / "assets" / "modules" / "production-pick.js").read_text(encoding="utf-8")
    # Fields come from the group's catalogue entry; every dropdown has "Other (type a value)" with a text box.
    assert "function renderFields()" in quick and "group?.fields" in quick
    assert 'Other (type a value)' in quick and "data-attr-other" in quick and "data-attr-text" in quick
    # The values are saved with the point.
    assert "export function featureAttributes()" in pick and "...featureAttributes()" in pick


def test_profile_view_overlays_follow_the_toolbar_and_the_cursor():
    modules = ROOT / "web" / "assets" / "modules"
    profile = (modules / "production-profile.js").read_text(encoding="utf-8")
    geo = (modules / "production-geo.js").read_text(encoding="utf-8")
    points = (modules / "production-points.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "assets" / "app.css").read_text(encoding="utf-8")
    # The cursor/Z overlay is aligned to the 3D canvas on every draw, so the cursor line matches the pointer.
    assert "canvasBox.top-hostBox.top" in profile
    # The profile bar, intensity control and GeoJSON card stack below the (wrapping) toolbar and the profile bar.
    assert '"--profile-bar-h"' in points and '"--viewer-head-h"' in points
    assert ".production-viewer .production-profile-bar{top:var(--viewer-overlay-top)}" in css
    assert "var(--viewer-overlay-top, 54px) + var(--profile-bar-h, 46px)" in geo
    # The direction pad stays clear of the elevation ruler, and pins repaint as soon as the slab changes.
    assert ".production-direction-pad{right:86px}" in css
    assert "  drawProductionGeoMarkers()}" in geo


def test_confirmations_use_the_in_page_dialog_not_browser_popups():
    import re
    modules = ROOT / "web" / "assets" / "modules"
    core = (modules / "core.js").read_text(encoding="utf-8")
    assert "export function confirmAction(" in core and 'role="alertdialog"' in core
    for path in sorted(modules.glob("*.js")):
        text = "\n".join(line for line in path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("//"))
        assert not re.search(r"(?<![\w.])(window\.)?confirm\(", text), f"{path.name} still uses the browser confirm popup"
    pick = (modules / "production-pick.js").read_text(encoding="utf-8")
    assert 'await confirmAction("Delete this saved production point?' in pick
