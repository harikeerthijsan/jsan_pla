// Viewer creation, permissions, workspace switching, dataset selection and bootstrap.
import * as THREE from "../../potree/libs/three.js/build/three.module.js";
import { applyProductionPointSettings } from "./production-points.js?v=20261022-saved-point-layer";
import { $, api, state, rememberPage, updatePageTitle } from "./core.js?v=20261022-saved-point-layer";
import { loadWorkflow } from "./delivery.js?v=20261022-saved-point-layer";
import { loadNotifications } from "./notifications.js?v=20261022-saved-point-layer";
import { loadProduction } from "./production-data.js?v=20261022-saved-point-layer";
import { installProductionNavigation } from "./production-view.js?v=20261022-saved-point-layer";
import { clearCanvases } from "./qc-analysis.js?v=20261022-saved-point-layer";
import { renderPoles, renderSummary } from "./qc-review.js?v=20261022-saved-point-layer";
import { loadProject } from "./qc-run.js?v=20261022-saved-point-layer";
import { clearClouds, clearThreeGroup } from "./qc-scene.js?v=20261022-saved-point-layer";

// A viewer on a hidden page (QC while in Production, and the other way round) has a 0×0 canvas. Potree would still
// update and draw it every frame, which wastes CPU/GPU and floods the console with GL_INVALID_FRAMEBUFFER_OPERATION
// warnings. Skip those frames; the viewer picks up again as soon as its page is shown.
export function pauseWhenHidden(v){const dom=v.renderer.domElement,shown=()=>dom.clientWidth>0&&dom.clientHeight>0,update=v.update.bind(v),render=v.render.bind(v);v.update=(delta,timestamp)=>{if(shown())update(delta,timestamp)};v.render=(...args)=>{if(shown())render(...args)}}
// Potree starts a new decoding Web Worker whenever none is free, with no upper limit. A dataset with many LiDAR tiles
// (e.g. 43) then decodes ~43 tiles at once in ~43 workers, each with its own LAZ decoder, which freezes the tab and runs
// it out of memory. Cap the pool: at most MAX workers per decoder script; extra jobs queue and run as workers free up.
// Potree's loaders all follow getWorker -> onmessage/postMessage -> returnWorker, so a queued stand-in is transparent.
export function limitPotreeWorkers(max=Math.max(2,Math.min(4,(navigator.hardwareConcurrency||4)-1))){const pool=window.Potree?.workerPool;if(!pool||pool.__limited)return;pool.__limited=true;const idle={},count={},waiting={};
  const acquire=(url,use)=>{const free=(idle[url]||=[]);if(free.length){use(free.pop());return}if((count[url]||0)<max){count[url]=(count[url]||0)+1;use(new Worker(url));return}(waiting[url]||=[]).push(use)};
  const release=(url,worker)=>{const next=(waiting[url]||[]).shift();if(next)next(worker);else (idle[url]||=[]).push(worker)};
  class QueuedWorker{constructor(url){this.url=url;this.real=null;this.onmessage=null;this.onerror=null}
    postMessage(message,transfer){acquire(this.url,worker=>{this.real=worker;worker.onmessage=e=>this.onmessage?.(e);worker.onerror=e=>{this.onerror?.(e);const w=this.real;this.real=null;if(w)release(this.url,w)};worker.postMessage(message,transfer)})}
    terminate(){}}
  pool.getWorker=url=>new QueuedWorker(url);
  pool.returnWorker=(url,worker)=>{const real=worker instanceof QueuedWorker?worker.real:worker;if(worker instanceof QueuedWorker)worker.real=null;if(real)release(url,real)}}
export function initViewer(){if(state.viewer)return;limitPotreeWorkers();const v=new Potree.Viewer($("potree_render_area"));pauseWhenHidden(v);v.setEDLEnabled(true);v.setFOV(60);v.setPointBudget(2200000);v.setBackground("gradient");state.viewer=v;state.overlay=new THREE.Group();state.relation=new THREE.Group();v.scene.scene.add(state.overlay);v.scene.scene.add(state.relation)}
export function initProductionViewer(){if(state.productionViewer)return;limitPotreeWorkers();const v=new Potree.Viewer($("production_render_area"));pauseWhenHidden(v);v.setEDLEnabled(true);v.setFOV(60);v.setPointBudget(2200000);v.setBackground("gradient");state.productionViewer=v;applyProductionPointSettings();installProductionNavigation(v)}
export function can(permission){return state.permissions.has(permission)}
export function renderRuntime(){const r=state.runtime||{};const env=(r.railway_environment||r.app_env||"local").toUpperCase();const version=String(r.version||"3.4").replace(/-operational$/,""),badge=$("runtimeBadge");if(badge){badge.textContent=`v${version.replace(/^v/,"")} · ${env}`;badge.className=`version env-${env.toLowerCase()}`}updatePageTitle()}
export function applyWorkspace(){rememberPage("workspace");$("profilePage").classList.add("hidden");$("teamPage").classList.add("hidden");$("superPage").classList.add("hidden");$("superAdminBtn").classList.toggle("hidden",!can("super.view"));$("teamProgressBtn").classList.toggle("hidden",!can("work.view_all"));$("poleAssignBtn").classList.toggle("hidden",!can("user.manage"));$("appView").classList.remove("profile-open");const available=state.workspaces.length;$("workspaceSwitch").classList.toggle("hidden",available<2);for(const name of ["PRODUCTION","DELIVERY","QC"]){const id=name.toLowerCase()+"WorkspaceBtn";$(id)?.classList.toggle("active",state.workspace===name)}$("productionWorkspace").classList.toggle("hidden",state.workspace!=="PRODUCTION");$("deliveryWorkspace").classList.toggle("hidden",state.workspace!=="DELIVERY");$("qcWorkspace").classList.toggle("hidden",state.workspace!=="QC");$("qcKpis").classList.toggle("hidden",state.workspace!=="QC");$("productionUploadBtn").classList.toggle("hidden",!can("project.create"));$("reprocessBtn").classList.toggle("hidden",state.workspace==="PRODUCTION"||!can("processing.run"));const projectChanged=state.projects?.length?syncWorkspaceProject():false;if(state.workspace==="PRODUCTION"){initProductionViewer();if(state.projectId)loadProduction()}else if(state.workspace==="DELIVERY"&&state.projectId)loadWorkflow();else if(state.workspace==="QC"&&(projectChanged||state.projectStale))loadProject();state.projectStale=false;if(!state.projects?.length)clearProject()}
export function chooseWorkspace(){if(!state.workspaces.includes(state.workspace))state.workspace=state.workspaces.includes("PRODUCTION")?"PRODUCTION":(state.workspaces.includes("DELIVERY")?"DELIVERY":"QC");localStorage.setItem("pla_workspace",state.workspace);applyWorkspace()}
export async function bootstrap({restore=null}={}){loadNotifications();const [runtime,access,projects]=await Promise.all([api("/api/system/info"),api("/api/workspaces"),api("/api/projects")]);state.runtime=runtime;state.workspaces=access.workspaces||[];state.permissions=new Set(access.permissions||[]);state.projects=projects;renderRuntime();chooseWorkspace();if(state.workspaces.includes("QC"))initViewer();renderProjectSelect();if(!state.projects.length){clearProject();if(restore?.())return;if(can("project.create")){if(state.workspace!=="PRODUCTION"){state.workspace="PRODUCTION";localStorage.setItem("pla_workspace","PRODUCTION");applyWorkspace()}$("productionUploadDialog").showModal()}return}const listed=workspaceProjects().length?workspaceProjects():state.projects;if(!state.projectId||!listed.some(p=>p.id===state.projectId))state.projectId=listed[0].id;$("projectSelect").value=state.projectId;localStorage.setItem("pla_project_id",state.projectId);restore?.();await loadProject()}
export async function refreshProjects(){state.projects=await api("/api/projects");if(!state.projects.some(p=>p.id===state.projectId)){const list=workspaceProjects().length?workspaceProjects():state.projects;state.projectId=list[0]?.id||null;if(state.projectId)localStorage.setItem("pla_project_id",state.projectId);else localStorage.removeItem("pla_project_id");state.projectStale=true}renderProjectSelect()}
export function currentProject(){return state.projects.find(p=>p.id===state.projectId)||{units:"project units"}}
export function workspaceProjects(){return state.workspace==="PRODUCTION"?state.projects.filter(p=>p.production_dataset):state.projects}
export function renderProjectSelect(){const s=$("projectSelect");s.innerHTML="";for(const p of workspaceProjects()){const o=document.createElement("option");o.value=p.id;o.textContent=`${p.name}${state.workspace!=="PRODUCTION"&&p.production_dataset?" · Production":""} · ${p.status}`;s.appendChild(o)}if(state.projectId)s.value=state.projectId;updatePageTitle()}
export function syncWorkspaceProject(){renderProjectSelect();const list=workspaceProjects();if(list.length&&!list.some(p=>p.id===state.projectId)){state.projectId=list[0].id;localStorage.setItem("pla_project_id",state.projectId);$("projectSelect").value=state.projectId;return true}return false}
export function clearProject(){state.poles=[];state.summary={poles:0,fail:0,review:0,unverifiable:0,open_findings:0};renderSummary();renderPoles();clearClouds();clearThreeGroup(state.overlay);clearThreeGroup(state.relation);$("viewerTitle").textContent="Upload a dataset";$("viewerSub").textContent="COLLECTION workbook + LAS/LAZ/COPC";clearCanvases()}

const appView=()=>$("appView");
// One-time setup (original statements 17–32); called by app.js in the original order.
export function init() {
  $("brandHome").onclick=event=>{event.preventDefault();if(appView().classList.contains("hidden"))return;state.workspace=state.workspaces.includes("PRODUCTION")?"PRODUCTION":state.workspace;localStorage.setItem("pla_workspace",state.workspace);chooseWorkspace();window.scrollTo({top:0,behavior:"smooth"})};
  $("productionWorkspaceBtn").onclick=()=>{state.workspace="PRODUCTION";localStorage.setItem("pla_workspace","PRODUCTION");applyWorkspace()};
  $("deliveryWorkspaceBtn").onclick=()=>{state.workspace="DELIVERY";localStorage.setItem("pla_workspace","DELIVERY");applyWorkspace()};
  $("qcWorkspaceBtn").onclick=()=>{state.workspace="QC";localStorage.setItem("pla_workspace","QC");applyWorkspace()};
  $("projectSelect").onchange=async()=>{state.projectId=$("projectSelect").value;localStorage.setItem("pla_project_id",state.projectId);state.currentPole=null;state.analysis=null;state.section=null;await loadProject()};
}
