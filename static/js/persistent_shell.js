(function initPersistentShell(global) {
  const ROOT_SELECTOR = "#shell-content";
  const ENABLED_PATHS = new Set(["/", "/features", "/about", "/wasp"]);
  const HEAD_SELECTOR = 'link[rel="stylesheet"], style, meta[name="theme-color"]';
  // Nodes that belong to something living outside the swapped content (the
  // W.A.S.P. player on <body>) carry data-shell-persist and are never removed.
  const PERSIST_SELECTOR = "[data-shell-persist]";
  const STYLESHEET_WAIT_MS = 2500;
  const shouldBlockNavigation = (urlLike) => {
    const blocker =
      typeof global.__spectreTosShouldBlockNavigation === "function"
        ? global.__spectreTosShouldBlockNavigation
        : null;
    if (!blocker) return false;
    return blocker(urlLike);
  };

  const parseUrl = (value) => {
    try {
      return new URL(value, global.location.href);
    } catch (_error) {
      return null;
    }
  };

  const normalizePath = (value) => parseUrl(value)?.pathname || "";
  const documentKey = (value) => {
    const url = parseUrl(value);
    return url ? `${url.pathname}${url.search}` : "";
  };

  const shouldHandle = (urlLike) => ENABLED_PATHS.has(normalizePath(urlLike));

  // The URL (without hash) whose content is currently rendered. Fragment-only
  // history changes (clicking "#overview") fire popstate too and must not
  // refetch the page.
  let renderedKey = documentKey(global.location.href);
  let navigationId = 0;
  let activeRequest = null;

  const headSignature = (node) => {
    const tag = node.tagName.toLowerCase();
    if (tag === "link") return `link:${node.href || node.getAttribute("href") || ""}`;
    if (tag === "meta") return `meta:${node.getAttribute("content") || ""}`;
    return `style:${node.textContent || ""}`;
  };

  const markInitialHeadNodes = () => {
    document.head.querySelectorAll(HEAD_SELECTOR).forEach((node) => {
      if (node.matches(PERSIST_SELECTOR)) return;
      node.setAttribute("data-shell-managed", "true");
    });
  };

  const waitForStylesheet = (link) =>
    new Promise((resolve) => {
      link.addEventListener("load", resolve, { once: true });
      link.addEventListener("error", resolve, { once: true });
    });

  // Bring the head in line with the next page without a flash of unstyled
  // content: stylesheets both pages share stay in place, new ones are added
  // and loaded before the content swap, and stale ones are removed afterwards.
  const prepareHead = async (nextDoc) => {
    const available = new Map();
    document.head.querySelectorAll(`[data-shell-managed="true"], ${PERSIST_SELECTOR}`).forEach((node) => {
      if (!node.matches(HEAD_SELECTOR)) return;
      const signature = headSignature(node);
      if (!available.has(signature)) available.set(signature, []);
      available.get(signature).push(node);
    });

    const kept = new Set();
    const added = [];
    const pending = [];
    let anchor = null;
    nextDoc.head.querySelectorAll(HEAD_SELECTOR).forEach((node) => {
      const candidate = document.importNode(node, true);
      const signature = headSignature(candidate);
      const reusable = (available.get(signature) || []).find((existing) => !kept.has(existing));
      if (reusable) {
        kept.add(reusable);
        anchor = reusable;
        return;
      }
      candidate.setAttribute("data-shell-managed", "true");
      if (anchor && anchor.parentNode === document.head) {
        anchor.after(candidate);
      } else {
        document.head.appendChild(candidate);
      }
      anchor = candidate;
      added.push(candidate);
      if (candidate.tagName.toLowerCase() === "link") pending.push(waitForStylesheet(candidate));
    });

    if (pending.length) {
      await Promise.race([
        Promise.all(pending),
        new Promise((resolve) => global.setTimeout(resolve, STYLESHEET_WAIT_MS)),
      ]);
    }

    return () => {
      document.head.querySelectorAll('[data-shell-managed="true"]').forEach((node) => {
        if (kept.has(node) || added.includes(node) || node.matches(PERSIST_SELECTOR)) return;
        node.remove();
      });
    };
  };

  // The Content-Security-Policy only runs inline scripts carrying this page's
  // nonce. Browsers hide the attribute, but the property keeps it.
  const pageNonce = (() => {
    const nonced = document.querySelector("script[nonce]");
    return nonced ? nonced.nonce || nonced.getAttribute("nonce") || "" : "";
  })();

  const responseNonce = (response) => {
    const policy = response.headers.get("content-security-policy") || "";
    const match = policy.match(/'nonce-([^']+)'/);
    return match ? match[1] : "";
  };

  // Inline scripts in the fetched page run only if the server issued them,
  // i.e. they carry the nonce from that response's own policy. Anything else
  // (script injected into the page) is dropped instead of being run under ours.
  const dropUntrustedScripts = (root, nonce) => {
    root.querySelectorAll("script:not([src])").forEach((node) => {
      const carried = node.nonce || node.getAttribute("nonce") || "";
      if (!nonce || carried !== nonce) node.remove();
    });
  };

  const executeScriptsSequentially = async (container) => {
    const scripts = Array.from(container.querySelectorAll("script"));
    for (const oldScript of scripts) {
      const script = document.createElement("script");
      for (const { name, value } of Array.from(oldScript.attributes)) {
        if (name !== "nonce") script.setAttribute(name, value);
      }
      script.nonce = pageNonce;

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

  const scrollAfterSwap = (url) => {
    const hash = parseUrl(url)?.hash || "";
    if (hash.length > 1) {
      let target = null;
      try {
        target = document.getElementById(decodeURIComponent(hash.slice(1)));
      } catch (_error) {
        target = null;
      }
      if (target) {
        target.scrollIntoView();
        return;
      }
    }
    global.scrollTo(0, 0);
  };

  const swapTo = async (url, { pushState = true } = {}) => {
    const currentRoot = document.querySelector(ROOT_SELECTOR);
    if (!currentRoot) return;

    // Only the most recent navigation may touch the page; a slower response
    // for an earlier click must never overwrite a newer one.
    navigationId += 1;
    const myId = navigationId;
    if (activeRequest) activeRequest.abort();
    const controller = typeof AbortController === "function" ? new AbortController() : null;
    activeRequest = controller;
    const isCurrent = () => myId === navigationId;

    let response;
    let html;
    try {
      response = await fetch(url, {
        credentials: "same-origin",
        headers: { "X-Shell-Navigation": "1" },
        signal: controller ? controller.signal : undefined,
      });
      if (!isCurrent()) return;
      if (!response.ok) {
        global.location.href = url;
        return;
      }
      html = await response.text();
    } catch (error) {
      if (!isCurrent() || error?.name === "AbortError") return;
      global.location.href = url;
      return;
    }
    if (!isCurrent()) return;

    // Follow server redirects (ToS gate, login): leave the shell if the final
    // page is not one of ours, otherwise record the URL that actually loaded.
    const requested = parseUrl(url);
    let finalUrl = String(url);
    if (response.redirected && response.url) {
      if (!shouldHandle(response.url)) {
        global.location.href = response.url;
        return;
      }
      const landed = parseUrl(response.url);
      if (landed && requested) landed.hash = requested.hash;
      finalUrl = landed ? landed.href : response.url;
    }

    const nextDoc = new DOMParser().parseFromString(html, "text/html");
    const nextRoot = nextDoc.querySelector(ROOT_SELECTOR);
    const nonce = responseNonce(response);
    // Without both nonces the page's scripts could not run here; load it normally.
    if (!nextRoot || !nonce || !pageNonce) {
      global.location.href = finalUrl;
      return;
    }
    dropUntrustedScripts(nextRoot, nonce);

    const removeStaleHead = await prepareHead(nextDoc);
    if (!isCurrent()) return;

    document.dispatchEvent(new CustomEvent("shell:before-swap", { detail: { url: finalUrl } }));
    document.title = nextDoc.title || document.title;

    const importedRoot = document.importNode(nextRoot, true);
    const liveRoot = document.querySelector(ROOT_SELECTOR) || currentRoot;
    liveRoot.replaceWith(importedRoot);
    removeStaleHead();

    if (pushState) {
      global.history.pushState({ shell: true }, "", finalUrl);
    } else if (finalUrl !== global.location.href) {
      global.history.replaceState({ shell: true }, "", finalUrl);
    }
    renderedKey = documentKey(finalUrl);
    scrollAfterSwap(finalUrl);

    await executeScriptsSequentially(importedRoot);
    if (!isCurrent()) return;

    document.dispatchEvent(new CustomEvent("shell:navigated", { detail: { url: finalUrl } }));
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
    if (shouldBlockNavigation(targetUrl.href)) {
      event.preventDefault();
      return;
    }
    if (!shouldHandle(targetUrl.href)) return;
    if (!shouldHandle(global.location.href)) return;
    // Same page, different fragment: let the browser scroll natively.
    if (documentKey(targetUrl.href) === renderedKey && targetUrl.hash) return;

    event.preventDefault();
    void swapTo(targetUrl.href, { pushState: true });
  };

  const onPopState = () => {
    if (!shouldHandle(global.location.href)) return;
    if (documentKey(global.location.href) === renderedKey) return;
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
