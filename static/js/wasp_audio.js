(function initWaspAudioModule(global) {
  const AUDIO_STATE_KEY = 'spectre_wasp_audio_state_v1';
  const AUDIO_PROGRESS_KEY = 'spectre_wasp_audio_progress_v1';

  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

  const safeParse = (value) => {
    try {
      return JSON.parse(value);
    } catch (_error) {
      return null;
    }
  };

  const readState = () => {
    const parsed = safeParse(global.localStorage.getItem(AUDIO_STATE_KEY));
    return parsed && typeof parsed === 'object' ? parsed : null;
  };

  const persistState = (state) => {
    try {
      global.localStorage.setItem(AUDIO_STATE_KEY, JSON.stringify(state));
    } catch (_error) {
      // Storage can be unavailable in private browsing; keep in-memory state.
    }
  };

  const readProgress = () => {
    const parsed = safeParse(global.localStorage.getItem(AUDIO_PROGRESS_KEY));
    return parsed && typeof parsed === 'object' ? parsed : null;
  };

  const persistProgress = (progress) => {
    try {
      global.localStorage.setItem(AUDIO_PROGRESS_KEY, JSON.stringify(progress));
    } catch (_error) {
      // Ignore storage write limitations.
    }
  };

  const summarizeTrack = (trackLabel) => String(trackLabel || 'WASP track')
    .replace(/[?#].*$/g, '')
    .replace(/^.*[\\/]/g, '')
    .replace(/\.mp3$/i, '')
    .replace(/[-_]+/g, ' ')
    // Strip common auto-generated date/time suffixes (e.g. 20260402 120258).
    .replace(/(?:\s+)?\d{8}(?:\s?\d{6})?$/g, '')
    .replace(/(?:\s+)?\d{14}$/g, '')
    .replace(/(?:\s+)?\d{4,}(?:\s+\d{2,})*$/g, '')
    .replace(/\s{2,}/g, ' ')
    .trim();

  global.setupWaspAudioControls = function setupWaspAudioControls(config) {
    const tracks = Array.isArray(config?.tracks) ? config.tracks : [];
    const audioEl = config?.audioElement;
    const statusEl = config?.statusElement;
    const buttons = Array.isArray(config?.buttons) ? config.buttons : [];

    if (!audioEl || !statusEl) return null;

    if (!tracks.length) {
      statusEl.textContent = 'Music unavailable · Upload MP3 in Director panel';
      buttons.forEach((button) => {
        button.disabled = true;
        button.classList.add('is-disabled');
      });
      return null;
    }

    const persisted = readState();
    const initialVolume = Number.isFinite(Number(config?.defaultVolume))
      ? Number(config.defaultVolume)
      : 50;

    const state = {
      volume: clamp(Number(persisted?.volume ?? initialVolume), 0, 100),
      muted: Boolean(persisted?.muted),
      trackIndex: clamp(Number(persisted?.trackIndex ?? 0), 0, Math.max(0, tracks.length - 1)),
      playing: Boolean(persisted?.playing),
    };

    const applyState = () => {
      audioEl.volume = state.volume / 100;
      audioEl.muted = state.muted;
      persistState(state);
    };

    const getCurrentTrack = () => tracks[state.trackIndex] || null;

    const loadTrack = (restoreProgress = false) => {
      const activeTrack = getCurrentTrack();
      if (!activeTrack?.url) return false;

      const targetHref = new URL(activeTrack.url, global.location.origin).href;
      const changedTrack = audioEl.src !== targetHref;
      if (changedTrack) {
        audioEl.src = activeTrack.url;
        audioEl.load();
      }

      if (restoreProgress) {
        const progress = readProgress();
        if (
          progress &&
          Number(progress.trackIndex) === state.trackIndex &&
          Number.isFinite(Number(progress.time)) &&
          Number(progress.time) > 0
        ) {
          const resumeTime = Number(progress.time);
          const seek = () => {
            if (Number.isFinite(audioEl.duration) && resumeTime <= audioEl.duration + 1) {
              audioEl.currentTime = resumeTime;
            }
            audioEl.removeEventListener('loadedmetadata', seek);
          };
          if (audioEl.readyState >= 1) {
            seek();
          } else {
            audioEl.addEventListener('loadedmetadata', seek, { once: true });
          }
        }
      }

      return true;
    };

    const updateStatus = (hint = '') => {
      const track = getCurrentTrack();
      const name = summarizeTrack(track?.title || track?.name || track?.filename || track?.url);
      statusEl.textContent = hint ? `${name} · ${hint}` : name;
    };

    const persistPlaybackPosition = () => {
      persistProgress({
        trackIndex: state.trackIndex,
        time: Number.isFinite(audioEl.currentTime) ? audioEl.currentTime : 0,
        updatedAt: Date.now(),
      });
    };

    const play = async (hint = 'Playing') => {
      if (!loadTrack()) {
        updateStatus();
        return;
      }
      applyState();
      try {
        await audioEl.play();
        state.playing = true;
        persistState(state);
        updateStatus(hint);
      } catch (_error) {
        state.playing = false;
        persistState(state);
        updateStatus('Click a control to start');
      }
    };

    const next = async () => {
      state.trackIndex = (state.trackIndex + 1) % tracks.length;
      persistPlaybackPosition();
      await play('Playing');
    };

    const previous = async () => {
      state.trackIndex = (state.trackIndex - 1 + tracks.length) % tracks.length;
      persistPlaybackPosition();
      await play('Playing');
    };

    buttons.forEach((button) => {
      button.addEventListener('click', () => {
        const control = String(button.dataset.audioControl || '').toLowerCase();

        if (control === 'increase') {
          state.volume = clamp(state.volume + 10, 0, 100);
          if (state.volume > 0) state.muted = false;
          applyState();
          updateStatus(audioEl.paused ? 'Ready' : 'Playing');
          if (audioEl.paused) void play('Playing');
          return;
        }

        if (control === 'decrease') {
          state.volume = clamp(state.volume - 10, 0, 100);
          if (state.volume === 0) state.muted = true;
          applyState();
          updateStatus(audioEl.paused ? 'Ready' : 'Playing');
          if (audioEl.paused) void play('Playing');
          return;
        }

        if (control === 'next') {
          void next();
          return;
        }

        if (control === 'previous') {
          void previous();
        }
      });
    });

    audioEl.addEventListener('ended', () => {
      void next();
    });

    audioEl.addEventListener('error', () => {
      updateStatus('Track error · skipping');
      void next();
    });

    audioEl.addEventListener('timeupdate', () => {
      if (!audioEl.paused) {
        persistPlaybackPosition();
      }
    });

    global.addEventListener('beforeunload', () => {
      state.playing = !audioEl.paused;
      persistState(state);
      persistPlaybackPosition();
    });

    applyState();
    loadTrack(true);

    const shouldAutoplay = Boolean(config?.autoPlay);
    if (shouldAutoplay || state.playing) {
      void play('Playing');
    } else {
      updateStatus('Ready');
    }

    return {
      play,
      next,
      previous,
      updateStatus,
      state,
    };
  };
})(window);
