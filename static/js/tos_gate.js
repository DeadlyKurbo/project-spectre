(function initTosGate(global) {
  const COOKIE_NAME = "spectre_tos_accepted";
  const COOKIE_VALUE = "1";
  const REQUIRED_QUERY_VALUE = "required";
  const ROOT_SELECTOR = "#shell-content";

  let pendingUrl = "";
  let modal;
  let statusMessage;

  const getCookieValue = (name) => {
    const prefix = `${name}=`;
    const values = document.cookie ? document.cookie.split(";") : [];
    for (const entry of values) {
      const trimmed = entry.trim();
      if (trimmed.startsWith(prefix)) {
        return decodeURIComponent(trimmed.slice(prefix.length));
      }
    }
    return "";
  };

  const hasConsent = () => getCookieValue(COOKIE_NAME) === COOKIE_VALUE;

  const parseDestination = (rawValue) => {
    if (!rawValue) return "";
    try {
      const target = new URL(rawValue, global.location.origin);
      if (target.origin !== global.location.origin) return "";
      return `${target.pathname}${target.search}${target.hash}`;
    } catch (_error) {
      return "";
    }
  };

  const setStatus = (message) => {
    if (statusMessage) {
      statusMessage.textContent = message || "";
    }
  };

  const openModal = (targetUrl) => {
    if (!modal) return;
    const parsedTarget = parseDestination(targetUrl);
    if (parsedTarget) {
      pendingUrl = parsedTarget;
    }
    modal.hidden = false;
    modal.classList.add("is-open");
    setStatus("");
  };

  const blockOrAllowNavigation = (urlLike) => {
    if (!modal) return false;
    if (hasConsent()) return false;
    openModal(urlLike);
    return true;
  };

  const navigateToPending = () => {
    const fallback = "/dashboard";
    const target = pendingUrl || fallback;
    pendingUrl = "";
    global.location.assign(target);
  };

  const acceptTerms = async () => {
    setStatus("Saving acknowledgement...");
    try {
      const response = await fetch("/tos/accept", {
        method: "POST",
        credentials: "same-origin",
      });
      if (!response.ok) {
        setStatus("Unable to record acceptance. Please try again.");
        return;
      }
      navigateToPending();
    } catch (_error) {
      setStatus("Network error while recording acceptance. Please retry.");
    }
  };

  const onDocumentClickCapture = (event) => {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;

    const link = event.target.closest("a[href]");
    if (!link) return;
    if (link.target && link.target !== "_self") return;
    if (link.hasAttribute("download")) return;
    if (link.dataset.tosAllow === "1") return;

    const root = document.querySelector(ROOT_SELECTOR);
    if (root && !root.contains(link)) return;

    const href = link.getAttribute("href") || "";
    if (!href || href.startsWith("#")) return;

    const targetUrl = new URL(href, global.location.href);
    if (targetUrl.origin !== global.location.origin) return;

    if (!blockOrAllowNavigation(targetUrl.href)) return;

    event.preventDefault();
    event.stopImmediatePropagation();
  };

  const boot = () => {
    modal = document.getElementById("tos-gate");
    if (!modal) return;

    statusMessage = document.getElementById("tos-status");

    const agreeButton = document.getElementById("tos-agree");
    const disagreeButton = document.getElementById("tos-disagree");
    const readButton = document.getElementById("tos-read");

    if (agreeButton) {
      agreeButton.addEventListener("click", () => {
        void acceptTerms();
      });
    }

    if (disagreeButton) {
      disagreeButton.addEventListener("click", () => {
        setStatus("You must agree to the Terms of Service to continue.");
      });
    }

    if (readButton) {
      readButton.addEventListener("click", () => {
        global.open(
          "https://docs.google.com/document/d/1yarvbcLyva-MeepQfC8jlYU2pweMFSeNiEIT9WDoLX0/edit?usp=sharing",
          "_blank",
          "noopener,noreferrer",
        );
      });
    }

    document.addEventListener("click", onDocumentClickCapture, true);

    const query = new URLSearchParams(global.location.search);
    if (query.get("tos") === REQUIRED_QUERY_VALUE && !hasConsent()) {
      openModal(query.get("next") || "");
    }
  };

  global.__spectreTosShouldBlockNavigation = blockOrAllowNavigation;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})(window);
