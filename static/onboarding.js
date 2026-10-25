(() => {
  const STORAGE_KEY = "spectre-onboarding-complete";
  const ONBOARDING_COOLDOWN_MS = 10 * 60 * 1000;
  const ALLOWED_PATHS = ["/", "/alice", "/director"];
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

  const disableOnboarding = () => {
    const overlay = document.querySelector(".spectre-onboarding-overlay");
    if (overlay && typeof overlay.remove === "function") {
      overlay.remove();
    }

    const style = document.getElementById("spectre-onboarding-style");
    if (style && typeof style.remove === "function") {
      style.remove();
    }

    setCookie(STORAGE_KEY, String(Date.now()), 365 * 24 * 60 * 60);
  };

  const tourStops = [
    {
      title: "Command Deck",
      description:
        "Review live operations, track deployments, and keep your squad synced with the latest directives.",
      href: "/",
    },
    {
      title: "A.L.I.C.E Relay",
      description:
        "Meet the AI liaison that routes intel, surfaces anomalies, and keeps the secure comms humming.",
      href: "/alice",
    },
    {
      title: "Director's Briefing",
      description:
        "Pull narrative dossiers, mission histories, and the strategic intent behind every dispatch.",
      href: "/director",
    },
    {
      title: "Fleet Watch",
      description:
        "Monitor ship status, resupply cadence, and waypoint confirmations without leaving the cockpit.",
      href: "/fleet",
    },
  ];

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

  const getCookie = (name) => {
    const match = document.cookie
      .split(";")
      .map((entry) => entry.trim())
      .find((entry) => entry.startsWith(`${name}=`));
    if (!match) return null;
    return decodeURIComponent(match.split("=")[1] || "");
  };

  const setCookie = (name, value, maxAgeSeconds) => {
    const safeValue = encodeURIComponent(value);
    const directives = [
      `${name}=${safeValue}`,
      "path=/",
      `max-age=${maxAgeSeconds}`,
      "SameSite=Lax",
    ];
    document.cookie = directives.join("; ");
  };

  const shouldShowOnboarding = () => false;

  const normalizePath = (path) => {
    const trimmed = path.replace(/\/+$/, "");
    return trimmed || "/";
  };

  const buildOverlay = async () => {
    if (!shouldShowOnboarding()) {
      disableOnboarding();
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
      .spectre-onboarding-actions .btn.tertiary {
        background: transparent;
        color: #a5f3c7;
        border-color: rgba(133, 255, 169, .35);
      }
      .spectre-onboarding-actions .btn.tour {
        background: linear-gradient(135deg, rgba(57, 93, 132, .96), rgba(27, 43, 66, .96));
        border-color: rgba(143, 194, 255, .65);
        color: #dbebff;
      }
      .spectre-onboarding-tour {
        margin-top: 10px;
        padding: 14px 16px 12px;
        border-radius: 12px;
        background: rgba(22, 35, 52, .72);
        border: 1px solid rgba(143, 194, 255, .3);
        color: #deebff;
        display: grid;
        gap: 10px;
      }
      .spectre-onboarding-tour header {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 10px;
      }
      .spectre-onboarding-tour .tour-label {
        font-size: 12px;
        letter-spacing: .9px;
        text-transform: uppercase;
        color: #8eb6ff;
      }
      .spectre-onboarding-tour .tour-title {
        margin: 0;
        font-size: 18px;
        letter-spacing: .6px;
      }
      .spectre-onboarding-tour .tour-body {
        color: #cfdcf5;
        line-height: 1.5;
      }
      .spectre-onboarding-tour .tour-actions {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        align-items: center;
      }
      .spectre-onboarding-tour .chip {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 8px 10px;
        border-radius: 10px;
        background: rgba(143, 194, 255, .1);
        border: 1px solid rgba(143, 194, 255, .25);
        color: #bcd7ff;
        font-weight: 700;
        letter-spacing: .4px;
      }
      .spectre-onboarding-tour .tour-nav {
        display: flex;
        gap: 8px;
        margin-left: auto;
      }
      .spectre-onboarding-tour .tour-nav button {
        background: transparent;
        color: #deebff;
        border: 1px solid rgba(143, 194, 255, .35);
        border-radius: 10px;
        padding: 8px 12px;
        cursor: pointer;
        transition: background .2s ease, border-color .2s ease;
      }
      .spectre-onboarding-tour .tour-nav button:hover {
        background: rgba(143, 194, 255, .08);
        border-color: rgba(143, 194, 255, .5);
      }
      .spectre-onboarding-tour .tour-link {
        background: linear-gradient(135deg, rgba(86, 149, 73, .95), rgba(24, 48, 24, .95));
        border: 1px solid rgba(133, 255, 169, .6);
        color: #e8f4ec;
        border-radius: 10px;
        padding: 8px 14px;
        font-weight: 700;
        letter-spacing: .3px;
        cursor: pointer;
        transition: transform .1s ease, box-shadow .2s ease;
      }
      .spectre-onboarding-tour .tour-link:hover {
        transform: translateY(-1px);
        box-shadow: 0 10px 30px rgba(76, 175, 80, .28);
      }
      .spectre-onboarding-tour footer {
        display: flex;
        gap: 10px;
        align-items: center;
        justify-content: space-between;
        flex-wrap: wrap;
      }
      .spectre-onboarding-info {
        margin: -6px 8px 0;
        padding: 12px 14px;
        border-radius: 10px;
        background: rgba(42, 66, 54, .35);
        color: #cfe8d9;
        border: 1px solid rgba(133, 255, 169, .28);
        line-height: 1.5;
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
      <div class="subline">Clearance confirmed, Operator. Choose how you want to enter.</div>
    `;

    headline.appendChild(badge);
    headline.appendChild(titleWrap);

    const body = document.createElement("div");
    body.className = "spectre-onboarding-body";
    body.innerHTML = `
      <div>Welcome aboard. We held the channel until you arrived—pick a lane and we'll open your dashboards.</div>
      <div><strong>Continue mission</strong> keeps you on the primary deck with your usual controls.</div>
      <div><strong>Take me to A.L.I.C.E</strong> pairs you with the liaison AI for intel routing.</div>
      <div><strong>Want a quick tour?</strong> Launch the recon brief to see what's waiting inside.</div>
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

    const tourBtn = document.createElement("button");
    tourBtn.type = "button";
    tourBtn.className = "btn tour";
    tourBtn.textContent = "Launch recon tour";
    tourBtn.setAttribute("aria-expanded", "false");

    const knowMoreBtn = document.createElement("button");
    knowMoreBtn.type = "button";
    knowMoreBtn.className = "btn tertiary";
    knowMoreBtn.setAttribute("aria-expanded", "false");
    knowMoreBtn.textContent = "Know more about A.L.I.C.E";

    const aliceDetails = document.createElement("div");
    aliceDetails.className = "spectre-onboarding-info";
    aliceDetails.hidden = true;
    aliceDetails.tabIndex = -1;
    aliceDetails.textContent =
      "A.L.I.C.E is your embedded liaison—she triages anomalies, escorts you into secure comms, and narrates the intel stream so you can stay heads-up.";

    const tourPanel = document.createElement("section");
    tourPanel.className = "spectre-onboarding-tour";
    tourPanel.hidden = true;
    tourPanel.tabIndex = -1;
    tourPanel.id = "spectre-onboarding-tour";
    tourPanel.setAttribute("aria-label", "Guided tour stops");
    tourBtn.setAttribute("aria-controls", tourPanel.id);

    const tourHeader = document.createElement("header");
    const tourLabel = document.createElement("div");
    tourLabel.className = "tour-label";
    tourLabel.textContent = "Recon tour";
    const tourTitle = document.createElement("h3");
    tourTitle.className = "tour-title";
    tourTitle.textContent = "Get the lay of the land";
    tourHeader.append(tourLabel, tourTitle);

    const tourBody = document.createElement("div");
    tourBody.className = "tour-body";

    const tourFooter = document.createElement("footer");
    const tourChip = document.createElement("div");
    tourChip.className = "chip";
    const tourLink = document.createElement("button");
    tourLink.type = "button";
    tourLink.className = "tour-link";
    tourLink.textContent = "Open stop";
    const tourNav = document.createElement("div");
    tourNav.className = "tour-nav";
    const prevBtn = document.createElement("button");
    prevBtn.type = "button";
    prevBtn.textContent = "Previous";
    const nextBtn = document.createElement("button");
    nextBtn.type = "button";
    nextBtn.textContent = "Next";
    tourNav.append(prevBtn, nextBtn);

    let tourIndex = 0;
    const resolveStopIndex = (index) => (index % tourStops.length + tourStops.length) % tourStops.length;
    const updateTour = () => {
      const stop = tourStops[resolveStopIndex(tourIndex)];
      tourTitle.textContent = stop.title;
      tourBody.textContent = stop.description;
      tourChip.textContent = `Stop ${resolveStopIndex(tourIndex) + 1} of ${tourStops.length}`;
      tourLink.dataset.href = stop.href;
    };
    updateTour();

    const cycleTour = (delta) => {
      tourIndex = resolveStopIndex(tourIndex + delta);
      updateTour();
    };

    tourBtn.addEventListener("click", () => {
      const willShow = tourPanel.hidden;
      tourPanel.hidden = !willShow;
      tourBtn.setAttribute("aria-expanded", String(willShow));
      if (willShow) {
        tourPanel.focus({ preventScroll: true });
        updateTour();
      }
    });

    prevBtn.addEventListener("click", () => cycleTour(-1));
    nextBtn.addEventListener("click", () => cycleTour(1));
    tourLink.addEventListener("click", () => {
      const target = tourLink.dataset.href || "/";
      dismiss();
      window.location.href = target;
    });

    const dismiss = () => {
      setCookie(STORAGE_KEY, `${Date.now()}`, Math.ceil(ONBOARDING_COOLDOWN_MS / 1000));
      overlay.remove();
      style.remove();
    };

    continueBtn.addEventListener("click", dismiss);
    aliceBtn.addEventListener("click", () => {
      console.info("Routing to A.L.I.C.E loading screen.");
      dismiss();
      window.location.href = "/alice";
    });

    knowMoreBtn.addEventListener("click", () => {
      aliceDetails.hidden = !aliceDetails.hidden;
      const isExpanded = !aliceDetails.hidden;
      knowMoreBtn.setAttribute("aria-expanded", String(isExpanded));
      if (isExpanded) {
        aliceDetails.focus();
      }
    });

    tourFooter.append(tourChip, tourLink, tourNav);
    tourPanel.append(tourHeader, tourBody, tourFooter);

    actions.append(continueBtn, aliceBtn, tourBtn, knowMoreBtn);
    inner.append(headline, body, actions, aliceDetails, tourPanel);
    card.append(inner);
    overlay.append(card);

    document.head.appendChild(style);
    document.body.prepend(overlay);
  };

  ready(() => {
    disableOnboarding();
  });
})();
