(function initWaspAudioModule(global) {
  const AUDIO_STATE_KEY = 'spectre_wasp_audio_state_v2';
  const LEGACY_AUDIO_STATE_KEY = 'spectre_wasp_audio_state_v1';
  const AUDIO_PROGRESS_KEY = 'spectre_wasp_audio_progress_v1';
  const CHANNEL_NAME = 'spectre_wasp_audio';
  const PROGRESS_WRITE_INTERVAL_MS = 1000;

  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const toNumber = (value, fallback) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  };

  const safeParse = (value) => {
    try {
      return JSON.parse(value);
    } catch (_error) {
      return null;
    }
  };

  // Storage can be unavailable (private browsing, blocked site data) and even
  // reading it can throw; the player must keep working from in-memory state.
  const storageGet = (key) => {
    try {
      return global.localStorage.getItem(key);
    } catch (_error) {
      return null;
    }
  };

  const storageSet = (key, value) => {
    try {
      global.localStorage.setItem(key, value);
    } catch (_error) {
      // Ignore storage write limitations.
    }
  };

  const readState = () => {
    const parsed = safeParse(storageGet(AUDIO_STATE_KEY));
    if (parsed && typeof parsed === 'object') {
      return parsed;
    }
    const legacy = safeParse(storageGet(LEGACY_AUDIO_STATE_KEY));
    return legacy && typeof legacy === 'object' ? legacy : null;
  };

  const readProgress = () => {
    const parsed = safeParse(storageGet(AUDIO_PROGRESS_KEY));
    return parsed && typeof parsed === 'object' ? parsed : null;
  };

  const persistProgress = (progress) => {
    storageSet(AUDIO_PROGRESS_KEY, JSON.stringify(progress));
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

    const lastIndex = Math.max(0, tracks.length - 1);

    // The saved track is matched by URL first so a reordered or trimmed playlist
    // never resumes a different song at the old song's position.
    const resolveTrackIndex = (saved, fallback = 0) => {
      const savedUrl = saved?.trackUrl;
      if (savedUrl) {
        const byUrl = tracks.findIndex((track) => track?.url === savedUrl);
        if (byUrl >= 0) return byUrl;
      }
      return clamp(Math.trunc(toNumber(saved?.trackIndex, fallback)), 0, lastIndex);
    };

    const persisted = readState();
    const initialVolume = toNumber(config?.defaultVolume, 50);

    const state = {
      volume: clamp(toNumber(persisted?.volume, initialVolume), 0, 100),
      muted: Boolean(persisted?.muted),
      trackIndex: resolveTrackIndex(persisted),
      playing: Boolean(persisted?.musicEnabled) && Boolean(persisted?.playing),
      musicEnabled: Boolean(persisted?.musicEnabled),
    };

    // Set when another tab takes over playback; this page then stops writing
    // shared state so it cannot clobber the tab that is actually playing.
    let yieldedToOtherTab = false;
    let consecutiveErrors = 0;
    let lastProgressWrite = 0;
    let resumeInFlight = false;
    let pendingSeek = null;

    const getCurrentTrack = () => tracks[state.trackIndex] || null;

    const persistState = () => {
      storageSet(AUDIO_STATE_KEY, JSON.stringify({
        ...state,
        trackUrl: getCurrentTrack()?.url || '',
      }));
    };

    const formatTime = (rawSeconds) => {
      const safe = Math.max(0, toNumber(rawSeconds, 0));
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
        button.classList.toggle('is-playing', isPlaying);
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
      if (!yieldedToOtherTab) persistState();
      refreshToggleButtons();
      refreshPlayPauseButtons();
      syncVolumeUI();
    };

    const savedPositionFor = (track) => {
      const progress = readProgress();
      if (!progress || !track) return 0;
      const matches = progress.trackUrl
        ? progress.trackUrl === track.url
        : Number(progress.trackIndex) === state.trackIndex;
      const time = toNumber(progress.time, 0);
      return matches && time > 0 ? time : 0;
    };

    const loadTrack = (restoreProgress = false, { force = false } = {}) => {
      const activeTrack = getCurrentTrack();
      if (!activeTrack?.url) return false;

      const targetHref = new URL(activeTrack.url, global.location.origin).href;
      const changedTrack = audioEl.src !== targetHref;
      if (changedTrack) {
        audioEl.src = activeTrack.url;
        audioEl.load();
      }

      // Only jump to the saved position for a freshly loaded track; resuming a
      // paused track in place must not rewind to the last persisted timestamp.
      if (restoreProgress && (changedTrack || force || audioEl.currentTime < 0.5)) {
        const resumeTime = savedPositionFor(activeTrack);
        if (pendingSeek) {
          audioEl.removeEventListener('loadedmetadata', pendingSeek);
          pendingSeek = null;
        }
        if (resumeTime > 0) {
          const seek = () => {
            pendingSeek = null;
            if (!Number.isFinite(audioEl.duration) || resumeTime <= audioEl.duration + 1) {
              try {
                audioEl.currentTime = resumeTime;
              } catch (_error) {
                // Not seekable yet; playback simply starts from the top.
              }
            }
          };
          if (audioEl.readyState >= 1) {
            seek();
          } else {
            pendingSeek = seek;
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

    const persistPlaybackPosition = (time) => {
      if (yieldedToOtherTab) return;
      const current = time ?? (Number.isFinite(audioEl.currentTime) ? audioEl.currentTime : 0);
      persistProgress({
        trackIndex: state.trackIndex,
        trackUrl: getCurrentTrack()?.url || '',
        time: current,
        updatedAt: Date.now(),
      });
    };

    let channel = null;
    try {
      channel = typeof global.BroadcastChannel === 'function' ? new global.BroadcastChannel(CHANNEL_NAME) : null;
    } catch (_error) {
      channel = null;
    }
    const instanceId = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
    const announcePlaying = () => {
      try {
        channel?.postMessage({ type: 'playing', id: instanceId });
      } catch (_error) {
        // Cross-tab coordination is best effort.
      }
    };

    const play = async (hint = 'Playing', options = {}) => {
      state.musicEnabled = true;
      yieldedToOtherTab = false;
      const shouldRestoreProgress = Boolean(options?.restoreProgress);
      const preservePlayingOnFail = Boolean(options?.preservePlayingOnFail);
      audioEl.preload = 'auto';
      if (!loadTrack(shouldRestoreProgress)) {
        updateStatus();
        return false;
      }
      applyState();
      try {
        await audioEl.play();
        state.playing = true;
        persistState();
        updateStatus(hint);
        announcePlaying();
        return true;
      } catch (error) {
        // AbortError: a newer load or play call interrupted this one and owns
        // the outcome. NotSupportedError: the track failed to load and the
        // 'error' handler (which runs first) already skipped or stopped.
        if (error?.name === 'AbortError' || error?.name === 'NotSupportedError') return false;
        state.playing = preservePlayingOnFail;
        persistState();
        if (preservePlayingOnFail && state.musicEnabled) {
          updateStatus('Autoplay blocked · tap to resume');
        } else {
          updateStatus('Click a control to start');
        }
        refreshPlayPauseButtons();
        return false;
      }
    };

    const disableMusic = () => {
      state.musicEnabled = false;
      state.playing = false;
      audioEl.pause();
      persistState();
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
      if (!state.musicEnabled || audioEl.paused) {
        void play('Playing', { restoreProgress: true });
        return;
      }
      audioEl.pause();
      state.playing = false;
      persistState();
      updateStatus('Paused');
      refreshPlayPauseButtons();
    };

    const stepTrack = (delta) => {
      state.trackIndex = (state.trackIndex + delta + tracks.length) % tracks.length;
      persistPlaybackPosition(0);
    };

    const next = async () => {
      stepTrack(1);
      await play('Playing');
    };

    const previous = async () => {
      stepTrack(-1);
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
      if (!audioEl.getAttribute('src')) return;
      consecutiveErrors += 1;
      if (consecutiveErrors >= tracks.length) {
        // Every track failed in a row: stop instead of cycling forever.
        state.playing = false;
        if (!yieldedToOtherTab) persistState();
        updateStatus('Tracks unavailable · try again later');
        refreshPlayPauseButtons();
        return;
      }
      if (state.musicEnabled && state.playing) {
        updateStatus('Track error · skipping');
        void next();
        return;
      }
      // Music is off: move past the broken track without switching music on.
      stepTrack(1);
      if (!yieldedToOtherTab) persistState();
      loadTrack(false);
      updateStatus();
    });

    audioEl.addEventListener('playing', () => {
      consecutiveErrors = 0;
    });

    audioEl.addEventListener('timeupdate', () => {
      if (!audioEl.paused) {
        const now = Date.now();
        if (now - lastProgressWrite >= PROGRESS_WRITE_INTERVAL_MS) {
          lastProgressWrite = now;
          persistPlaybackPosition();
        }
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
      persistPlaybackPosition();
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

    if (channel) {
      channel.addEventListener('message', (event) => {
        const message = event?.data;
        if (!message || message.type !== 'playing' || message.id === instanceId) return;
        if (!state.playing && audioEl.paused) return;
        // Another tab started the soundtrack: hand playback over instead of
        // playing two copies on top of each other.
        yieldedToOtherTab = true;
        state.playing = false;
        if (!audioEl.paused) audioEl.pause();
        updateStatus('Playing in another tab');
        refreshPlayPauseButtons();
      });
    }

    const wantsPlayback = () => state.musicEnabled && state.playing && audioEl.paused;

    const resume = async () => {
      if (resumeInFlight || !wantsPlayback()) return;
      resumeInFlight = true;
      try {
        await play('Playing', { restoreProgress: true, preservePlayingOnFail: true });
      } finally {
        resumeInFlight = false;
      }
    };

    // Browsers block autoplay until the visitor interacts, so the first
    // interaction resumes playback. Presses on the player's own controls are
    // skipped: their click handler runs right after and would otherwise undo
    // the resume (pausing it again or switching music off).
    const tryResumeAfterInteraction = (event) => {
      const target = event?.target;
      if (target instanceof Element && target.closest('[data-audio-control]')) return;
      void resume();
    };
    global.addEventListener('pointerdown', tryResumeAfterInteraction);
    global.addEventListener('keydown', tryResumeAfterInteraction);
    global.addEventListener('touchstart', tryResumeAfterInteraction, { passive: true });

    // Pull in whatever other pages changed while this one sat in the
    // back/forward cache, so going "back" never revives stale settings.
    const syncFromStorage = () => {
      const latest = readState();
      if (!latest) return;
      state.volume = clamp(toNumber(latest.volume, state.volume), 0, 100);
      state.muted = Boolean(latest.muted);
      state.musicEnabled = Boolean(latest.musicEnabled);
      state.playing = state.musicEnabled && Boolean(latest.playing);
      state.trackIndex = resolveTrackIndex(latest, state.trackIndex);
      yieldedToOtherTab = false;
      if (!state.musicEnabled && !audioEl.paused) audioEl.pause();
      loadTrack(true, { force: true });
      applyState();
      updateStatus();
    };

    global.addEventListener('pageshow', (event) => {
      if (!event?.persisted) return;
      syncFromStorage();
      void resume();
    });

    const persistAll = () => {
      if (yieldedToOtherTab) return;
      persistState();
      persistPlaybackPosition();
    };

    global.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') {
        persistAll();
        return;
      }
      void resume();
    });

    // pagehide (unlike beforeunload) fires reliably on mobile and keeps the
    // page eligible for the back/forward cache.
    global.addEventListener('pagehide', persistAll);

    audioEl.preload = state.musicEnabled ? 'auto' : 'metadata';
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
    };
  };
})(window);
