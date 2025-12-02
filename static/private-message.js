(function () {
  const POPUP_ID = 'privateMessagePopup';

  function formatTimestamp(value) {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  function dismissPopup() {
    const existing = document.getElementById(POPUP_ID);
    if (existing) {
      existing.remove();
    }
  }

  function renderPopup(messages) {
    if (!Array.isArray(messages) || !messages.length) return;
    dismissPopup();

    const popup = document.createElement('div');
    popup.className = 'private-message-popup';
    popup.id = POPUP_ID;
    popup.setAttribute('role', 'alert');
    popup.setAttribute('aria-live', 'assertive');

    const header = document.createElement('div');
    header.className = 'private-message-popup__header';

    const badge = document.createElement('span');
    badge.className = 'private-message-popup__badge';
    badge.textContent = 'PM';

    const title = document.createElement('p');
    title.className = 'private-message-popup__title';
    title.textContent = messages.length > 1 ? 'New private messages' : 'New private message';

    header.append(badge, title);

    const list = document.createElement('ul');
    list.className = 'private-message-popup__list';

    messages.forEach((entry) => {
      const li = document.createElement('li');
      li.className = 'private-message-popup__item';

      const from = document.createElement('p');
      from.className = 'private-message-popup__from';
      const sender = entry.sender || 'Operator';
      from.textContent = `From ${sender}`;

      const body = document.createElement('p');
      body.className = 'private-message-popup__body';
      body.textContent = entry.message || '';

      li.append(from, body);
      list.append(li);
    });

    const footer = document.createElement('div');
    footer.className = 'private-message-popup__footer';

    const timestamp = document.createElement('span');
    timestamp.className = 'private-message-popup__timestamp';
    timestamp.textContent = `Received ${formatTimestamp(messages[0].delivered_at || messages[0].created_at)}`;

    const closeButton = document.createElement('button');
    closeButton.type = 'button';
    closeButton.className = 'private-message-popup__close';
    closeButton.textContent = 'Dismiss';
    closeButton.addEventListener('click', dismissPopup);

    footer.append(timestamp, closeButton);

    popup.append(header, list, footer);
    document.body.append(popup);
  }

  async function checkPrivateMessages() {
    try {
      const response = await fetch('/api/alice/chat/private', { cache: 'no-store' });
      if (!response.ok) return;
      const payload = await response.json();
      const messages = Array.isArray(payload?.messages) ? payload.messages : [];
      if (!messages.length) return;
      renderPopup(messages);
    } catch (error) {
      console.error('Failed to load private messages', error);
    }
  }

  window.addEventListener('load', () => {
    setTimeout(checkPrivateMessages, 300);
  });
})();
