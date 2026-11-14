const loginPanel = document.querySelector("#login-panel");
const companyPanel = document.querySelector("#company-panel");
const loginForm = document.querySelector("#login-form");
const loginMessage = document.querySelector("#login-message");
const verificationPanel = document.querySelector("#verification-panel");
const verificationMessage = document.querySelector("#verification-message");
const passwordResetPanel = document.querySelector("#password-reset-panel");
const passwordResetForm = document.querySelector("#password-reset-form");
const passwordResetMessage = document.querySelector("#password-reset-message");
const mfaLoginPanel = document.querySelector("#mfa-login-panel");
const mfaLoginForm = document.querySelector("#mfa-login-form");
const mfaLoginMessage = document.querySelector("#mfa-login-message");
const mfaSetupForm = document.querySelector("#mfa-setup-form");
const mfaConfirmForm = document.querySelector("#mfa-confirm-form");
const mfaDisableForm = document.querySelector("#mfa-disable-form");
const mfaMessage = document.querySelector("#mfa-message");
const mfaSecret = document.querySelector("#mfa-secret");
const mfaRecoveryPanel = document.querySelector("#mfa-recovery-panel");
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
  mfaLoginPanel.hidden = true;
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
    showLogin(pendingInvitationToken
      ? "Sign in with the email address that received this company invitation."
      : "");
    return;
  }
  signedInUserId = data.user.id;
  showCompanies(data);
  loadMfaStatus().catch((error) => { mfaMessage.textContent = error.message; });
  if (pendingInvitationToken) {
    try {
      const accepted = await apiRequest("/api/team/invitations/accept", {
        method: "POST",
        body: JSON.stringify({ token: pendingInvitationToken }),
      });
      pendingInvitationToken = "";
      window.history.replaceState({}, document.title, window.location.pathname);
      const refreshed = await apiRequest("/api/auth/me");
      showCompanies(refreshed);
      companyMessage.textContent = accepted.message;
    } catch (error) {
      companyMessage.textContent = error.message;
    }
  }
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = loginForm.querySelector("button");
  button.disabled = true;
  loginMessage.textContent = "Signing in…";
  try {
    await refreshCsrfToken();
    const loginResult = await apiRequest("/api/auth/login", {
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
    if (loginResult.mfa_required) {
      loginPanel.hidden = true;
      mfaLoginPanel.hidden = false;
      document.querySelector("#mfa-login-code").focus();
      mfaLoginMessage.textContent = "Enter your authenticator code to finish signing in.";
      return;
    }
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
const pendingVerificationToken = new URLSearchParams(window.location.hash.slice(1)).get("verify_email");
const pendingPasswordResetToken = new URLSearchParams(window.location.hash.slice(1)).get("reset_password");
let pendingInvitationToken = new URLSearchParams(window.location.hash.slice(1)).get("accept_invitation");
if (pendingVerificationToken) {
  loginPanel.hidden = true;
  companyPanel.hidden = true;
  verificationPanel.hidden = false;
} else if (pendingPasswordResetToken) {
  loginPanel.hidden = true;
  companyPanel.hidden = true;
  passwordResetPanel.hidden = false;
} else {
  loadCurrentUser().catch((error) => showLogin(error.message));
}

async function loadMfaStatus() {
  const data = await apiRequest("/api/auth/mfa/status");
  mfaSetupForm.hidden = data.enabled;
  mfaDisableForm.hidden = !data.enabled;
  if (data.enabled) {
    mfaConfirmForm.hidden = true;
    mfaSecret.textContent = "Authenticator MFA is enabled for this account.";
  }
}

document.querySelector("#mfa-back-to-login").addEventListener("click", () => showLogin());

mfaLoginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = mfaLoginForm.querySelector("button");
  button.disabled = true;
  mfaLoginMessage.textContent = "Checking your code…";
  try {
    await apiRequest("/api/auth/mfa/challenge", {
      method: "POST",
      body: JSON.stringify({ code: document.querySelector("#mfa-login-code").value.trim() }),
    });
    csrfToken = "";
    await refreshCsrfToken();
    mfaLoginForm.reset();
    mfaLoginPanel.hidden = true;
    await loadCurrentUser();
  } catch (error) {
    mfaLoginMessage.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

mfaSetupForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = mfaSetupForm.querySelector("button");
  button.disabled = true;
  mfaMessage.textContent = "Preparing your authenticator setup…";
  try {
    const data = await apiRequest("/api/auth/mfa/setup", {
      method: "POST",
      body: JSON.stringify({ current_password: document.querySelector("#mfa-setup-password").value }),
    });
    mfaSecret.textContent = "In your authenticator app, add SALES DASH using this setup key: " + data.secret;
    mfaConfirmForm.hidden = false;
    document.querySelector("#mfa-confirm-code").focus();
    mfaSetupForm.reset();
    mfaMessage.textContent = "Enter the code shown by your authenticator app to finish setup.";
  } catch (error) {
    mfaMessage.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

mfaConfirmForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = mfaConfirmForm.querySelector("button");
  button.disabled = true;
  mfaMessage.textContent = "Confirming authenticator…";
  try {
    const data = await apiRequest("/api/auth/mfa/confirm", {
      method: "POST",
      body: JSON.stringify({ code: document.querySelector("#mfa-confirm-code").value.trim() }),
    });
    document.querySelector("#mfa-recovery-codes").textContent = data.recovery_codes.join("\n");
    mfaRecoveryPanel.hidden = false;
    mfaConfirmForm.hidden = true;
    mfaSetupForm.hidden = true;
    mfaMessage.textContent = data.message;
    await loadMfaStatus();
  } catch (error) {
    mfaMessage.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

mfaDisableForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = mfaDisableForm.querySelector("button");
  button.disabled = true;
  mfaMessage.textContent = "Disabling MFA…";
  try {
    const data = await apiRequest("/api/auth/mfa/disable", {
      method: "POST",
      body: JSON.stringify({
        current_password: document.querySelector("#mfa-disable-password").value,
        code: document.querySelector("#mfa-disable-code").value.trim(),
      }),
    });
    mfaDisableForm.reset();
    csrfToken = "";
    showLogin(data.message);
  } catch (error) {
    mfaMessage.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

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


document.querySelector("#resend-verification-button").addEventListener("click", async () => {
  const email = document.querySelector("#email").value.trim();
  if (!email) {
    loginMessage.textContent = "Enter your email address first.";
    return;
  }
  const button = document.querySelector("#resend-verification-button");
  button.disabled = true;
  loginMessage.textContent = "Requesting a verification email…";
  try {
    const data = await apiRequest("/api/auth/verification/resend", {
      method: "POST",
      body: JSON.stringify({ email }),
    });
    loginMessage.textContent = data.message;
  } catch (error) {
    loginMessage.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

document.querySelector("#confirm-verification-button").addEventListener("click", async () => {
  const button = document.querySelector("#confirm-verification-button");
  const token = pendingVerificationToken;
  if (!token) {
    verificationMessage.textContent = "This verification link is invalid or has expired.";
    return;
  }
  button.disabled = true;
  verificationMessage.textContent = "Verifying your email…";
  try {
    const data = await apiRequest("/api/auth/verification/confirm", {
      method: "POST",
      body: JSON.stringify({ token }),
    });
    window.history.replaceState({}, document.title, window.location.pathname);
    verificationPanel.hidden = true;
    showLogin(data.message);
  } catch (error) {
    verificationMessage.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});


document.querySelector("#forgot-password-button").addEventListener("click", async () => {
  const email = document.querySelector("#email").value.trim();
  if (!email) {
    loginMessage.textContent = "Enter your email address first.";
    return;
  }
  const button = document.querySelector("#forgot-password-button");
  button.disabled = true;
  loginMessage.textContent = "Requesting a password reset email…";
  try {
    const data = await apiRequest("/api/auth/password/reset/request", {
      method: "POST",
      body: JSON.stringify({ email }),
    });
    loginMessage.textContent = data.message;
  } catch (error) {
    loginMessage.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

passwordResetForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const password = document.querySelector("#reset-new-password").value;
  const confirmation = document.querySelector("#reset-confirm-password").value;
  const button = passwordResetForm.querySelector("button");
  if (password !== confirmation) {
    passwordResetMessage.textContent = "The new passwords do not match.";
    return;
  }
  if (password.length < 12) {
    passwordResetMessage.textContent = "Your password must contain at least 12 characters.";
    return;
  }
  if (!pendingPasswordResetToken) {
    passwordResetMessage.textContent = "This reset link is invalid or has expired.";
    return;
  }
  button.disabled = true;
  passwordResetMessage.textContent = "Resetting your password…";
  try {
    const data = await apiRequest("/api/auth/password/reset/confirm", {
      method: "POST",
      body: JSON.stringify({ token: pendingPasswordResetToken, new_password: password }),
    });
    window.history.replaceState({}, document.title, window.location.pathname);
    passwordResetForm.reset();
    passwordResetPanel.hidden = true;
    showLogin(data.message);
  } catch (error) {
    passwordResetMessage.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
