// Keeps a signed-in admin marked "Online" on the Contact page while any page of
// the site is open. Only served to admins (templates/_admin_presence.html);
// every request they make also counts, this covers time spent reading a page.
(function () {
  "use strict";

  if (window.__spectreAdminPresence) return;
  window.__spectreAdminPresence = true;

  const PING_INTERVAL_MS = 45000;
  let lastPing = 0;
  let stopped = false;

  async function ping() {
    if (stopped) return;
    lastPing = Date.now();
    try {
      const response = await fetch("/api/presence/ping", {
        method: "POST",
        credentials: "same-origin",
        keepalive: true,
        headers: { "X-Requested-With": "fetch" },
      });
      // Signed out or no longer an admin: nothing more to report.
      if (response.status === 401 || response.status === 403) stopped = true;
    } catch (_err) {
      // Offline for a moment; the next tick retries.
    }
  }

  window.setInterval(ping, PING_INTERVAL_MS);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && Date.now() - lastPing > PING_INTERVAL_MS / 3) ping();
  });
}());
