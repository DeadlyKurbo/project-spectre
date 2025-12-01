(() => {
  const STORAGE_KEY = "spectre-onboarding-complete";
  if (typeof window === "undefined" || typeof document === "undefined") {
    return;
  }

  const ready = (callback) => {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", callback, { once: true });
    } else {
      callback();
    }
  };

  const fetchDefinitionImages = async () => {
    try {
      const res = await fetch("/branding/definitions/manifest", {
        headers: { Accept: "application/json" },
      });
      if (!res.ok) return {};
      const data = await res.json();
      return typeof data === "object" && data !== null ? data : {};
    } catch (err) {
      console.warn("Definition image lookup failed", err);
      return {};
    }
  };

  const buildOverlay = async () => {
    if (sessionStorage.getItem(STORAGE_KEY)) {
      return;
    }

    const definitions = await fetchDefinitionImages();
    const hqImage = (definitions?.hq && definitions.hq.url) || null;

    const style = document.createElement("style");
    style.id = "spectre-onboarding-style";
    style.textContent = `
      @keyframes sweepLines { from { background-position: 0 0; } to { background-position: 0 140%; } }
      @keyframes badgePulse { 0% { box-shadow: 0 0 0 0 rgba(108, 194, 74, .5); } 70% { box-shadow: 0 0 0 14px rgba(108, 194, 74, 0); } 100% { box-shadow: 0 0 0 0 rgba(108, 194, 74, 0); } }
      .spectre-onboarding-overlay {
        position: fixed;
        inset: 0;
        z-index: 9999;
        display: grid;
        place-items: center;
        background: radial-gradient(1200px 820px at 12% -10%, rgba(31, 41, 55, .88), rgba(5, 8, 13, .94)),
                    linear-gradient(135deg, rgba(20, 28, 38, .96), rgba(7, 12, 18, .98));
        color: #e8f0ff;
        font-family: "Inter", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Ubuntu, sans-serif;
        padding: 24px;
      }
      .spectre-onboarding-card {
        width: min(720px, 100%);
        border: 1px solid rgba(255,255,255,.18);
        border-radius: 18px;
        background: rgba(6, 10, 16, .85);
        box-shadow: 0 20px 60px rgba(0,0,0,.45);
        overflow: hidden;
        position: relative;
        isolation: isolate;
      }
      .spectre-onboarding-card::before {
        content: "";
        position: absolute;
        inset: 0;
        background-image: linear-gradient(180deg, rgba(83, 255, 157, .08), rgba(83, 255, 157, 0));
        opacity: .9;
        pointer-events: none;
      }
      .spectre-onboarding-card::after {
        content: "";
        position: absolute;
        inset: 0;
        background-image:
          linear-gradient(90deg, rgba(255,255,255,.05) 1px, transparent 1px),
          linear-gradient(rgba(255,255,255,.05) 1px, transparent 1px);
        background-size: 30px 30px, 30px 30px;
        background-position: 0 0, 0 0;
        mix-blend-mode: lighten;
        opacity: .08;
        pointer-events: none;
        animation: sweepLines 26s linear infinite;
      }
      .spectre-onboarding-inner {
        position: relative;
        padding: 32px 32px 28px;
        display: grid;
        gap: 18px;
        z-index: 1;
      }
      .spectre-onboarding-headline {
        display: flex;
        align-items: center;
        gap: 16px;
        flex-wrap: wrap;
      }
      .spectre-onboarding-badge {
        display: grid;
        place-items: center;
        width: 60px;
        height: 60px;
        border-radius: 14px;
        background: linear-gradient(135deg, rgba(88, 175, 86, .9), rgba(36, 88, 43, .9));
        color: #071008;
        font-weight: 800;
        letter-spacing: 1px;
        border: 1px solid rgba(133, 255, 169, .4);
        text-transform: uppercase;
        box-shadow: 0 0 0 1px rgba(83, 255, 157, .2);
        animation: badgePulse 2.8s ease-out infinite;
      }
      .spectre-onboarding-title {
        display: grid;
        gap: 6px;
      }
      .spectre-onboarding-title h1 {
        margin: 0;
        font-size: clamp(24px, 4vw, 32px);
        letter-spacing: .8px;
        text-transform: uppercase;
      }
      .spectre-onboarding-title .subline {
        color: #8ba6b9;
        font-size: 14px;
        letter-spacing: .4px;
      }
      .spectre-onboarding-body {
        display: grid;
        gap: 14px;
        color: #d8e3f5;
        line-height: 1.6;
      }
      .spectre-onboarding-body strong { color: #a5f3c7; }
      .spectre-onboarding-actions {
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        margin-top: 6px;
      }
      .spectre-onboarding-actions .btn {
        appearance: none;
        border: 1px solid rgba(133, 255, 169, .6);
        background: linear-gradient(135deg, rgba(86, 149, 73, .95), rgba(24, 48, 24, .95));
        color: #e8f4ec;
        border-radius: 12px;
        padding: 12px 18px;
        font-weight: 700;
        letter-spacing: .3px;
        cursor: pointer;
        transition: transform .1s ease, box-shadow .2s ease, filter .2s ease;
      }
      .spectre-onboarding-actions .btn:hover {
        transform: translateY(-1px);
        box-shadow: 0 10px 30px rgba(76, 175, 80, .28);
      }
      .spectre-onboarding-actions .btn.secondary {
        background: linear-gradient(135deg, rgba(42, 52, 66, .95), rgba(13, 18, 27, .95));
        border-color: rgba(255,255,255,.2);
        color: #d8e3f5;
      }
    `;

    const overlay = document.createElement("div");
    overlay.className = "spectre-onboarding-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-label", "SPECTRE onboarding");

    const card = document.createElement("div");
    card.className = "spectre-onboarding-card";

    const inner = document.createElement("div");
    inner.className = "spectre-onboarding-inner";

    const headline = document.createElement("div");
    headline.className = "spectre-onboarding-headline";
    const badge = document.createElement("div");
    badge.className = "spectre-onboarding-badge";
    if (hqImage) {
      const img = document.createElement("img");
      img.src = hqImage;
      img.alt = "HQ badge";
      img.width = 60;
      img.height = 60;
      img.loading = "lazy";
      img.style.width = "100%";
      img.style.height = "100%";
      img.style.objectFit = "cover";
      img.style.borderRadius = "14px";
      badge.appendChild(img);
    } else {
      badge.textContent = "HQ";
    }

    const titleWrap = document.createElement("div");
    titleWrap.className = "spectre-onboarding-title";
    titleWrap.innerHTML = `
      <h1>Command Onboarding</h1>
      <div class="subline">Clearance check. Choose your deployment lane.</div>
    `;

    headline.appendChild(badge);
    headline.appendChild(titleWrap);

    const body = document.createElement("div");
    body.className = "spectre-onboarding-body";
    body.innerHTML = `
      <div>Welcome, Operator. This channel is locked until you acknowledge orders.</div>
      <div><strong>Option 1 — Continue mission:</strong> Proceed to the standard control deck.</div>
      <div><strong>Option 2 — Take me to A.L.I.C.E:</strong> Deployment node pending activation.</div>
    `;

    const actions = document.createElement("div");
    actions.className = "spectre-onboarding-actions";

    const continueBtn = document.createElement("button");
    continueBtn.type = "button";
    continueBtn.className = "btn";
    continueBtn.textContent = "Continue as normal";

    const aliceBtn = document.createElement("button");
    aliceBtn.type = "button";
    aliceBtn.className = "btn secondary";
    aliceBtn.textContent = "Take me to A.L.I.C.E";

    const dismiss = (origin) => {
      sessionStorage.setItem(STORAGE_KEY, origin);
      overlay.remove();
      style.remove();
    };

    continueBtn.addEventListener("click", () => dismiss("continue"));
    aliceBtn.addEventListener("click", () => {
      console.info("A.L.I.C.E routing will be enabled in a future deployment.");
      dismiss("alice");
    });

    actions.append(continueBtn, aliceBtn);
    inner.append(headline, body, actions);
    card.append(inner);
    overlay.append(card);

    document.head.appendChild(style);
    document.body.prepend(overlay);
  };

  ready(() => { void buildOverlay(); });
})();
