(() => {
  const clockEl = document.getElementById('clock');
  const greetingEl = document.getElementById('greeting-text');
  const yearEl = document.getElementById('year');
  const callsignForm = document.getElementById('callsign-form');
  const callsignInput = document.getElementById('callsign-input');
  const callsignReset = document.getElementById('callsign-reset');

  const CALLSIGN_KEY = 'spectre.callsign';

  const getGreetingPrefix = (hour) => {
    if (hour < 12) return 'Good morning';
    if (hour < 18) return 'Good afternoon';
    return 'Good evening';
  };

  const sanitizeCallsign = (value) => value.replace(/[^a-zA-Z0-9\s\-_]/g, '').trim().slice(0, 30);

  const renderGreeting = () => {
    const now = new Date();
    const storedCallsign = localStorage.getItem(CALLSIGN_KEY);
    const name = storedCallsign && storedCallsign.trim().length > 0 ? storedCallsign : 'Operator';

    greetingEl.textContent = `${getGreetingPrefix(now.getHours())}, ${name}.`;
    clockEl.textContent = now.toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
    clockEl.dateTime = now.toISOString();
  };

  const applyStoredCallsign = () => {
    const value = localStorage.getItem(CALLSIGN_KEY);
    if (value && callsignInput) {
      callsignInput.value = value;
    }
  };

  if (yearEl) {
    yearEl.textContent = String(new Date().getFullYear());
  }

  if (callsignForm && callsignInput) {
    callsignForm.addEventListener('submit', (event) => {
      event.preventDefault();
      const sanitized = sanitizeCallsign(callsignInput.value);
      if (!sanitized) {
        localStorage.removeItem(CALLSIGN_KEY);
        callsignInput.value = '';
      } else {
        localStorage.setItem(CALLSIGN_KEY, sanitized);
        callsignInput.value = sanitized;
      }
      renderGreeting();
    });
  }

  if (callsignReset) {
    callsignReset.addEventListener('click', () => {
      localStorage.removeItem(CALLSIGN_KEY);
      if (callsignInput) {
        callsignInput.value = '';
      }
      renderGreeting();
    });
  }

  applyStoredCallsign();
  renderGreeting();
  setInterval(renderGreeting, 1000);
})();
