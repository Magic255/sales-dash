const loginPanel = document.querySelector("#login-panel");
const companyPanel = document.querySelector("#company-panel");
const loginForm = document.querySelector("#login-form");
const loginMessage = document.querySelector("#login-message");
const companyMessage = document.querySelector("#company-message");
const companySelect = document.querySelector("#company-select");
const workspaceReady = document.querySelector("#workspace-ready");
const auditPanel = document.querySelector("#audit-panel");
const auditRows = document.querySelector("#audit-rows");
const auditMessage = document.querySelector("#audit-message");
let csrfToken = "";
let signedInUserId = "";

async function refreshCsrfToken() {
  const response = await fetch("/api/auth/csrf", { credentials: "same-origin" });
  if (!response.ok) throw new Error("Could not start a secure session. Refresh the page.");
  const data = await response.json();
  csrfToken = data.csrf_token;
}

async function apiRequest(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers || {});
  if (method !== "GET" && method !== "HEAD" && method !== "OPTIONS") {
    if (!csrfToken) await refreshCsrfToken();
    headers.set("X-CSRFToken", csrfToken);
  }
  if (options.body) headers.set("Content-Type", "application/json");
  const response = await fetch(path, {
    ...options,
    method,
    headers,
    credentials: "same-origin",
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "Something went wrong. Please try again.");
  return data;
}

function showLogin(message = "") {
  loginPanel.hidden = false;
  companyPanel.hidden = true;
  loginMessage.textContent = message;
  workspaceReady.hidden = true;
  auditPanel.hidden = true;
  document.dispatchEvent(new CustomEvent("salesdash:signed-out"));
}

function showCompanies(data) {
  loginPanel.hidden = true;
  companyPanel.hidden = false;
  document.querySelector("#account-email").textContent = data.user.email;
  companySelect.replaceChildren(new Option("Select a company", ""));
  for (const company of data.companies) {
    const option = new Option(company.name + " · " + company.role, company.id);
    companySelect.add(option);
  }
  if (data.selected_company) {
    companySelect.value = data.selected_company.id;
    showSelectedCompany(data.selected_company);
  } else {
    workspaceReady.hidden = true;
    auditPanel.hidden = true;
  }
  companyMessage.textContent = data.companies.length
    ? ""
    : "Your account has no active company access yet. Please contact your administrator.";
  companySelect.disabled = data.companies.length === 0;
}

function showSelectedCompany(company) {
  workspaceReady.hidden = false;
  document.querySelector("#selected-company-name").textContent = company.name;
  document.querySelector("#selected-company-role").textContent =
    "Signed in with " + company.role + " access.";
  auditPanel.hidden = company.role !== "admin";
  auditRows.replaceChildren();
  if (company.role === "admin") loadAuditLogs();
  document.dispatchEvent(new CustomEvent("salesdash:company-selected", { detail: { ...company, userId: signedInUserId } }));
}

async function loadAuditLogs() {
  if (auditPanel.hidden) return;
  auditMessage.textContent = "Loading security activity…";
  try {
    const data = await apiRequest("/api/audit-logs?limit=100");
    auditRows.replaceChildren();
    if (!data.items.length) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 3;
      cell.textContent = "No security activity has been recorded yet.";
      row.append(cell);
      auditRows.append(row);
    }
    for (const item of data.items) {
      const row = document.createElement("tr");
      const when = document.createElement("td");
      const event = document.createElement("td");
      const actor = document.createElement("td");
      const date = new Date(item.occurred_at);
      when.textContent = Number.isNaN(date.getTime()) ? item.occurred_at : date.toLocaleString();
      event.textContent = item.event_type.replaceAll("_", " ");
      actor.textContent = item.actor_user_id ? item.actor_user_id : "System";
      row.append(when, event, actor);
      auditRows.append(row);
    }
    auditMessage.textContent = "Showing the latest " + data.items.length + " events.";
  } catch (error) {
    auditMessage.textContent = error.message;
  }
}

async function loadCurrentUser() {
  const data = await apiRequest("/api/auth/me");
  if (!data.authenticated) {
    showLogin();
    return;
  }
  signedInUserId = data.user.id;
  showCompanies(data);
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = loginForm.querySelector("button");
  button.disabled = true;
  loginMessage.textContent = "Signing in…";
  try {
    await refreshCsrfToken();
    await apiRequest("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        email: document.querySelector("#email").value,
        password: document.querySelector("#password").value,
      }),
    });
    // Login rotates the session; fetch a fresh CSRF token for the new session.
    csrfToken = "";
    await refreshCsrfToken();
    loginForm.reset();
    await loadCurrentUser();
  } catch (error) {
    loginMessage.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

companySelect.addEventListener("change", async () => {
  workspaceReady.hidden = true;
  auditPanel.hidden = true;
  if (!companySelect.value) {
    document.dispatchEvent(new CustomEvent("salesdash:signed-out"));
    return;
  }
  companyMessage.textContent = "Checking company access…";
  try {
    const data = await apiRequest("/api/auth/company", {
      method: "POST",
      body: JSON.stringify({ company_id: companySelect.value }),
    });
    companyMessage.textContent = "";
    showSelectedCompany(data.selected_company);
  } catch (error) {
    companyMessage.textContent = error.message;
    companySelect.value = "";
  }
});

document.querySelector("#logout-button").addEventListener("click", async () => {
  try {
    await apiRequest("/api/auth/logout", { method: "POST", body: "{}" });
    csrfToken = "";
    showLogin("You have been signed out.");
  } catch (error) {
    companyMessage.textContent = error.message;
  }
});

document.querySelector("#audit-refresh").addEventListener("click", loadAuditLogs);
loadCurrentUser().catch((error) => showLogin(error.message));

const passwordForm = document.querySelector("#password-form");
const passwordMessage = document.querySelector("#password-message");

passwordForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const currentPassword = document.querySelector("#current-password").value;
  const newPassword = document.querySelector("#new-password").value;
  const confirmPassword = document.querySelector("#confirm-password").value;
  const button = passwordForm.querySelector("button");

  if (newPassword !== confirmPassword) {
    passwordMessage.textContent = "The new passwords do not match.";
    return;
  }
  if (newPassword.length < 12) {
    passwordMessage.textContent = "Your new password must contain at least 12 characters.";
    return;
  }

  button.disabled = true;
  passwordMessage.textContent = "Updating your password…";
  try {
    await apiRequest("/api/auth/password", {
      method: "POST",
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    });
    passwordForm.reset();
    csrfToken = "";
    showLogin("Your password was changed. Please sign in again with your new password.");
  } catch (error) {
    passwordMessage.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
