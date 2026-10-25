// Site-wide Project ZETA ping: shows a toast for the newest unread direct
// message. Served to anyone with a ZETA identity on every page except ZETA
// itself (templates/_admin_presence.html). The server hands out each message
// once, so a burst of messages or several open tabs produce a single ping, and
// a message that arrived while the person was away shows on their next visit.
(function () {
  "use strict";

  if (window.__spectreZetaPing) return;
  window.__spectreZetaPing = true;

  const CHECK_INTERVAL_MS = 20000;
  const HIDE_AFTER_MS = 15000;
  let timer = null;
  let hideTimer = null;
  let stopped = false;
  let toast = null;

  function injectStyles() {
    if (document.getElementById("zeta-ping-styles")) return;
    const style = document.createElement("style");
    style.id = "zeta-ping-styles";
    style.setAttribute("data-shell-persist", "");
    style.textContent = `
      .zeta-ping {
        position: fixed; right: 16px; bottom: 16px; z-index: 2147483000;
        display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 4px 12px; align-items: start;
        width: min(360px, calc(100vw - 32px)); padding: 12px 12px 12px 14px;
        border: 1px solid var(--sp-border-accent, rgba(142, 167, 132, .45));
        border-left: 3px solid var(--sp-accent, #8ea784);
        background: var(--sp-panel, #0b1014); color: var(--sp-text, #c9d1c4);
        box-shadow: 0 14px 32px rgba(0, 0, 0, .55);
        font: 500 14px/1.4 "Rajdhani", system-ui, sans-serif;
        transform: translateY(12px); opacity: 0; transition: transform .2s ease, opacity .2s ease;
      }
      .zeta-ping.is-visible { transform: none; opacity: 1; }
      .zeta-ping__avatar {
        grid-row: span 3; display: grid; place-items: center; width: 36px; height: 36px;
        border: 1px solid var(--sp-border-accent, rgba(142, 167, 132, .45));
        background: var(--sp-accent-bg, rgba(142, 167, 132, .1)); color: var(--sp-accent-strong, #b6cfa9);
        font: 700 16px "Share Tech Mono", ui-monospace, monospace;
      }
      .zeta-ping__tag { color: var(--sp-label, #7d8a78); font: 11px "Share Tech Mono", ui-monospace, monospace; letter-spacing: .14em; text-transform: uppercase; }
      .zeta-ping__from { color: var(--sp-text-bright, #e8efe3); font-weight: 700; letter-spacing: .04em; overflow-wrap: anywhere; }
      .zeta-ping__preview { margin: 0; color: var(--sp-muted, #8a948a); overflow-wrap: anywhere; }
      .zeta-ping__open { grid-column: 2; justify-self: start; margin-top: 4px; color: var(--sp-accent-strong, #b6cfa9); font: 12px "Share Tech Mono", ui-monospace, monospace; letter-spacing: .1em; text-transform: uppercase; }
      .zeta-ping__close {
        grid-column: 3; grid-row: 1; width: 28px; height: 28px; padding: 0; border: 1px solid transparent;
        background: none; color: var(--sp-muted, #8a948a); font: 14px ui-monospace, monospace; cursor: pointer;
      }
      .zeta-ping__close:hover, .zeta-ping__close:focus-visible { border-color: var(--sp-border, #1f2a24); color: var(--sp-text-bright, #e8efe3); }
      @media (prefers-reduced-motion: reduce) { .zeta-ping { transition: none; } }
    `;
    document.head.appendChild(style);
  }

  function hide() {
    clearTimeout(hideTimer);
    if (!toast) return;
    const node = toast;
    toast = null;
    node.classList.remove("is-visible");
    setTimeout(() => node.remove(), 250);
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function show(ping) {
    injectStyles();
    // Only the latest message is ever on screen.
    if (toast) toast.remove();
    toast = el("aside", "zeta-ping");
    toast.setAttribute("role", "status");
    toast.setAttribute("aria-live", "polite");
    toast.setAttribute("data-shell-persist", "");

    const avatar = el("span", "zeta-ping__avatar", String(ping.initial || "?").slice(0, 2));
    avatar.setAttribute("aria-hidden", "true");
    const more = Number(ping.unread_total) > 1 ? ` · ${ping.unread_total} unread` : "";
    const close = el("button", "zeta-ping__close", "✕");
    close.type = "button";
    close.setAttribute("aria-label", "Dismiss");
    close.addEventListener("click", hide);
    const open = el("a", "zeta-ping__open", "Open in ZETA →");
    open.href = ping.url || "/zeta";

    toast.append(
      avatar,
      el("span", "zeta-ping__tag", `ZETA // Direct message${more}`),
      close,
      el("span", "zeta-ping__from", ping.from || "Operator"),
      el("p", "zeta-ping__preview", ping.preview || ""),
      open,
    );
    document.body.appendChild(toast);
    requestAnimationFrame(() => toast && toast.classList.add("is-visible"));
    clearTimeout(hideTimer);
    hideTimer = setTimeout(hide, HIDE_AFTER_MS);
  }

  async function check() {
    clearTimeout(timer);
    if (stopped || document.hidden) return;
    try {
      const response = await fetch("/api/zeta/ping", {
        method: "POST",
        credentials: "same-origin",
        headers: { Accept: "application/json", "X-Requested-With": "fetch" },
      });
      if (response.status === 401 || response.status === 403) {
        stopped = true;
        return;
      }
      if (response.ok) {
        const payload = await response.json();
        if (payload && payload.ping) show(payload.ping);
      }
    } catch (_err) {
      // Offline for a moment; the next tick retries.
    }
    if (!stopped) timer = setTimeout(check, CHECK_INTERVAL_MS);
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) check();
  });
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", check, { once: true });
  } else {
    check();
  }
})();
