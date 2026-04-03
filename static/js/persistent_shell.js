(function initPersistentShell(global) {
  const ROOT_SELECTOR = "#shell-content";
  const ENABLED_PATHS = new Set(["/", "/features", "/about", "/wasp"]);
  const HEAD_SELECTOR = 'link[rel="stylesheet"], style, meta[name="theme-color"]';

  const normalizePath = (value) => {
    try {
      const url = new URL(value, global.location.origin);
      return url.pathname;
    } catch (_error) {
      return "";
    }
  };

  const shouldHandle = (urlLike) => ENABLED_PATHS.has(normalizePath(urlLike));

  const markInitialHeadNodes = () => {
    document.head.querySelectorAll(HEAD_SELECTOR).forEach((node) => {
      node.setAttribute("data-shell-managed", "true");
    });
  };

  const syncHead = (nextDoc) => {
    document.head.querySelectorAll('[data-shell-managed="true"]').forEach((node) => node.remove());
    nextDoc.head.querySelectorAll(HEAD_SELECTOR).forEach((node) => {
      const clone = node.cloneNode(true);
      clone.setAttribute("data-shell-managed", "true");
      document.head.appendChild(clone);
    });
  };

  const executeScriptsSequentially = async (container) => {
    const scripts = Array.from(container.querySelectorAll("script"));
    for (const oldScript of scripts) {
      const script = document.createElement("script");
      for (const { name, value } of Array.from(oldScript.attributes)) {
        script.setAttribute(name, value);
      }

      const runPromise = new Promise((resolve) => {
        script.addEventListener("load", () => resolve(), { once: true });
        script.addEventListener("error", () => resolve(), { once: true });
      });

      if (oldScript.src) {
        script.src = oldScript.src;
      } else {
        script.textContent = oldScript.textContent || "";
      }

      oldScript.replaceWith(script);
      if (script.src) {
        await runPromise;
      }
    }
  };

  const swapTo = async (url, { pushState = true } = {}) => {
    const currentRoot = document.querySelector(ROOT_SELECTOR);
    if (!currentRoot) return;

    const response = await fetch(url, {
      credentials: "same-origin",
      headers: { "X-Shell-Navigation": "1" },
    });
    if (!response.ok) {
      global.location.href = url;
      return;
    }

    const html = await response.text();
    const parser = new DOMParser();
    const nextDoc = parser.parseFromString(html, "text/html");
    const nextRoot = nextDoc.querySelector(ROOT_SELECTOR);
    if (!nextRoot) {
      global.location.href = url;
      return;
    }

    syncHead(nextDoc);
    document.title = nextDoc.title || document.title;

    const importedRoot = document.importNode(nextRoot, true);
    currentRoot.replaceWith(importedRoot);
    await executeScriptsSequentially(importedRoot);

    if (pushState) {
      global.history.pushState({ shell: true }, "", url);
    }

    document.dispatchEvent(new CustomEvent("shell:navigated", { detail: { url: String(url) } }));
  };

  const onClick = (event) => {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;

    const link = event.target.closest("a[href]");
    if (!link) return;
    if (link.target && link.target !== "_self") return;
    if (link.hasAttribute("download")) return;
    if (link.getAttribute("rel") === "external") return;

    const href = link.getAttribute("href") || "";
    if (!href || href.startsWith("#")) return;

    const targetUrl = new URL(href, global.location.href);
    if (targetUrl.origin !== global.location.origin) return;
    if (!shouldHandle(targetUrl.href)) return;
    if (!shouldHandle(global.location.href)) return;

    event.preventDefault();
    void swapTo(targetUrl.href, { pushState: true });
  };

  const onPopState = () => {
    if (!shouldHandle(global.location.href)) return;
    void swapTo(global.location.href, { pushState: false });
  };

  const boot = () => {
    if (!shouldHandle(global.location.href)) return;
    if (!document.querySelector(ROOT_SELECTOR)) return;

    markInitialHeadNodes();
    document.addEventListener("click", onClick);
    global.addEventListener("popstate", onPopState);
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})(window);
