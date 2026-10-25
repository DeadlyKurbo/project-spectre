(function initWaspAudioModule(global) {
  const AUDIO_STATE_KEY = 'spectre_wasp_audio_state_v2';
  const LEGACY_AUDIO_STATE_KEY = 'spectre_wasp_audio_state_v1';
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
    if (parsed && typeof parsed === 'object') {
      return parsed;
    }
    const legacy = safeParse(global.localStorage.getItem(LEGACY_AUDIO_STATE_KEY));
    return legacy && typeof legacy === 'object' ? legacy : null;
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
    const trackNameEl = config?.trackNameElement;
    const buttons = Array.isArray(config?.buttons) ? config.buttons : [];
    const seekSlider = config?.seekSlider;
    const currentTimeEl = config?.currentTimeElement;
    const durationEl = config?.durationElement;
    const volumeSlider = config?.volumeSlider;
    const volumeValueEl = config?.volumeValueElement;

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
      playing: Boolean(persisted?.musicEnabled) && Boolean(persisted?.playing),
      musicEnabled: Boolean(persisted?.musicEnabled),
      uiCollapsed: Boolean(persisted?.uiCollapsed),
    };

    const formatTime = (rawSeconds) => {
      const safe = Number.isFinite(Number(rawSeconds)) ? Math.max(0, Number(rawSeconds)) : 0;
      const total = Math.floor(safe);
      const minutes = Math.floor(total / 60);
      const seconds = total % 60;
      return `${minutes}:${String(seconds).padStart(2, '0')}`;
    };

    const refreshToggleButtons = () => {
      buttons.forEach((button) => {
        const control = String(button.dataset.audioControl || '').toLowerCase();
        if (control !== 'toggle') return;
        button.classList.toggle('is-active', state.musicEnabled);
        button.setAttribute('aria-pressed', state.musicEnabled ? 'true' : 'false');
        button.setAttribute('aria-label', state.musicEnabled ? 'Disable music' : 'Enable music');
        button.title = state.musicEnabled ? 'Disable music' : 'Enable music';
      });
    };

    const refreshPlayPauseButtons = () => {
      buttons.forEach((button) => {
        const control = String(button.dataset.audioControl || '').toLowerCase();
        if (control !== 'playpause') return;
        const isPlaying = state.musicEnabled && !audioEl.paused;
        button.textContent = isPlaying ? '⏸' : '▶';
        button.setAttribute('aria-label', isPlaying ? 'Pause' : 'Play');
        button.title = isPlaying ? 'Pause' : 'Play';
      });
    };

    const syncVolumeUI = () => {
      if (volumeSlider) {
        volumeSlider.value = String(clamp(state.volume, 0, 100));
      }
      if (volumeValueEl) {
        volumeValueEl.textContent = `${Math.round(clamp(state.volume, 0, 100))}%`;
      }
    };

    const syncTimelineUI = () => {
      const duration = Number.isFinite(audioEl.duration) ? audioEl.duration : 0;
      const current = Number.isFinite(audioEl.currentTime) ? audioEl.currentTime : 0;
      if (seekSlider) {
        seekSlider.max = String(duration > 0 ? duration : 100);
        seekSlider.value = String(clamp(current, 0, duration > 0 ? duration : 100));
      }
      if (currentTimeEl) {
        currentTimeEl.textContent = formatTime(current);
      }
      if (durationEl) {
        durationEl.textContent = formatTime(duration);
      }
    };

    const applyState = () => {
      audioEl.volume = state.volume / 100;
      audioEl.muted = state.muted;
      persistState(state);
      refreshToggleButtons();
      refreshPlayPauseButtons();
      syncVolumeUI();
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
          const resumeTime = Math.max(0, Number(progress.time));
          const seek = () => {
            if (!Number.isFinite(audioEl.duration) || resumeTime <= audioEl.duration + 1) {
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
      if (trackNameEl) {
        trackNameEl.textContent = name || 'WASP track';
        statusEl.textContent = hint || (state.musicEnabled ? 'Ready' : 'Music off');
      } else {
        statusEl.textContent = hint ? `${name} · ${hint}` : name;
      }
    };

    const persistPlaybackPosition = () => {
      persistProgress({
        trackIndex: state.trackIndex,
        time: Number.isFinite(audioEl.currentTime) ? audioEl.currentTime : 0,
        updatedAt: Date.now(),
      });
    };

    const play = async (hint = 'Playing', options = {}) => {
      state.musicEnabled = true;
      const shouldRestoreProgress = Boolean(options?.restoreProgress);
      const preservePlayingOnFail = Boolean(options?.preservePlayingOnFail);
      if (!loadTrack(shouldRestoreProgress)) {
        updateStatus();
        return false;
      }
      applyState();
      try {
        await audioEl.play();
        state.playing = true;
        persistState(state);
        updateStatus(hint);
        return true;
      } catch (_error) {
        state.playing = preservePlayingOnFail ? true : false;
        persistState(state);
        if (preservePlayingOnFail && state.musicEnabled) {
          updateStatus('Autoplay blocked · tap to resume');
        } else {
          updateStatus('Click a control to start');
        }
        return false;
      }
    };

    const disableMusic = () => {
      state.musicEnabled = false;
      state.playing = false;
      audioEl.pause();
      persistState(state);
      updateStatus('Music off');
      refreshToggleButtons();
      refreshPlayPauseButtons();
    };

    const toggleMusic = () => {
      if (state.musicEnabled) {
        disableMusic();
        return;
      }
      void play('Playing', { restoreProgress: true });
    };

    const togglePlayPause = () => {
      if (!state.musicEnabled) {
        void play('Playing', { restoreProgress: true });
        return;
      }
      if (audioEl.paused) {
        void play('Playing', { restoreProgress: true });
      } else {
        audioEl.pause();
        state.playing = false;
        persistState(state);
        updateStatus('Paused');
        refreshPlayPauseButtons();
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
          updateStatus(audioEl.paused ? (state.musicEnabled ? 'Ready' : 'Music off') : 'Playing');
          if (audioEl.paused && state.musicEnabled) void play('Playing');
          return;
        }

        if (control === 'decrease') {
          state.volume = clamp(state.volume - 10, 0, 100);
          if (state.volume === 0) state.muted = true;
          applyState();
          updateStatus(audioEl.paused ? (state.musicEnabled ? 'Ready' : 'Music off') : 'Playing');
          if (audioEl.paused && state.musicEnabled) void play('Playing');
          return;
        }

        if (control === 'next') {
          void next();
          return;
        }

        if (control === 'previous') {
          void previous();
          return;
        }

        if (control === 'playpause') {
          togglePlayPause();
          return;
        }

        if (control === 'toggle') {
          toggleMusic();
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
      syncTimelineUI();
      refreshPlayPauseButtons();
    });

    audioEl.addEventListener('loadedmetadata', () => {
      syncTimelineUI();
    });

    audioEl.addEventListener('durationchange', () => {
      syncTimelineUI();
    });

    audioEl.addEventListener('play', () => {
      refreshPlayPauseButtons();
    });

    audioEl.addEventListener('pause', () => {
      refreshPlayPauseButtons();
    });

    if (seekSlider) {
      const onSeek = () => {
        const nextTime = Number(seekSlider.value);
        if (!Number.isFinite(nextTime)) return;
        audioEl.currentTime = Math.max(0, nextTime);
        syncTimelineUI();
      };
      seekSlider.addEventListener('input', onSeek);
      seekSlider.addEventListener('change', onSeek);
    }

    if (volumeSlider) {
      volumeSlider.addEventListener('input', () => {
        const nextVolume = clamp(Number(volumeSlider.value), 0, 100);
        state.volume = nextVolume;
        state.muted = nextVolume === 0;
        applyState();
        updateStatus(audioEl.paused ? (state.musicEnabled ? 'Ready' : 'Music off') : 'Playing');
      });
    }

    const tryResumeAfterInteraction = async () => {
      if (!state.musicEnabled || !state.playing || !audioEl.paused) {
        return;
      }
      const resumed = await play('Playing', { restoreProgress: true, preservePlayingOnFail: true });
      if (resumed) {
        global.removeEventListener('pointerdown', tryResumeAfterInteraction);
        global.removeEventListener('keydown', tryResumeAfterInteraction);
        global.removeEventListener('touchstart', tryResumeAfterInteraction);
      }
    };
    global.addEventListener('pointerdown', tryResumeAfterInteraction);
    global.addEventListener('keydown', tryResumeAfterInteraction);
    global.addEventListener('touchstart', tryResumeAfterInteraction, { passive: true });
    global.addEventListener('pageshow', () => {
      if (!state.musicEnabled || !state.playing || !audioEl.paused) return;
      void play('Playing', { restoreProgress: true, preservePlayingOnFail: true });
    });
    global.addEventListener('visibilitychange', () => {
      if (document.visibilityState !== 'visible') return;
      if (!state.musicEnabled || !state.playing || !audioEl.paused) return;
      void play('Playing', { restoreProgress: true, preservePlayingOnFail: true });
    });

    global.addEventListener('beforeunload', () => {
      state.playing = state.musicEnabled && state.playing;
      persistState(state);
      persistPlaybackPosition();
    });

    applyState();
    loadTrack(true);
    syncTimelineUI();

    const shouldAutoplay = Boolean(config?.autoPlay);
    const shouldResume = state.musicEnabled && (shouldAutoplay || state.playing);
    if (shouldResume) {
      void play('Playing', { restoreProgress: true, preservePlayingOnFail: true });
    } else if (state.musicEnabled) {
      updateStatus('Ready');
    } else {
      updateStatus('Music off');
    }

    return {
      play,
      next,
      previous,
      updateStatus,
      state,
      disableMusic,
      toggleMusic,
      setCollapsed(collapsed) {
        state.uiCollapsed = Boolean(collapsed);
        persistState(state);
      },
    };
  };
})(window);
