"use strict";

(async () => {
  const status = document.getElementById("access-status");
  const token = window.location.hash.slice(1).trim();

  if (!token) {
    status.textContent = "Dieser Review-Link enthält keinen Zugriffsschlüssel.";
    return;
  }

  try {
    const response = await fetch("/review/access", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Accept": "application/json",
        "Content-Type": "text/plain;charset=UTF-8"
      },
      body: token
    });

    if (!response.ok) {
      status.textContent = "Der Review-Link ist ungültig oder wurde widerrufen.";
      return;
    }

    window.history.replaceState(null, "", "/");
    window.location.replace("/review");
  } catch (_error) {
    status.textContent = "Der Review-Zugriff konnte nicht geprüft werden.";
  }
})();
