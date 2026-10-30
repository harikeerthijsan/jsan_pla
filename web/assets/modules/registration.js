// Self-registration on the sign-in card: an employee in the JSAN directory, without an account yet, enters their work
// email, then chooses a username and password. The account is created with the User role and linked to the directory
// entry (so the super admin directory shows the access at once); admins and super admins are still created by a super admin.
import { $, api } from "./core.js?v=20261029-replace-excel-format";

const SIGN_IN_PARTS = ["loginPasswordPane", "loginCodePane", "loginTabs"];
let hiddenBefore = {};

function showRegister(on) {
  if (on) {
    hiddenBefore = Object.fromEntries(SIGN_IN_PARTS.map(id => [id, $(id).classList.contains("hidden")]));
    for (const id of SIGN_IN_PARTS) $(id).classList.add("hidden");
  } else {
    for (const id of SIGN_IN_PARTS) $(id).classList.toggle("hidden", hiddenBefore[id] ?? id !== "loginPasswordPane");
  }
  $("loginRegisterPane").classList.toggle("hidden", !on);
  $("loginSignInHint").classList.toggle("hidden", on);
  $("loginError").textContent = "";  // a sign-in error doesn't carry over to the register form, or back
  showError();
  step(1);
  if (on) $("registerEmail").focus();
}

// The register form shows its messages in its own alert box, right under its buttons.
function showError(message = "") {
  const box = $("registerError");
  box.textContent = message;
  box.classList.toggle("hidden", !message);
}

function step(n) {
  $("registerStep1").classList.toggle("hidden", n !== 1);
  $("registerStep2").classList.toggle("hidden", n !== 2);
}

async function busy(button, work) {
  button.disabled = true;
  try { await work(); } catch (e) { showError(e.message); } finally { button.disabled = false; }
}

function checkEmail() {
  const email = $("registerEmail").value.trim();
  showError();
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) { showError("Enter your work email address."); $("registerEmail").focus(); return; }
  return busy($("registerCheckBtn"), async () => {
    const found = await api("/api/auth/register/check", { method: "POST", body: JSON.stringify({ email }) });
    $("registerWho").textContent = `${found.name}${found.jsan_id ? ` · ${found.jsan_id}` : ""} · ${found.email}`;
    $("registerUsername").value = found.suggested_username || "";
    $("registerPassword").value = ""; $("registerConfirm").value = "";
    step(2);
    $("registerPassword").focus();
  });
}

function createAccount() {
  const email = $("registerEmail").value.trim(), username = $("registerUsername").value.trim();
  const password = $("registerPassword").value, confirm = $("registerConfirm").value;
  showError();
  if (!/^[A-Za-z0-9._-]{3,80}$/.test(username)) { showError("Username: 3 or more letters, numbers, dot, dash or underscore."); $("registerUsername").focus(); return; }
  if (password.length < 12) { showError("Use at least 12 characters for the password."); $("registerPassword").focus(); return; }
  if (password !== confirm) { showError("The two passwords don't match."); $("registerConfirm").focus(); return; }
  return busy($("registerSubmitBtn"), async () => {
    const done = await api("/api/auth/register", { method: "POST", body: JSON.stringify({ email, username, password }) });
    showRegister(false);
    $("email").value = done.username; $("password").value = "";
    $("loginRegisterDone").textContent = `Welcome, ${done.name}. ${done.message}`;
    $("loginRegisterDone").classList.remove("hidden");
    $("password").focus();
  });
}

export function init() {
  if (!$("loginRegisterPane")) return;
  $("registerOpen").onclick = () => { $("loginRegisterDone").classList.add("hidden"); showRegister(true); };
  $("registerCancel").onclick = () => showRegister(false);
  $("registerBackBtn").onclick = () => { step(1); showError(); $("registerEmail").focus(); };
  $("registerCheckBtn").onclick = checkEmail;
  $("registerSubmitBtn").onclick = createAccount;
  $("registerEmail").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); checkEmail(); } });
  for (const id of ["registerUsername", "registerPassword", "registerConfirm"]) {
    $(id).addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); createAccount(); } });
  }
}
