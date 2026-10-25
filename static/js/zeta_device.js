// Project ZETA ban enforcement, loaded on the ZETA page only.
//
// Device marker: a random ID kept in a cookie, localStorage and IndexedDB.
// Clearing one of them is not enough; whichever survives restores the rest.
// Fingerprint: a SHA-256 of stable browser and hardware traits (canvas and
// WebGL rendering, screen, fonts, timezone, languages). Skipped on iPhone and
// iPad, where every device of a model renders identically and one ban would
// catch strangers.
//
// Both travel to the server as cookies, so every ZETA request carries them;
// the server only stores keyed hashes of them (config_app._zeta_request_traces).
(function () {
  "use strict";

  if (window.__spectreZetaDevice) return;

  const DEVICE_COOKIE = "zeta_device";
  const FINGERPRINT_COOKIE = "zeta_fp";
  const STORAGE_KEY = "spectre.zeta.device";
  const DB_NAME = "spectre-zeta";
  const DB_STORE = "kv";
  const MAX_AGE = 60 * 60 * 24 * 400;  // the most browsers allow
  const DEVICE_RE = /^[0-9a-f]{32}$/;

  function readCookie(name) {
    const match = document.cookie.split("; ").find((part) => part.startsWith(`${name}=`));
    return match ? decodeURIComponent(match.slice(name.length + 1)) : "";
  }

  function writeCookie(name, value) {
    const secure = location.protocol === "https:" ? "; Secure" : "";
    document.cookie = value
      ? `${name}=${encodeURIComponent(value)}; Max-Age=${MAX_AGE}; Path=/; SameSite=Lax${secure}`
      : `${name}=; Max-Age=0; Path=/; SameSite=Lax${secure}`;
  }

  const local = {
    get() { try { return localStorage.getItem(STORAGE_KEY) || ""; } catch (_err) { return ""; } },
    set(value) { try { localStorage.setItem(STORAGE_KEY, value); } catch (_err) { /* blocked */ } },
  };

  function idb(mode, work) {
    return new Promise((resolve) => {
      let request;
      try {
        request = indexedDB.open(DB_NAME, 1);
      } catch (_err) {
        resolve("");
        return;
      }
      request.onupgradeneeded = () => request.result.createObjectStore(DB_STORE);
      request.onerror = () => resolve("");
      request.onsuccess = () => {
        try {
          const tx = request.result.transaction(DB_STORE, mode);
          const result = work(tx.objectStore(DB_STORE));
          tx.oncomplete = () => resolve(result && "result" in result ? result.result || "" : "");
          tx.onerror = () => resolve("");
        } catch (_err) {
          resolve("");
        }
      };
    });
  }

  function randomId() {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  }

  async function sha256(text) {
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
    return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
  }

  function isAppleMobile() {
    const ua = navigator.userAgent || "";
    // iPadOS reports itself as a Mac; touch support gives it away.
    return /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
  }

  function canvasTrait() {
    try {
      const canvas = document.createElement("canvas");
      canvas.width = 280;
      canvas.height = 60;
      const ctx = canvas.getContext("2d");
      if (!ctx) return "";
      ctx.textBaseline = "alphabetic";
      ctx.fillStyle = "#f60";
      ctx.fillRect(100, 1, 62, 20);
      ctx.fillStyle = "#069";
      ctx.font = "15px 'Arial'";
      ctx.fillText("ZETA ops net \u{1F6F0} 0.1", 4, 17);
      ctx.fillStyle = "rgba(102, 204, 0, 0.7)";
      ctx.font = "18px 'Times New Roman'";
      ctx.fillText("ZETA ops net \u{1F6F0} 0.1", 6, 42);
      ctx.globalCompositeOperation = "multiply";
      ctx.fillStyle = "rgb(255,0,255)";
      ctx.beginPath();
      ctx.arc(220, 30, 20, 0, Math.PI * 2);
      ctx.fill();
      return canvas.toDataURL();
    } catch (_err) {
      return "";
    }
  }

  function webglTrait() {
    try {
      const gl = document.createElement("canvas").getContext("webgl");
      if (!gl) return "";
      const info = gl.getExtension("WEBGL_debug_renderer_info");
      const vendor = info ? gl.getParameter(info.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR);
      const renderer = info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
      return [vendor, renderer, gl.getParameter(gl.MAX_TEXTURE_SIZE), (gl.getSupportedExtensions() || []).join(",")].join("|");
    } catch (_err) {
      return "";
    }
  }

  function fontTrait() {
    const fonts = [
      "Arial Black", "Bahnschrift", "Calibri", "Cambria", "Candara", "Comic Sans MS", "Consolas", "Constantia",
      "Corbel", "Franklin Gothic Medium", "Gabriola", "Garamond", "Georgia", "Helvetica Neue", "Impact",
      "Lucida Console", "Menlo", "Monaco", "Noto Sans", "Palatino Linotype", "Segoe UI", "Tahoma",
      "Trebuchet MS", "Ubuntu", "Verdana", "DejaVu Sans", "Liberation Sans", "Cantarell", "Roboto", "SF Pro Text",
    ];
    try {
      const ctx = document.createElement("canvas").getContext("2d");
      if (!ctx) return "";
      const sample = "mmmmmmmmlli1WQ@#";
      const width = (font) => { ctx.font = `48px ${font}`; return ctx.measureText(sample).width; };
      const base = ["monospace", "serif", "sans-serif"].map(width);
      return fonts
        .filter((font) => ["monospace", "serif", "sans-serif"].some((fallback, i) => width(`'${font}', ${fallback}`) !== base[i]))
        .join(",");
    } catch (_err) {
      return "";
    }
  }

  async function fingerprint() {
    if (isAppleMobile() || !(window.crypto && crypto.subtle)) return "";
    const traits = [
      navigator.platform,
      (navigator.languages || [navigator.language]).join(","),
      Intl.DateTimeFormat().resolvedOptions().timeZone,
      [screen.width, screen.height, screen.colorDepth, window.devicePixelRatio].join("x"),
      navigator.hardwareConcurrency,
      navigator.deviceMemory,
      navigator.maxTouchPoints,
      canvasTrait(),
      webglTrait(),
      fontTrait(),
    ];
    return sha256(traits.join("\n"));
  }

  async function prepare() {
    // A cookie or localStorage value is available at once, so the marker is in
    // place before anyone can submit the join form; IndexedDB catches up.
    let device = [readCookie(DEVICE_COOKIE), local.get()].find((value) => DEVICE_RE.test(value)) || "";
    const stored = await idb("readonly", (store) => store.get("device"));
    if (DEVICE_RE.test(stored)) device = stored;  // the hardest one to clear wins
    if (!device) device = randomId();
    writeCookie(DEVICE_COOKIE, device);
    local.set(device);
    await idb("readwrite", (store) => store.put(device, "device"));

    try {
      writeCookie(FINGERPRINT_COOKIE, await fingerprint());
    } catch (_err) {
      writeCookie(FINGERPRINT_COOKIE, "");
    }
  }

  const ready = prepare().catch(() => undefined);
  window.__spectreZetaDevice = ready;

  // Joining waits (briefly) for the marker and fingerprint to be in place.
  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || form.getAttribute("action") !== "/zeta/join" || form.dataset.ready) return;
    event.preventDefault();
    const timeout = new Promise((resolve) => setTimeout(resolve, 1500));
    Promise.race([ready, timeout]).then(() => {
      form.dataset.ready = "1";
      form.submit();
    });
  });
})();
