(function initGlobalWaspPlayer(global) {
  const ROOT_ID = "global-wasp-audio-widget";

  function createMarkup() {
    const root = document.createElement("section");
    root.id = ROOT_ID;
    root.className = "wasp-global-audio";
    root.setAttribute("aria-label", "Global WASP audio controls");
    root.innerHTML = `
      <div class="wasp-global-audio__top">
        <p class="wasp-global-audio__title">WASP Player</p>
        <div class="wasp-global-audio__header-actions">
          <button type="button" class="audio-btn" data-audio-control="toggle" aria-label="Enable music" title="Enable music">⏻</button>
          <button type="button" class="audio-btn" data-widget-control="collapse" aria-label="Collapse player" title="Collapse player">▾</button>
        </div>
      </div>
      <div class="wasp-global-audio__content">
        <audio id="global-wasp-audio-element" preload="auto"></audio>
        <p class="wasp-global-audio__track" id="global-wasp-track-name">No track loaded</p>
        <div class="wasp-global-audio__timeline">
          <span class="wasp-global-audio__time" id="global-wasp-current-time">0:00</span>
          <input
            id="global-wasp-seek-slider"
            class="wasp-global-audio__seek"
            type="range"
            min="0"
            max="100"
            step="0.1"
            value="0"
            aria-label="Seek track position"
          >
          <span class="wasp-global-audio__time" id="global-wasp-duration">0:00</span>
        </div>
        <div class="wasp-global-audio__controls" role="group" aria-label="WASP audio controls">
          <button type="button" class="audio-btn" data-audio-control="previous" aria-label="Previous track" title="Previous track">⏮</button>
          <button type="button" class="audio-btn" data-audio-control="playpause" aria-label="Play" title="Play">▶</button>
          <button type="button" class="audio-btn" data-audio-control="next" aria-label="Next track" title="Next track">⏭</button>
        </div>
        <div class="wasp-global-audio__volume-row">
          <span aria-hidden="true">🔊</span>
          <input
            id="global-wasp-volume-slider"
            class="wasp-global-audio__volume"
            type="range"
            min="0"
            max="100"
            step="1"
            value="50"
            aria-label="Set volume"
          >
          <span class="wasp-global-audio__volume-value" id="global-wasp-volume-value">50%</span>
        </div>
        <p class="wasp-global-audio__status" id="global-wasp-audio-status" aria-live="polite">Music off</p>
      </div>
    `;
    return root;
  }

  global.mountGlobalWaspPlayer = function mountGlobalWaspPlayer(options) {
    if (typeof global.setupWaspAudioControls !== "function") {
      return null;
    }

    const tracks = Array.isArray(options?.tracks) ? options.tracks : [];
    let root = document.getElementById(ROOT_ID);
    if (!root) {
      root = createMarkup();
      document.body.appendChild(root);
    }

    if (root.dataset.initialized === "true") {
      return root._waspController || null;
    }

    const audioEl = root.querySelector("#global-wasp-audio-element");
    const statusEl = root.querySelector("#global-wasp-audio-status");
    const trackNameEl = root.querySelector("#global-wasp-track-name");
    const buttons = Array.from(root.querySelectorAll("[data-audio-control]"));
    const collapseBtn = root.querySelector('[data-widget-control="collapse"]');
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
      || !collapseBtn
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
      root.dataset.initialized = "true";
      root._waspController = null;
      return null;
    }

    if (controller.state.uiCollapsed) {
      root.classList.add("is-collapsed");
      collapseBtn.textContent = "▸";
      collapseBtn.setAttribute("aria-label", "Expand player");
      collapseBtn.title = "Expand player";
    }

    collapseBtn.addEventListener("click", function handleCollapseClick() {
      const collapsed = root.classList.toggle("is-collapsed");
      collapseBtn.textContent = collapsed ? "▸" : "▾";
      collapseBtn.setAttribute("aria-label", collapsed ? "Expand player" : "Collapse player");
      collapseBtn.title = collapsed ? "Expand player" : "Collapse player";
      if (typeof controller.setCollapsed === "function") {
        controller.setCollapsed(collapsed);
      }
    });

    root.dataset.initialized = "true";
    root._waspController = controller;
    return controller;
  };
})(window);
