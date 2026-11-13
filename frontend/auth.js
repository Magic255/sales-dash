const loginPanel = document.querySelector("#login-panel");
const companyPanel = document.querySelector("#company-panel");
const loginForm = document.querySelector("#login-form");
const loginMessage = document.querySelector("#login-message");
const companyMessage = document.querySelector("#company-message");
const companySelect = document.querySelector("#company-select");
const workspaceReady = document.querySelector("#workspace-ready");
let csrfToken = "";

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
}

async function loadCurrentUser() {
  const data = await apiRequest("/api/auth/me");
  if (!data.authenticated) {
    showLogin();
    return;
  }
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
  if (!companySelect.value) return;
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

loadCurrentUser().catch((error) => showLogin(error.message));
