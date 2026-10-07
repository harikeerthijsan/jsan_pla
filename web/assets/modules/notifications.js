// Notification bell, panel and polling.
import { $, api, esc, state, toast } from "./core.js?v=20261007-tab-order";
import { openInProduction, openInQc } from "./delivery.js?v=20261007-tab-order";
import { applyWorkspace } from "./workspace.js?v=20261007-tab-order";

export const NOTIFY_ICONS={QC_ISSUES_ON_YOUR_POLES:"!",QC_FINISHED:"✓",QC_FAILED:"×",CORRECTION_REQUESTED:"↺",CORRECTION_RESOLVED:"✓",VERSION_APPROVED:"★",POLES_ASSIGNED:"→"};
export function notifyAgo(iso){const s=Math.max(0,(Date.now()-new Date(iso).getTime())/1000);if(s<60)return "just now";if(s<3600)return `${Math.floor(s/60)} min ago`;if(s<86400)return `${Math.floor(s/3600)} h ago`;return new Date(iso).toLocaleDateString()}
export function renderNotifications(unread){const count=$("notifyCount");count.textContent=unread>99?"99+":String(unread);count.classList.toggle("hidden",!unread);$("notifyBtn").setAttribute("aria-label",unread?`Notifications, ${unread} unread`:"Notifications");$("notifyReadAll").disabled=!unread;$("notifyList").innerHTML=state.notifications.map(n=>`<button type="button" class="notify-item${n.read?"":" unread"} kind-${esc(String(n.kind).toLowerCase())}" data-notification="${esc(n.id)}"><i aria-hidden="true">${NOTIFY_ICONS[n.kind]||"•"}</i><span><b>${esc(n.title)}</b>${n.body?`<small>${esc(n.body)}</small>`:""}<em>${notifyAgo(n.created_at)}</em></span></button>`).join("")||'<div class="empty-workflow">No notifications yet.</div>'}
export async function loadNotifications(){if(!state.token||state.user?.must_change_password)return;try{const data=await api("/api/notifications?limit=30");state.notifications=data.items;renderNotifications(data.unread)}catch{}}
export function toggleNotifications(open){const panel=$("notifyPanel"),show=open??panel.classList.contains("hidden");panel.classList.toggle("hidden",!show);$("notifyBtn").setAttribute("aria-expanded",String(show));if(show)loadNotifications()}

// One-time setup (original statements 289–301); called by app.js in the original order.
export function init() {
  state.notifications=[];
  $("notifyBtn").onclick=event=>{event.stopPropagation();toggleNotifications()};
  document.addEventListener("click",event=>{if(!event.target.closest(".notify-wrap"))toggleNotifications(false)});
  document.addEventListener("keydown",event=>{if(event.key==="Escape"&&!$("notifyPanel").classList.contains("hidden"))toggleNotifications(false)});
  $("notifyReadAll").onclick=async()=>{try{await api("/api/notifications/read-all",{method:"POST"});await loadNotifications()}catch(e){toast(e.message,"error")}};
  $("notifyList").addEventListener("click",async event=>{const item=event.target.closest("[data-notification]");if(!item)return;const n=state.notifications.find(x=>String(x.id)===item.dataset.notification);toggleNotifications(false);if(n&&!n.read){try{await api(`/api/notifications/${n.id}/read`,{method:"POST"})}catch{}}loadNotifications();const link=n?.link||{};if(!link.project_id)return;if(!state.projects.some(p=>p.id===link.project_id))state.projects=await api("/api/projects");if(link.workspace==="PRODUCTION")openInProduction(link.project_id,link.pole_internal_id??null);else if(link.workspace==="QC")openInQc(link.project_id);else{state.projectId=link.project_id;localStorage.setItem("pla_project_id",link.project_id);state.workspace="DELIVERY";localStorage.setItem("pla_workspace","DELIVERY");applyWorkspace()}});
  setInterval(loadNotifications,60000);
  document.addEventListener("visibilitychange",()=>{if(!document.hidden)loadNotifications()});
}
