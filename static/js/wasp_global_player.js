(function initGlobalWaspPlayer(global) {
  const ROOT_ID = "global-wasp-audio-widget";
  const WIDGET_VERSION = "3";
  const STYLESHEET_HREF = "/static/wasp_global_player.css?v=20261026a";

  // The widget lives on <body>, outside the persistent shell's swapped content,
  // so it survives in-page navigation. It brings its own stylesheet (marked
  // data-shell-persist) because the page it lands on may not link one, and the
  // shell would otherwise drop the previous page's copy and leave it unstyled.
  function ensureStylesheet() {
    if (document.querySelector("link[data-wasp-player-style]")) return;
    // Compare paths, not a pattern: the server may publish /static/... under a scrambled path.
    const stylesheetPath = new URL(STYLESHEET_HREF, global.location.href).pathname;
    const pageLink = Array.from(document.querySelectorAll('link[rel="stylesheet"]')).find(
      (node) => node.href && new URL(node.href).pathname === stylesheetPath
    );
    if (pageLink) {
      pageLink.setAttribute("data-wasp-player-style", "true");
      pageLink.setAttribute("data-shell-persist", "true");
      pageLink.removeAttribute("data-shell-managed");
      return;
    }
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = STYLESHEET_HREF;
    link.setAttribute("data-wasp-player-style", "true");
    link.setAttribute("data-shell-persist", "true");
    document.head.appendChild(link);
  }

  const ICONS = {
    play: '<path d="M8 5.5v13l10.5-6.5z"/>',
    pause: '<path d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z"/>',
    previous: '<path d="M6 5h2.2v14H6zM19 5.5v13L9.5 12z"/>',
    next: '<path d="M15.8 5H18v14h-2.2zM5 5.5v13l9.5-6.5z"/>',
    chevron: '<path d="M6.4 15.4 12 9.8l5.6 5.6 1.4-1.4-7-7-7 7z"/>',
    volume: '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4zM15 8.6a4.5 4.5 0 0 1 0 6.8l-1.1-1.2a2.9 2.9 0 0 0 0-4.4zM17.3 6.2a8 8 0 0 1 0 11.6l-1.1-1.1a6.4 6.4 0 0 0 0-9.4z"/>',
  };

  const icon = (name, extraClass = "") => `<svg class="wasp-global-audio__icon ${extraClass}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${ICONS[name]}</svg>`;

  // A slim bar is all that shows by default; the timeline and volume open above it.
  function createMarkup() {
    const root = document.createElement("section");
    root.id = ROOT_ID;
    root.className = "wasp-global-audio";
    root.setAttribute("data-shell-persist", "true");
    root.setAttribute("aria-label", "W.A.S.P. music player");
    root.innerHTML = `
      <audio id="global-wasp-audio-element" preload="metadata"></audio>
      <div class="wasp-global-audio__panel" id="global-wasp-audio-panel" hidden>
        <div class="wasp-global-audio__timeline">
          <span class="wasp-global-audio__time" id="global-wasp-current-time">0:00</span>
          <input
            id="global-wasp-seek-slider"
            class="wasp-global-audio__range"
            type="range"
            min="0"
            max="100"
            step="0.1"
            value="0"
            aria-label="Seek track position"
          >
          <span class="wasp-global-audio__time" id="global-wasp-duration">0:00</span>
        </div>
        <div class="wasp-global-audio__volume-row">
          ${icon("volume")}
          <input
            id="global-wasp-volume-slider"
            class="wasp-global-audio__range"
            type="range"
            min="0"
            max="100"
            step="1"
            value="50"
            aria-label="Set volume"
          >
          <span class="wasp-global-audio__time" id="global-wasp-volume-value">50%</span>
        </div>
      </div>
      <div class="wasp-global-audio__bar" role="group" aria-label="Playback">
        <button type="button" class="audio-btn audio-btn--step" data-audio-control="previous" aria-label="Previous track" title="Previous track">${icon("previous")}</button>
        <button type="button" class="audio-btn audio-btn--play" data-audio-control="playpause" aria-label="Play" title="Play">${icon("play", "icon-play")}${icon("pause", "icon-pause")}</button>
        <button type="button" class="audio-btn audio-btn--step" data-audio-control="next" aria-label="Next track" title="Next track">${icon("next")}</button>
        <div class="wasp-global-audio__meta">
          <p class="wasp-global-audio__track" id="global-wasp-track-name">No track loaded</p>
          <p class="wasp-global-audio__status" id="global-wasp-audio-status" aria-live="polite">Music off</p>
        </div>
        <button type="button" class="audio-btn audio-btn--ghost" data-widget-control="expand" aria-expanded="false" aria-controls="global-wasp-audio-panel" aria-label="Show player controls" title="Show player controls">${icon("chevron", "icon-chevron")}</button>
      </div>
    `;
    return root;
  }

  // Range inputs paint their filled part from --fill so they look the same in every browser.
  function paintRange(slider) {
    const min = Number(slider.min) || 0;
    const max = Number(slider.max) || 100;
    const value = Number(slider.value) || 0;
    const percent = max > min ? ((value - min) / (max - min)) * 100 : 0;
    slider.style.setProperty("--fill", `${Math.max(0, Math.min(100, percent))}%`);
    return percent;
  }

  global.mountGlobalWaspPlayer = function mountGlobalWaspPlayer(options) {
    if (typeof global.setupWaspAudioControls !== "function") {
      return null;
    }

    ensureStylesheet();
    const tracks = Array.isArray(options?.tracks) ? options.tracks : [];
    let root = document.getElementById(ROOT_ID);
    if (root && root.dataset.widgetVersion !== WIDGET_VERSION) {
      root.remove();
      root = null;
    }
    if (!root) {
      root = createMarkup();
      root.dataset.widgetVersion = WIDGET_VERSION;
      document.body.appendChild(root);
    }

    if (root.dataset.initialized === "true") {
      return root._waspController || null;
    }

    const audioEl = root.querySelector("#global-wasp-audio-element");
    const statusEl = root.querySelector("#global-wasp-audio-status");
    const trackNameEl = root.querySelector("#global-wasp-track-name");
    const buttons = Array.from(root.querySelectorAll("[data-audio-control]"));
    const expandBtn = root.querySelector('[data-widget-control="expand"]');
    const panel = root.querySelector("#global-wasp-audio-panel");
    const seekSlider = root.querySelector("#global-wasp-seek-slider");
    const currentTimeEl = root.querySelector("#global-wasp-current-time");
    const durationEl = root.querySelector("#global-wasp-duration");
    const volumeSlider = root.querySelector("#global-wasp-volume-slider");
    const volumeValueEl = root.querySelector("#global-wasp-volume-value");

    if (
      !audioEl
      || !statusEl
      || !trackNameEl
      || !buttons.length
      || !expandBtn
      || !panel
      || !seekSlider
      || !currentTimeEl
      || !durationEl
      || !volumeSlider
      || !volumeValueEl
    ) {
      return null;
    }

    const controller = global.setupWaspAudioControls({
      tracks,
      audioElement: audioEl,
      statusElement: statusEl,
      trackNameElement: trackNameEl,
      buttons,
      seekSlider,
      currentTimeElement: currentTimeEl,
      durationElement: durationEl,
      volumeSlider,
      volumeValueElement: volumeValueEl,
      defaultVolume: Number.isFinite(Number(options?.defaultVolume)) ? Number(options.defaultVolume) : 50,
      autoPlay: false,
    });

    if (!controller) {
      root.classList.add("is-empty");
      root.dataset.initialized = "true";
      root._waspController = null;
      return null;
    }

    // The player always starts as the slim bar; the panel is a popover that
    // closes on Escape or a press anywhere else on the page.
    const setExpanded = (expanded) => {
      root.classList.toggle("is-expanded", expanded);
      panel.hidden = !expanded;
      const label = expanded ? "Hide player controls" : "Show player controls";
      expandBtn.setAttribute("aria-expanded", expanded ? "true" : "false");
      expandBtn.setAttribute("aria-label", label);
      expandBtn.title = label;
    };

    expandBtn.addEventListener("click", function handleExpandClick() {
      setExpanded(!root.classList.contains("is-expanded"));
    });
    document.addEventListener("pointerdown", function handleOutsidePress(event) {
      if (root.classList.contains("is-expanded") && !root.contains(event.target)) setExpanded(false);
    });
    root.addEventListener("keydown", function handleEscape(event) {
      if (event.key !== "Escape" || !root.classList.contains("is-expanded")) return;
      setExpanded(false);
      expandBtn.focus();
    });

    const syncProgress = () => {
      root.style.setProperty("--wasp-progress", `${paintRange(seekSlider)}%`);
    };
    ["timeupdate", "loadedmetadata", "durationchange", "emptied"].forEach((type) => {
      audioEl.addEventListener(type, syncProgress);
    });
    seekSlider.addEventListener("input", syncProgress);
    audioEl.addEventListener("volumechange", () => paintRange(volumeSlider));
    volumeSlider.addEventListener("input", () => paintRange(volumeSlider));
    syncProgress();
    paintRange(volumeSlider);

    root.dataset.initialized = "true";
    root._waspController = controller;
    return controller;
  };
})(window);
