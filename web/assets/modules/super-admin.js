// Super admin page: every account with its access and work, and a timeline of everyone's actions.
// Only shown to accounts with the super.view permission; the server enforces it on every route.
import { $, api, esc, state, toast } from "./core.js?v=20261008-project-delete-2";
import { roleLabel, signInCell } from "./profile.js?v=20261008-project-delete-2";
import { teamAgo, teamAvatar } from "./team-progress.js?v=20261008-project-delete-2";
import { openTeamPage } from "./team.js?v=20261008-project-delete-2";
import { applyWorkspace } from "./workspace.js?v=20261008-project-delete-2";

const ROLES=["USER","ADMIN","SUPER_ADMIN"];
const GROUPS={production:"Production",qc:"QC",data:"Data",delivery:"Delivery",accounts:"Accounts",other:"Other"};

export function openSuperPage(tab=state.superAdmin.tab){for(const id of ["productionWorkspace","deliveryWorkspace","qcWorkspace","qcKpis","profilePage","teamPage"])$(id).classList.add("hidden");$("superPage").classList.remove("hidden");showTab(tab);loadPeople()}

function showTab(tab){state.superAdmin.tab=tab;document.querySelectorAll("[data-super-tab]").forEach(b=>{const on=b.dataset.superTab===tab;b.classList.toggle("active",on);b.setAttribute("aria-selected",String(on))});$("superPeopleView").classList.toggle("hidden",tab!=="people");$("superActivityView").classList.toggle("hidden",tab!=="activity");if(tab==="activity"&&!state.superAdmin.activity.loaded)loadActivity(true)}

async function loadPeople(){const root=$("superPeople");root.innerHTML='<div class="team-skeleton-block short"></div>';try{const people=await api(`/api/super/people?days=${state.superAdmin.days}`);people.sort((a,b)=>ROLES.indexOf(String(b.role).toUpperCase())-ROLES.indexOf(String(a.role).toUpperCase())||String(a.username||a.email).localeCompare(String(b.username||b.email),undefined,{numeric:true}));state.superAdmin.people=people;renderPeople();fillActivityFilters()}catch(e){root.innerHTML=`<div class="team-empty error"><b>People could not load</b><small>${esc(e.message)}</small></div>`}}

function accessCell(u){if(String(u.role).toUpperCase()==="SUPER_ADMIN")return '<span class="profile-status">Anywhere (super admin)</span>';return `<button type="button" class="net-access-btn${u.remote_access?" anywhere":""}" data-super-remote="${esc(u.id)}" data-remote="${u.remote_access?"false":"true"}" data-name="${esc(u.username||u.email)}" title="${u.remote_access?"Limit to office networks":"Allow from anywhere"}">${u.remote_access?"Anywhere":"Office only"}</button>`}

function roleCell(u,mine){const role=String(u.role).toUpperCase();if(mine)return `<span class="profile-role admin">${esc(roleLabel(role))}</span>`;const options=[...new Set([...ROLES,role])];return `<select class="super-role" data-super-role="${esc(u.id)}" data-name="${esc(u.username||u.email)}" data-current="${esc(role)}" aria-label="Role of ${esc(u.username||u.email)}">${options.map(r=>`<option value="${r}"${r===role?" selected":""}>${esc(roleLabel(r))}</option>`).join("")}</select>`}

export function renderPeople(){const root=$("superPeople"),q=($("superPeopleSearch").value||"").trim().toLowerCase(),people=state.superAdmin.people||[],days=state.superAdmin.days;
  const counts=ROLES.map(r=>{const n=people.filter(u=>String(u.role).toUpperCase()===r).length;return `${n} ${roleLabel(r).toLowerCase()}${n===1?"":"s"}`});$("superPeopleMeta").textContent=`${people.length} accounts · ${counts.join(" · ")} · work in the last ${days} days`;
  const rows=people.filter(u=>!q||`${u.username||""} ${u.name||""} ${u.email||""} ${u.role||""}`.toLowerCase().includes(q));
  if(!rows.length){root.innerHTML='<div class="team-empty"><b>No accounts match</b><small>Try another search.</small></div>';return}
  root.innerHTML=`<table class="profile-users-table super-people-table"><thead><tr><th>Person</th><th>Role</th><th>Status</th><th>Access from</th><th>Last sign-in</th><th>Work (${days} days)</th><th>All time</th><th>Last active</th><th></th></tr></thead><tbody>${rows.map((u,i)=>{const mine=u.id===state.user?.id,off=u.active===false;return `<tr class="${off?"off":u.must_change_password?"pending":"active"}" style="--i:${Math.min(i,20)}"><td><div class="team-user">${teamAvatar(u)}<span><b>${esc(u.username||u.email)}${mine?'<em class="profile-you">You</em>':""}</b><small>${esc(u.name)}${u.email&&u.email!==u.username?` · ${esc(u.email)}`:""}</small></span></div></td><td>${roleCell(u,mine)}</td><td>${off?'<span class="profile-status off">Deactivated</span>':u.must_change_password?'<span class="profile-status pending">Must change password</span>':'<span class="profile-status">Active</span>'}</td><td>${accessCell(u)}</td><td>${signInCell(u)}</td><td class="super-work"><b>${u.points_period}</b> points · <b>${u.edits_period}</b> edits · <b>${u.deletes_period}</b> deleted<br><b>${u.qc_decisions_period}</b> QC decisions</td><td class="super-work"><b>${u.poles_completed_total}</b> poles completed<br><b>${u.points_total}</b> points · <b>${u.qc_decisions_total}</b> QC</td><td title="${esc(u.last_active||"")}">${esc(teamAgo(u.last_active))}</td><td>${mine?'<small class="muted">Your account</small>':`<button type="button" class="compact-btn${off?"":" danger-btn"}" data-super-active="${off?"true":"false"}" data-super-user="${esc(u.id)}" data-name="${esc(u.username||u.email)}">${off?"Reactivate":"Deactivate"}</button>`}</td></tr>`}).join("")}</tbody></table>`}

async function updateAccount(id,body,message){await api(`/api/users/${encodeURIComponent(id)}`,{method:"PUT",body:JSON.stringify(body)});toast(message,"success");await loadPeople()}

function fillActivityFilters(){const person=$("superActivityPerson"),current=person.value;person.innerHTML='<option value="">Everyone</option>'+(state.superAdmin.people||[]).map(u=>`<option value="${esc(u.email)}">${esc(u.username||u.email)} · ${esc(roleLabel(u.role))}</option>`).join("");person.value=current;const dataset=$("superActivityDataset"),chosen=dataset.value;dataset.innerHTML='<option value="">All datasets</option>'+(state.projects||[]).map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join("");dataset.value=chosen}

async function loadActivity(reset){const a=state.superAdmin.activity,root=$("superActivity"),more=$("superActivityMore");if(reset){a.items=[];a.next=null;root.innerHTML='<div class="team-skeleton-block short"></div>'}more.disabled=true;
  const params=new URLSearchParams({limit:"50"});for(const [key,id] of [["actor","superActivityPerson"],["group","superActivityGroup"],["project_id","superActivityDataset"]]){const v=$(id).value;if(v)params.set(key,v)}if(!reset&&a.next)params.set("before_id",a.next);
  try{const page=await api(`/api/super/activity?${params}`);a.items=reset?page.items:[...a.items,...page.items];a.next=page.next_before_id;a.loaded=true;renderActivity()}catch(e){root.innerHTML=`<div class="team-empty error"><b>Activity could not load</b><small>${esc(e.message)}</small></div>`}finally{more.disabled=false}}

function renderActivity(){const a=state.superAdmin.activity,root=$("superActivity");$("superActivityMore").classList.toggle("hidden",!a.next);if(!a.items.length){root.innerHTML='<div class="team-empty"><b>No activity</b><small>Nothing matches these filters.</small></div>';return}
  root.innerHTML=`<ol class="super-events">${a.items.map(e=>{const user={email:e.actor,username:e.actor_name,name:e.actor_name},where=[e.project_name||e.project_id,e.pole_internal_id!=null?`pole ID ${e.pole_internal_id}`:null].filter(Boolean).join(" · ");return `<li class="super-event"><span class="super-group g-${esc(e.group)}">${esc(GROUPS[e.group]||e.group)}</span>${teamAvatar(user,"sm")}<div><p><b>${esc(e.actor_name)}</b>${e.actor_role?` <span class="profile-role${/ADMIN/.test(String(e.actor_role).toUpperCase())?" admin":""}">${esc(roleLabel(e.actor_role))}</span>`:""} ${esc(e.label)}${e.summary?` <em>${esc(e.summary)}</em>`:""}</p><small>${where?`${esc(where)} · `:""}<time datetime="${esc(e.at||"")}" title="${esc(e.at?new Date(e.at).toLocaleString():"")}">${esc(teamAgo(e.at))}</time></small></div></li>`}).join("")}</ol>`}

export function init(){
  state.superAdmin={tab:"people",days:30,people:[],activity:{items:[],next:null,loaded:false}};
  $("superAdminBtn").onclick=()=>openSuperPage();
  $("superBackBtn").onclick=()=>applyWorkspace();
  $("superTeamBtn").onclick=()=>{state.team.scope="all";state.team.returnTo="super";$("teamBackBtn").textContent="Back to Super admin";openTeamPage()};
  document.querySelectorAll("[data-super-tab]").forEach(b=>b.onclick=()=>showTab(b.dataset.superTab));
  $("superPeopleSearch").oninput=renderPeople;
  $("superPeopleDays").onchange=event=>{state.superAdmin.days=Number(event.target.value);loadPeople()};
  for(const id of ["superActivityPerson","superActivityGroup","superActivityDataset"])$(id).onchange=()=>loadActivity(true);
  $("superActivityMore").onclick=()=>loadActivity(false);
  $("superPeople").addEventListener("click",async event=>{
    const access=event.target.closest("[data-super-remote]");
    if(access){const allow=access.dataset.remote==="true";access.disabled=true;try{await updateAccount(access.dataset.superRemote,{remote_access:allow},allow?`${access.dataset.name} can work from anywhere`:`${access.dataset.name} can now work only from the office networks`)}catch(e){access.disabled=false;toast(e.message,"error")}return}
    const active=event.target.closest("[data-super-active]");
    if(active){const on=active.dataset.superActive==="true",name=active.dataset.name;if(!on&&!confirm(`Deactivate ${name}? They are signed out everywhere and cannot sign in until reactivated. Their work is kept.`))return;active.disabled=true;try{await updateAccount(active.dataset.superUser,{active:on},on?`${name} can sign in again`:`${name} is deactivated and signed out`)}catch(e){active.disabled=false;toast(e.message,"error")}}
  });
  $("superPeople").addEventListener("change",async event=>{const select=event.target.closest("[data-super-role]");if(!select)return;const role=select.value,name=select.dataset.name;if(!confirm(`Change ${name} to ${roleLabel(role)}?`)){select.value=select.dataset.current;return}select.disabled=true;try{await updateAccount(select.dataset.superRole,{role},`${name} is now ${roleLabel(role)}`)}catch(e){select.value=select.dataset.current;select.disabled=false;toast(e.message,"error")}});
  $("superCreateForm").onsubmit=async event=>{event.preventDefault();const form=event.currentTarget,status=$("superCreateStatus"),button=$("superCreateBtn"),password=$("superCreatePassword").value;if(password!==$("superCreateConfirm").value){status.textContent="The temporary passwords don't match";return}if(password.length<12){status.textContent="Use at least 12 characters";return}status.textContent="Creating account…";button.disabled=true;
    try{const created=await api("/api/users",{method:"POST",body:JSON.stringify({username:$("superCreateUsername").value.trim(),name:$("superCreateName").value.trim(),email:$("superCreateEmail").value.trim(),role:$("superCreateRole").value,remote_access:$("superCreateAccess").value==="anywhere",password})});form.reset();status.textContent=`${created.username||created.email} created`;toast(`${roleLabel(created.role)} account created. The temporary password must be changed at first sign-in.`,"success",7000);await loadPeople()}catch(e){status.textContent=e.message;toast(e.message,"error")}finally{button.disabled=false}};
  $("superCreateRole").onchange=event=>{$("superCreateAccess").value=event.target.value==="USER"?"office":"anywhere"};
}
