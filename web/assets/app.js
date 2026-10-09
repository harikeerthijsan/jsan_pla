// Entry point. Feature code lives in ./modules/*.js; this file loads them, runs each module's one-time setup in
// the order the original single-file app used, then restores the session.
//
// All module imports must use the same ?v= value everywhere (scripts/set_web_version.py keeps them in sync); a
// mismatched specifier would load a second copy of a module with its own state.
import "./workbook-editor.js?v=20261009-directory-422";
import { init as initCore, $, api, showApp, showLogin, state, savedPage } from "./modules/core.js?v=20261009-directory-422";
import { init as initWorkspace, bootstrap } from "./modules/workspace.js?v=20261009-directory-422";
import { init as initQcRun } from "./modules/qc-run.js?v=20261009-directory-422";
import { init as initDelivery, init2 as init2Delivery } from "./modules/delivery.js?v=20261009-directory-422";
import { init as initQcReview } from "./modules/qc-review.js?v=20261009-directory-422";
import { init as initQcScene } from "./modules/qc-scene.js?v=20261009-directory-422";
import { init as initQcAnalysis } from "./modules/qc-analysis.js?v=20261009-directory-422";
import { init as initQcLayout } from "./modules/qc-layout.js?v=20261009-directory-422";
import { init as initUploads } from "./modules/uploads.js?v=20261009-directory-422";
import { init as initProductionData } from "./modules/production-data.js?v=20261009-directory-422";
import { init as initProductionAnnotations } from "./modules/production-annotations.js?v=20261009-directory-422";
import { init as initProductionPoles } from "./modules/production-poles.js?v=20261009-directory-422";
import { init as initProductionPick } from "./modules/production-pick.js?v=20261009-directory-422";
import { init as initProductionView } from "./modules/production-view.js?v=20261009-directory-422";
import { init as initProductionProfile } from "./modules/production-profile.js?v=20261009-directory-422";
import { init as initProductionGeo } from "./modules/production-geo.js?v=20261009-directory-422";
import { init as initProductionShell } from "./modules/production-shell.js?v=20261009-directory-422";
import { init as initProfile, init2 as init2Profile, openProfilePage } from "./modules/profile.js?v=20261009-directory-422";
import { init as initTeam, openTeamPage } from "./modules/team.js?v=20261009-directory-422";
import { init as initPointHistory } from "./modules/point-history.js?v=20261009-directory-422";
import { init as initNotifications } from "./modules/notifications.js?v=20261009-directory-422";
import { init as initTeamProgress } from "./modules/team-progress.js?v=20261009-directory-422";
import { init as initSuperAdmin, openSuperPage } from "./modules/super-admin.js?v=20261009-directory-422";
import { init as initLoginExperience } from "./modules/login-experience.js?v=20261009-directory-422";
import { init as initBrand } from "./modules/brand.js?v=20261009-directory-422";
import { init as initEmployeeDirectory } from "./modules/employee-directory.js?v=20261009-directory-422";

initCore();
initWorkspace();
initQcRun();
initDelivery();
initQcReview();
initQcScene();
initQcAnalysis();
initQcLayout();
initUploads();
initProductionData();
initProductionAnnotations();
initProductionPoles();
initProductionPick();
initProductionView();
initProductionProfile();
initProductionGeo();
initProductionShell();
initProfile();
initTeam();
initPointHistory();
init2Delivery();
initNotifications();
initTeamProgress();
initSuperAdmin();
init2Profile();
initLoginExperience();
initBrand();
initEmployeeDirectory();

// Reopen the page the person was on before a reload (workspace views are restored by chooseWorkspace itself).
function restorePage(page){const allowed=new Set(state.permissions||[]);if(page?.page==="profile"){openProfilePage();return true}
  if(page?.page==="super"&&allowed.has("super.view")){openSuperPage(page.tab||"people");return true}
  if(page?.page==="team"&&allowed.has("work.view_all")&&state.team){const all=page.scope==="all"&&allowed.has("super.view");if(!all&&!state.projectId)return false;state.team.scope=all?"all":"dataset";state.team.returnTo=page.returnTo||null;$("teamBackBtn").textContent=state.team.returnTo==="super"?"Back to Super admin":"Back to Production";openTeamPage();return true}
  return false}
(async function(){if(state.token&&state.apiBase){try{const me=await api('/api/auth/me');state.user={...(state.user||{}),...me};localStorage.setItem("pla_user",JSON.stringify(state.user));showApp();if(me.must_change_password){openProfilePage({forced:true});return}const page=savedPage();await bootstrap({restore:()=>restorePage(page)});return}catch{}}if(!$("loginError").textContent)showLogin()})();
