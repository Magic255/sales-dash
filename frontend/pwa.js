const installButton = document.querySelector("#install-app");
const appStatus = document.querySelector("#app-status");
let installPrompt = null;

if ("serviceWorker" in navigator) {
  window.addEventListener("load", async () => {
    try {
      await navigator.serviceWorker.register("/service-worker.js", { scope: "/" });
      appStatus.textContent =
        "App shell available offline. Sign-in and company data still need an internet connection.";
    } catch (_error) {
      appStatus.textContent = "Offline support could not start on this connection.";
    }
  });
}

window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  installPrompt = event;
  installButton.hidden = false;
});

installButton.addEventListener("click", async () => {
  if (!installPrompt) return;
  installButton.disabled = true;
  try {
    await installPrompt.prompt();
    await installPrompt.userChoice;
  } finally {
    installPrompt = null;
    installButton.hidden = true;
    installButton.disabled = false;
  }
});

window.addEventListener("appinstalled", () => {
  installButton.hidden = true;
  appStatus.textContent = "SALES DASH has been installed on this device.";
});
