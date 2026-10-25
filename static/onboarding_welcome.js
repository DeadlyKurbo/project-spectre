/**
 * First-time onboarding welcome overlay.
 * Shows once per visitor (cookie). Buttons are placeholders for future binding.
 */
(function () {
  const COOKIE_NAME = "spectre-onboarding-seen";
  const COOKIE_MAX_AGE_DAYS = 365;

  function getCookie(name) {
    const match = document.cookie
      .split(";")
      .map((s) => s.trim())
      .find((s) => s.startsWith(name + "="));
    if (!match) return null;
    const value = match.slice(name.length + 1);
    try {
      return decodeURIComponent(value);
    } catch (_) {
      return value;
    }
  }

  function setCookie(name, value, maxAgeDays) {
    const safe = encodeURIComponent(String(value));
    const maxAge = Math.max(0, Math.floor(maxAgeDays * 24 * 60 * 60));
    document.cookie = name + "=" + safe + "; path=/; max-age=" + maxAge + "; SameSite=Lax";
  }

  function isFirstVisit() {
    return !getCookie(COOKIE_NAME);
  }

  function markOnboardingSeen() {
    setCookie(COOKIE_NAME, "1", COOKIE_MAX_AGE_DAYS);
  }

  function hideOverlay() {
    const overlay = document.getElementById("spectre-onboarding-welcome");
    if (!overlay) return;
    overlay.setAttribute("aria-hidden", "true");
    overlay.addEventListener(
      "transitionend",
      function removeOnEnd(e) {
        if (e.target !== overlay) return;
        overlay.removeEventListener("transitionend", removeOnEnd);
        overlay.remove();
      },
      { once: true }
    );
  }

  function dismiss() {
    markOnboardingSeen();
    hideOverlay();
  }

  function navigateToModule(targetHref) {
    const normalizedTarget = String(targetHref || "").trim();
    if (!normalizedTarget) {
      dismiss();
      return;
    }

    markOnboardingSeen();

    const currentPath = window.location.pathname || "/";
    if (normalizedTarget === currentPath) {
      hideOverlay();
      return;
    }

    window.location.assign(normalizedTarget);
  }

  function init() {
    if (typeof document === "undefined" || !document.getElementById) return;

    const overlay = document.getElementById("spectre-onboarding-welcome");
    if (!overlay) return;

    if (!isFirstVisit()) {
      overlay.remove();
      return;
    }

    overlay.setAttribute("aria-hidden", "false");

    overlay.querySelectorAll(".js-onboarding-footer").forEach(function (link) {
      link.addEventListener("click", function (e) {
        e.preventDefault();
        dismiss();
      });
    });

    overlay.querySelectorAll(".module-card button[data-module]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const targetHref = btn.dataset.href;
        navigateToModule(targetHref);
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
