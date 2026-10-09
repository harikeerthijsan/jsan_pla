// Super admin · Directory: the HR employee list, with search/filters, and turning employees into PoleGrid accounts.
// Granting access creates the account on the server (temporary password shown once). Role, active and works-from
// changes on existing accounts use PUT /api/users/{id}, so the usual account safeguards apply.
import { $, api, esc, state, toast } from "./core.js?v=20261009-directory-422";
import { roleLabel } from "./profile.js?v=20261009-directory-422";

const PAGE = 100;
const ACCESS = { none: "No access yet", active: "Active", pending: "Must change password", inactive: "Deactivated" };
const ROLES = ["USER", "ADMIN", "SUPER_ADMIN"];
const dir = { employees: [], facets: {}, totals: {}, selected: new Set(), sort: { key: "name", dir: 1 }, limit: PAGE, loaded: false, grantFor: null, editFor: null, creds: [] };

const icon = {
  edit: '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><path fill="currentColor" d="M3 17.25V21h3.75L17.8 9.94l-3.75-3.75L3 17.25Zm17.7-10.2a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83Z"/></svg>',
  trash: '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><path fill="currentColor" d="M6 19a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7H6v12ZM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4Z"/></svg>',
  key: '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><path fill="currentColor" d="M12.65 10A6 6 0 1 0 7 18a6 6 0 0 0 5.65-4H17v4h4v-4h2v-4H12.65ZM7 14a2 2 0 1 1 0-4 2 2 0 0 1 0 4Z"/></svg>',
  power: '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><path fill="currentColor" d="M13 3h-2v10h2V3Zm4.83 2.17-1.42 1.42A6.92 6.92 0 0 1 19 12a7 7 0 1 1-11.42-5.42L6.17 5.17A8.93 8.93 0 0 0 3 12a9 9 0 0 0 18 0 8.93 8.93 0 0 0-3.17-6.83Z"/></svg>',
};

const initials = name => String(name || "?").split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0]).join("").toUpperCase();
const hue = text => [...String(text)].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
const fmtDate = iso => iso ? new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" }) : "—";
const ago = iso => { if (!iso) return "Never"; const s = (Date.now() - new Date(iso)) / 1000; if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min ago`; if (s < 86400) return `${Math.round(s / 3600)} h ago`; return `${Math.round(s / 86400)} d ago`; };
const roleOf = e => e.account?.role || "";
const isMe = e => e.account && e.account.id === state.user?.id;

export async function loadDirectory() {
  if (!dir.loaded) $("dirTable").innerHTML = '<div class="team-skeleton-block"></div>';
  try {
    const data = await api("/api/super/directory");
    Object.assign(dir, { employees: data.employees, facets: data.facets, totals: data.totals, loaded: true });
    const ids = new Set(data.employees.map(e => e.id));
    dir.selected = new Set([...dir.selected].filter(id => ids.has(id)));
    fillFacets();
    render();
  } catch (e) {
    $("dirTable").innerHTML = `<div class="team-empty error"><b>The directory could not load</b><small>${esc(e.message)}</small></div>`;
  }
}

function fillFacets() {
  const fill = (id, values, all) => {
    const select = $(id), current = select.value;
    select.innerHTML = `<option value="">${all}</option><option value="__none">Not set</option>` + values.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
    select.value = [...select.options].some(o => o.value === current) ? current : "";
  };
  fill("dirDept", dir.facets.department || [], "All departments");
  fill("dirDesig", dir.facets.designation || [], "All designations");
  fill("dirHrRole", dir.facets.source_role || [], "Any HR role");
  $("dirDeptList").innerHTML = (dir.facets.department || []).map(v => `<option value="${esc(v)}">`).join("");
  $("dirDesigList").innerHTML = (dir.facets.designation || []).map(v => `<option value="${esc(v)}">`).join("");
}

function matches(e) {
  const q = $("dirSearch").value.trim().toLowerCase(), access = $("dirAccess").value, role = $("dirRole").value;
  const facet = (id, value) => { const want = $(id).value; return !want || (want === "__none" ? !value : value === want); };
  if (q && !`${e.name} ${e.jsan_id || ""} ${e.employee_id || ""} ${e.email} ${e.department || ""} ${e.designation || ""} ${e.account?.username || ""}`.toLowerCase().includes(q)) return false;
  if (access && e.access !== access) return false;
  if (role && roleOf(e) !== role) return false;
  return facet("dirDept", e.department) && facet("dirDesig", e.designation) && facet("dirHrRole", e.source_role);
}

const SORTS = {
  name: e => e.name.toLowerCase(), jsan_id: e => (e.jsan_id || "~").toLowerCase(), department: e => `${e.department || "~"} ${e.designation || "~"}`.toLowerCase(),
  joined: e => e.date_of_joining || "9999", access: e => Object.keys(ACCESS).indexOf(e.access), role: e => ROLES.indexOf(roleOf(e)),
  last: e => e.account?.last_login_at || "",
};

function visible() {
  const { key, dir: d } = dir.sort, value = SORTS[key];
  return dir.employees.filter(matches).sort((a, b) => { const x = value(a), y = value(b); return (x < y ? -1 : x > y ? 1 : 0) * d || a.name.localeCompare(b.name); });
}

function kpis() {
  const t = dir.totals, cards = [["", "Employees", t.all], ["none", "No access yet", t.none], ["active", "Active", t.active], ["pending", "Must change password", t.pending], ["inactive", "Deactivated", t.inactive]];
  const current = $("dirAccess").value;
  $("dirKpis").innerHTML = cards.map(([key, label, n]) => `<button type="button" class="dir-kpi ${key || "all"}${current === key ? " on" : ""}" data-dir-kpi="${key}"><b>${n ?? 0}</b><span>${label}</span></button>`).join("");
}

function accessPill(e) {
  const extra = e.access === "none" && e.existing_account ? `<small class="dir-hint">Account exists: ${esc(e.existing_account.username || e.existing_account.email)}</small>` : "";
  return `<span class="dir-pill ${e.access}">${ACCESS[e.access]}</span>${extra}`;
}

function roleCell(e) {
  if (!e.account) return '<span class="muted">—</span>';
  if (isMe(e)) return `<span class="profile-role admin">${esc(roleLabel(e.account.role))}</span>`;
  return `<select class="dir-role" data-dir-role="${e.id}" aria-label="Role of ${esc(e.name)}">${ROLES.map(r => `<option value="${r}"${r === e.account.role ? " selected" : ""}>${esc(roleLabel(r))}</option>`).join("")}</select>`;
}

function worksFrom(e) {
  if (!e.account) return '<span class="muted">—</span>';
  if (e.account.role === "SUPER_ADMIN") return '<span class="profile-status">Anywhere</span>';
  return `<button type="button" class="net-access-btn${e.account.remote_access ? " anywhere" : ""}" data-dir-remote="${e.id}" title="${e.account.remote_access ? "Limit to office networks" : "Allow from anywhere"}">${e.account.remote_access ? "Anywhere" : "Office only"}</button>`;
}

function actions(e) {
  const btn = (attr, svg, title, cls = "") => `<button type="button" class="dir-icon${cls}" ${attr}="${e.id}" title="${title}" aria-label="${title} — ${esc(e.name)}">${svg}</button>`;
  const lead = !e.account
    ? `<button type="button" class="dir-grant" data-dir-grant="${e.id}">${e.existing_account ? "Link account" : "Grant access"}</button>`
    : isMe(e) ? '<small class="muted">Your account</small>'
      : `${btn("data-dir-reset", icon.key, "Reset temporary password")}${btn("data-dir-active", icon.power, e.account.active ? "Deactivate access" : "Reactivate access", e.account.active ? " warn" : " ok")}`;
  const lockDelete = e.account?.active;
  return `<div class="dir-actions">${lead}${btn("data-dir-edit", icon.edit, "Edit details")}${lockDelete ? `<button type="button" class="dir-icon" disabled title="Deactivate their access before removing them from the directory">${icon.trash}</button>` : btn("data-dir-delete", icon.trash, "Remove from directory", " danger")}</div>`;
}

function render() {
  kpis();
  const rows = visible(), shown = rows.slice(0, dir.limit), total = dir.employees.length;
  $("dirMeta").textContent = `${total} employees · ${dir.totals.active + dir.totals.pending} with access · ${dir.totals.none} without`;
  $("dirShowing").textContent = rows.length === total ? `Showing ${shown.length} of ${total}` : `${rows.length} of ${total} match · showing ${shown.length}`;
  $("dirMore").classList.toggle("hidden", shown.length >= rows.length);
  if (!total) { $("dirTable").innerHTML = '<div class="team-empty"><b>No employees yet</b><small>Use Import CSV to load the HR export, or Add employee.</small></div>'; updateBulk(); return; }
  if (!rows.length) { $("dirTable").innerHTML = '<div class="team-empty"><b>No employees match</b><small>Try another search or clear the filters.</small></div>'; updateBulk(); return; }
  const th = (key, label) => `<th${key ? ` data-dir-sort="${key}" class="sortable${dir.sort.key === key ? (dir.sort.dir > 0 ? " asc" : " desc") : ""}" aria-sort="${dir.sort.key === key ? (dir.sort.dir > 0 ? "ascending" : "descending") : "none"}"` : ""}>${label}</th>`;
  const allOn = shown.length && shown.every(e => dir.selected.has(e.id));
  $("dirTable").innerHTML = `<table class="profile-users-table dir-table"><thead><tr><th class="dir-check"><input type="checkbox" id="dirSelectAll" aria-label="Select all shown"${allOn ? " checked" : ""}></th>${th("name", "Employee")}${th("jsan_id", "JSAN ID · Emp ID")}${th("department", "Department · Designation")}${th("joined", "Joined · Exp.")}${th("access", "Access")}${th("role", "App role")}${th("", "Works from")}${th("last", "Last sign-in")}${th("", "")}</tr></thead><tbody>${shown.map((e, i) => `<tr class="dir-row ${e.access}${dir.selected.has(e.id) ? " selected" : ""}" style="--i:${Math.min(i, 24)}">
    <td class="dir-check"><input type="checkbox" data-dir-select="${e.id}" aria-label="Select ${esc(e.name)}"${dir.selected.has(e.id) ? " checked" : ""}></td>
    <td><div class="dir-person"><span class="dir-avatar" style="--h:${hue(e.email)}">${esc(initials(e.name))}</span><span><b>${esc(e.name)}</b><small>${esc(e.email)}</small></span></div></td>
    <td><b class="dir-mono">${esc(e.jsan_id || "—")}</b><small>${esc(e.employee_id || "No employee ID")}</small></td>
    <td>${e.department ? `<span class="dir-tag">${esc(e.department)}</span>` : '<span class="muted">—</span>'}<small>${esc(e.designation || "")}</small></td>
    <td>${esc(fmtDate(e.date_of_joining))}<small>${e.experience_years != null ? `${e.experience_years} yr${e.experience_years === 1 ? "" : "s"}` : ""}</small></td>
    <td>${accessPill(e)}</td><td>${roleCell(e)}</td><td>${worksFrom(e)}</td>
    <td title="${esc(e.account?.last_login_at || "")}">${e.account ? esc(ago(e.account.last_login_at)) : '<span class="muted">—</span>'}</td>
    <td>${actions(e)}</td></tr>`).join("")}</tbody></table>`;
  updateBulk();
}

function updateBulk() {
  const n = dir.selected.size;
  $("dirBulk").classList.toggle("hidden", !n);
  $("dirSelCount").textContent = `${n} selected`;
}

const byId = id => dir.employees.find(e => e.id === Number(id));
const remoteChoice = value => value === "anywhere" ? true : value === "office" ? false : null;

async function updateAccount(e, body, message) {
  try { await api(`/api/users/${encodeURIComponent(e.account.id)}`, { method: "PUT", body: JSON.stringify(body) }); toast(message, "success"); }
  catch (err) { toast(err.message, "error"); }
  await loadDirectory();
}

function openGrant(e) {
  dir.grantFor = e;
  $("dirGrantTitle").textContent = e.existing_account ? `Link ${e.name}'s account` : `Give ${e.name} access`;
  $("dirGrantWho").textContent = e.existing_account
    ? `${e.email} already has a PoleGrid account (${e.existing_account.username || e.existing_account.email}, ${roleLabel(e.existing_account.role)}). It will be linked as it is; no new password is created.`
    : `${e.email}${e.department || e.designation ? ` · ${[e.department, e.designation].filter(Boolean).join(" · ")}` : ""}`;
  document.querySelectorAll('input[name="dirGrantRole"]').forEach(r => { r.checked = r.value === "USER"; r.disabled = Boolean(e.existing_account); });
  $("dirGrantUsername").value = e.jsan_id || e.email.split("@")[0];
  $("dirGrantUsername").disabled = $("dirGrantAccess").disabled = Boolean(e.existing_account);
  $("dirGrantAccess").value = "";
  $("dirGrantError").textContent = "";
  $("dirGrantSubmit").textContent = e.existing_account ? "Link account" : "Grant access";
  $("dirGrantDialog").showModal();
}

async function submitGrant(event) {
  event.preventDefault();
  const e = dir.grantFor, button = $("dirGrantSubmit");
  const role = document.querySelector('input[name="dirGrantRole"]:checked')?.value || "USER";
  button.disabled = true; $("dirGrantError").textContent = "";
  try {
    const r = await api(`/api/super/directory/${e.id}/grant`, { method: "POST", body: JSON.stringify({ role, remote_access: remoteChoice($("dirGrantAccess").value), username: $("dirGrantUsername").value.trim() || null }) });
    $("dirGrantDialog").close();
    if (r.temporary_password) showCreds([{ name: e.name, email: e.email, username: r.employee.account.username, role: r.employee.account.role, temporary_password: r.temporary_password }], "Access granted");
    else toast(`${e.name} is linked to their existing account`, "success");
    await loadDirectory();
  } catch (err) { $("dirGrantError").textContent = err.message; }
  finally { button.disabled = false; }
}

function showCreds(list, title) {
  dir.creds = list.filter(c => c.temporary_password);
  $("dirCredsTitle").textContent = title;
  $("dirCredsBody").innerHTML = `<table class="dir-creds-table"><thead><tr><th>Name</th><th>Username</th><th>Role</th><th>Temporary password</th><th></th></tr></thead><tbody>${dir.creds.map((c, i) => `<tr><td><b>${esc(c.name)}</b><small>${esc(c.email)}</small></td><td class="dir-mono">${esc(c.username)}</td><td>${esc(roleLabel(c.role))}</td><td><code class="dir-secret">${esc(c.temporary_password)}</code></td><td><button type="button" class="dir-link" data-dir-copy="${i}">Copy</button></td></tr>`).join("")}</tbody></table>`;
  $("dirCredsDialog").showModal();
}

const credLine = c => `${c.name}\nUsername: ${c.username}\nEmail: ${c.email}\nTemporary password: ${c.temporary_password}\nSign in at: ${location.origin}`;
async function copyText(text, done) { try { await navigator.clipboard.writeText(text); toast(done, "success"); } catch { toast("Copy is blocked by the browser; select the text instead", "error"); } }
function credsCsv() {
  // Prefix cells that a spreadsheet would treat as formulas.
  const cell = v => { let s = String(v ?? ""); if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`; return `"${s.replace(/"/g, '""')}"`; };
  const lines = [["Name", "Email", "Username", "Role", "Temporary password"], ...dir.creds.map(c => [c.name, c.email, c.username, roleLabel(c.role), c.temporary_password])];
  const url = URL.createObjectURL(new Blob([lines.map(r => r.map(cell).join(",")).join("\r\n")], { type: "text/csv" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: `polegrid-access-${new Date().toISOString().slice(0, 10)}.csv` });
  document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function openEdit(e) {
  dir.editFor = e || null;
  $("dirEditTitle").textContent = e ? `Edit ${e.name}` : "Add employee";
  const v = e || {};
  $("dirEditName").value = v.name || ""; $("dirEditEmail").value = v.email || ""; $("dirEditJsan").value = v.jsan_id || ""; $("dirEditEmp").value = v.employee_id || "";
  $("dirEditDept").value = v.department || ""; $("dirEditDesig").value = v.designation || ""; $("dirEditDoj").value = v.date_of_joining || ""; $("dirEditExp").value = v.experience_years ?? "";
  $("dirEditEmail").disabled = Boolean(e?.account);
  $("dirEditNote").textContent = e?.account ? "The email is locked because it identifies their work in PoleGrid. A new name is also applied to their account." : "";
  $("dirEditError").textContent = "";
  $("dirEditSubmit").textContent = e ? "Save" : "Add employee";
  $("dirEditDialog").showModal();
  $("dirEditName").focus();
}

async function submitEdit(event) {
  event.preventDefault();
  const e = dir.editFor, button = $("dirEditSubmit"), exp = $("dirEditExp").value;
  const body = { name: $("dirEditName").value.trim(), email: $("dirEditEmail").value.trim(), jsan_id: $("dirEditJsan").value.trim() || null, employee_id: $("dirEditEmp").value.trim() || null,
    department: $("dirEditDept").value.trim() || null, designation: $("dirEditDesig").value.trim() || null, date_of_joining: $("dirEditDoj").value || null, experience_years: exp === "" ? null : Number(exp) };
  button.disabled = true; $("dirEditError").textContent = "";
  try {
    await api(e ? `/api/super/directory/${e.id}` : "/api/super/directory", { method: e ? "PUT" : "POST", body: JSON.stringify(body) });
    $("dirEditDialog").close();
    toast(e ? `${body.name} updated` : `${body.name} added`, "success");
    await loadDirectory();
  } catch (err) { $("dirEditError").textContent = err.message; }
  finally { button.disabled = false; }
}

async function importFile(file) {
  if (!file) return;
  if (!/\.csv$/i.test(file.name)) { toast("Choose a .csv file", "error"); return; }
  if (file.size > 2 * 1024 * 1024) { toast("The file is larger than 2 MB", "error"); return; }
  const button = $("dirImportBtn"); button.disabled = true; button.textContent = "Importing…";
  try {
    const r = await api("/api/super/directory/import", { method: "POST", body: JSON.stringify({ filename: file.name, csv: await file.text() }) });
    $("dirImportBody").innerHTML = `<div class="dir-import-stats"><span><b>${r.created}</b>added</span><span><b>${r.updated}</b>updated</span><span><b>${r.unchanged}</b>unchanged</span><span class="${r.skipped.length ? "warn" : ""}"><b>${r.skipped.length}</b>skipped</span></div>${r.skipped.length ? `<ul class="dir-skipped">${r.skipped.slice(0, 50).map(s => `<li>${s.row ? `Row ${s.row}` : "Row"}${s.name ? ` · ${esc(s.name)}` : ""}: ${esc(s.reason)}</li>`).join("")}</ul>` : ""}<p class="dir-note">Existing access is never changed by an import. Employees with access keep their email.</p>`;
    $("dirImportDialog").showModal();
    await loadDirectory();
  } catch (err) { toast(err.message, "error"); }
  finally { button.disabled = false; button.textContent = "Import CSV"; $("dirImportFile").value = ""; }
}

async function bulkGrant() {
  const ids = [...dir.selected].filter(id => !byId(id)?.account);
  if (!ids.length) { toast("Everyone selected already has access", "info"); return; }
  const role = $("dirBulkRole").value;
  if (!confirm(`Give ${ids.length} employee${ids.length === 1 ? "" : "s"} access as ${roleLabel(role)}? A temporary password is created for each.`)) return;
  const button = $("dirBulkGrant"); button.disabled = true; button.textContent = "Granting…";
  try {
    const r = await api("/api/super/directory/grant", { method: "POST", body: JSON.stringify({ ids, role, remote_access: remoteChoice($("dirBulkAccess").value) }) });
    const failed = r.results.filter(x => x.status === "error"), linked = r.results.filter(x => x.status === "linked");
    dir.selected.clear();
    if (r.results.some(x => x.temporary_password)) showCreds(r.results, `Access granted to ${r.results.filter(x => x.temporary_password).length}`);
    if (linked.length) toast(`${linked.length} linked to existing accounts`, "success");
    if (failed.length) toast(`${failed.length} could not be granted: ${failed[0].error}`, "error");
    await loadDirectory();
  } catch (err) { toast(err.message, "error"); }
  finally { button.disabled = false; button.textContent = "Grant access"; }
}

async function bulkActive(active) {
  const targets = [...dir.selected].map(byId).filter(e => e?.account && !isMe(e) && e.account.active !== active);
  if (!targets.length) { toast(active ? "Nobody selected is deactivated" : "Nobody selected has active access", "info"); return; }
  if (!confirm(`${active ? "Reactivate" : "Deactivate"} access for ${targets.length} employee${targets.length === 1 ? "" : "s"}?${active ? "" : " They are signed out straight away."}`)) return;
  let done = 0; const errors = [];
  for (const e of targets) {
    try { await api(`/api/users/${encodeURIComponent(e.account.id)}`, { method: "PUT", body: JSON.stringify({ active }) }); done++; }
    catch (err) { errors.push(`${e.name}: ${err.message}`); }
  }
  toast(`${done} ${active ? "reactivated" : "deactivated"}${errors.length ? ` · ${errors.length} refused` : ""}`, errors.length ? "error" : "success");
  if (errors.length) console.warn(errors.join("\n"));
  dir.selected.clear();
  await loadDirectory();
}

async function onTableClick(event) {
  const target = event.target.closest("button, input, th[data-dir-sort]");
  if (!target) return;
  if (target.matches("th[data-dir-sort]")) {
    const key = target.dataset.dirSort;
    dir.sort = { key, dir: dir.sort.key === key ? -dir.sort.dir : 1 };
    render(); return;
  }
  if (target.id === "dirSelectAll") {
    const shown = visible().slice(0, dir.limit);
    shown.forEach(e => target.checked ? dir.selected.add(e.id) : dir.selected.delete(e.id));
    render(); return;
  }
  if (target.dataset.dirSelect) {
    const id = Number(target.dataset.dirSelect);
    target.checked ? dir.selected.add(id) : dir.selected.delete(id);
    target.closest("tr").classList.toggle("selected", target.checked);
    updateBulk(); return;
  }
  const e = byId(target.dataset.dirGrant || target.dataset.dirEdit || target.dataset.dirDelete || target.dataset.dirReset || target.dataset.dirActive || target.dataset.dirRemote);
  if (!e) return;
  if (target.dataset.dirGrant) openGrant(e);
  else if (target.dataset.dirEdit) openEdit(e);
  else if (target.dataset.dirDelete) {
    if (!confirm(`Remove ${e.name} from the directory?${e.account ? " Their deactivated account is kept for their work history." : ""}`)) return;
    try { await api(`/api/super/directory/${e.id}`, { method: "DELETE" }); toast(`${e.name} removed`, "success"); dir.selected.delete(e.id); await loadDirectory(); }
    catch (err) { toast(err.message, "error"); }
  } else if (target.dataset.dirReset) {
    if (!confirm(`Reset ${e.name}'s password? They are signed out and must use the new temporary password.`)) return;
    try { const r = await api(`/api/super/directory/${e.id}/reset-password`, { method: "POST" }); showCreds([{ name: e.name, email: e.email, username: e.account.username, role: e.account.role, temporary_password: r.temporary_password }], "Password reset"); await loadDirectory(); }
    catch (err) { toast(err.message, "error"); }
  } else if (target.dataset.dirActive) {
    const active = !e.account.active;
    if (!confirm(`${active ? "Reactivate" : "Deactivate"} ${e.name}'s access?${active ? "" : " They are signed out straight away."}`)) return;
    await updateAccount(e, { active }, `${e.name} ${active ? "reactivated" : "deactivated"}`);
  } else if (target.dataset.dirRemote) {
    const remote = !e.account.remote_access;
    await updateAccount(e, { remote_access: remote }, `${e.name} can now work ${remote ? "from anywhere" : "from office networks only"}`);
  }
}

async function onRoleChange(event) {
  const select = event.target.closest("[data-dir-role]");
  if (!select) return;
  const e = byId(select.dataset.dirRole), role = select.value;
  if (!confirm(`Change ${e.name}'s role from ${roleLabel(e.account.role)} to ${roleLabel(role)}?`)) { select.value = e.account.role; return; }
  await updateAccount(e, { role }, `${e.name} is now ${roleLabel(role)}`);
}

export function init() {
  if (!$("superDirectoryView")) return;
  let typing = null;
  $("dirSearch").addEventListener("input", () => { clearTimeout(typing); typing = setTimeout(() => { dir.limit = PAGE; render(); }, 120); });
  for (const id of ["dirAccess", "dirRole", "dirDept", "dirDesig", "dirHrRole"]) $(id).addEventListener("change", () => { dir.limit = PAGE; render(); });
  $("dirClear").onclick = () => { $("dirSearch").value = ""; for (const id of ["dirAccess", "dirRole", "dirDept", "dirDesig", "dirHrRole"]) $(id).value = ""; dir.limit = PAGE; render(); };
  $("dirKpis").addEventListener("click", event => { const card = event.target.closest("[data-dir-kpi]"); if (!card) return; $("dirAccess").value = card.dataset.dirKpi; dir.limit = PAGE; render(); });
  $("dirMore").onclick = () => { dir.limit += PAGE; render(); };
  $("dirTable").addEventListener("click", onTableClick);
  $("dirTable").addEventListener("change", onRoleChange);
  $("dirAddBtn").onclick = () => openEdit(null);
  $("dirImportBtn").onclick = () => $("dirImportFile").click();
  $("dirImportFile").onchange = event => importFile(event.target.files?.[0]);
  $("dirBulkGrant").onclick = bulkGrant;
  $("dirBulkActivate").onclick = () => bulkActive(true);
  $("dirBulkDeactivate").onclick = () => bulkActive(false);
  $("dirBulkClear").onclick = () => { dir.selected.clear(); render(); };
  $("dirGrantForm").addEventListener("submit", submitGrant);
  $("dirEditForm").addEventListener("submit", submitEdit);
  $("dirCredsCopy").onclick = () => copyText(dir.creds.map(credLine).join("\n\n"), "Sign-in details copied");
  $("dirCredsCsv").onclick = credsCsv;
  $("dirCredsBody").addEventListener("click", event => { const b = event.target.closest("[data-dir-copy]"); if (b) copyText(credLine(dir.creds[Number(b.dataset.dirCopy)]), "Copied"); });
  document.querySelectorAll("#superDirectoryView [data-dir-close]").forEach(b => b.onclick = () => b.closest("dialog").close());
  // Temporary passwords are not kept once the dialog closes.
  $("dirCredsDialog").addEventListener("close", () => { dir.creds = []; $("dirCredsBody").innerHTML = ""; });
}
