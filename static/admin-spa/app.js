const shell = document.getElementById("app-shell");

const state = {
  tab: "users",
  error: "",
  authStatus: "Authorizing...",
  token: "",
  tokenExpiresAt: 0,
  siteUsers: [],
  subjects: [],
  cases: [],
  sanctions: [],
  appeals: [],
  events: []
};

let tokenRequest = null;
const REQUEST_TIMEOUT_MS = 12000;

async function fetchWithTimeout(url, init = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    return await fetch(url, {
      ...init,
      signal: controller.signal
    });
  } catch (error) {
    if (error && error.name === "AbortError") {
      throw new Error("Request timed out. Please retry.");
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

async function ensureToken(forceRefresh = false) {
  const now = Date.now();
  if (!forceRefresh && state.token && now < state.tokenExpiresAt - 15000) {
    return state.token;
  }
  if (!forceRefresh && tokenRequest) {
    return tokenRequest;
  }
  tokenRequest = (async () => {
    const response = await fetchWithTimeout("/api/auth/token", {
      credentials: "same-origin"
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || !body.token) {
      state.token = "";
      state.tokenExpiresAt = 0;
      state.authStatus = "Authentication required. Open /login first.";
      throw new Error(body.detail || "No token");
    }
    state.token = String(body.token);
    state.tokenExpiresAt = now + Math.max(Number(body.expiresIn || 0), 1) * 1000;
    state.authStatus = "Authorized";
    return state.token;
  })();
  try {
    return await tokenRequest;
  } finally {
    tokenRequest = null;
  }
}

async function api(path, init = {}, allowRetry = true) {
  const token = await ensureToken();
  const response = await fetchWithTimeout(`/api/moderation${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(init.headers || {})
    }
  });
  const body = await response.json().catch(() => ({}));
  if (allowRetry && response.status === 401) {
    await ensureToken(true);
    return api(path, init, false);
  }
  if (!response.ok) {
    throw new Error(body.detail || `Request failed with ${response.status}`);
  }
  return body;
}

async function loadAll() {
  try {
    await ensureToken();
    const [subjects, siteUsers, cases, sanctions, appeals, events] = await Promise.all([
      api("/subjects"),
      api("/website-users?limit=200"),
      api("/cases"),
      api("/sanctions"),
      api("/appeals"),
      api("/audit-events?limit=100")
    ]);
    state.subjects = subjects.subjects || [];
    state.siteUsers = siteUsers.users || [];
    state.cases = cases.cases || [];
    state.sanctions = sanctions.sanctions || [];
    state.appeals = appeals.appeals || [];
    state.events = events.events || [];
    state.error = "";
  } catch (error) {
    state.error = String(error.message || error);
  }
}

function setTab(tab) {
  state.tab = tab;
  render();
}

async function onCreateSubject(event) {
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    await api("/subjects", {
      method: "POST",
      body: JSON.stringify({ canonicalLabel: String(form.get("canonicalLabel") || "") })
    });
    await loadAll();
  } catch (error) {
    state.error = String(error.message || error);
  }
  render();
}

async function onCreateCase(event) {
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    await api("/cases", {
      method: "POST",
      body: JSON.stringify({
        subjectId: String(form.get("subjectId") || ""),
        title: String(form.get("title") || ""),
        description: String(form.get("description") || ""),
        priority: String(form.get("priority") || "normal")
      })
    });
    await loadAll();
  } catch (error) {
    state.error = String(error.message || error);
  }
  render();
}

async function onCreateSanction(event) {
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    await api("/sanctions", {
      method: "POST",
      body: JSON.stringify({
        subjectId: String(form.get("subjectId") || ""),
        caseId: String(form.get("caseId") || "") || null,
        target: String(form.get("target") || "website"),
        sanction: String(form.get("sanction") || "warning"),
        reason: String(form.get("reason") || ""),
        guildId: String(form.get("guildId") || "") || null
      })
    });
    await loadAll();
  } catch (error) {
    state.error = String(error.message || error);
  }
  render();
}

async function onCreateAppeal(event) {
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    await api("/appeals", {
      method: "POST",
      body: JSON.stringify({
        sanctionId: String(form.get("sanctionId") || ""),
        caseId: String(form.get("caseId") || "") || null,
        appealReason: String(form.get("appealReason") || "")
      })
    });
    await loadAll();
  } catch (error) {
    state.error = String(error.message || error);
  }
  render();
}

function usersView() {
  return `
    <section class="panel">
      <h2>Unified User Moderation</h2>
      <p class="muted">Create and track moderated subjects across website + Discord identities, plus live website usage.</p>
      <form id="subject-form" class="row">
        <input name="canonicalLabel" placeholder="Canonical label (e.g. John Doe #1234)" required />
        <button class="primary" type="submit">Create Subject</button>
      </form>
      <table>
        <thead><tr><th>Label</th><th>Status</th><th>ID</th></tr></thead>
        <tbody>
          ${state.subjects
            .map(
              (subject) =>
                `<tr><td>${escapeHtml(subject.canonicalLabel)}</td><td>${escapeHtml(subject.status)}</td><td>${escapeHtml(subject.id)}</td></tr>`
            )
            .join("")}
        </tbody>
      </table>
      <h3 style="margin-top:1rem;">Recent Website Users</h3>
      <table>
        <thead><tr><th>User</th><th>Website ID</th><th>IP</th><th>Path</th><th>Last seen</th></tr></thead>
        <tbody>
          ${state.siteUsers
            .map(
              (visitor) =>
                `<tr>
                  <td>${escapeHtml(visitor.displayName || "Guest")}</td>
                  <td>${escapeHtml(visitor.websiteUserId || visitor.visitorId || "-")}</td>
                  <td>${escapeHtml(visitor.ip || "Unknown")}</td>
                  <td>${escapeHtml(visitor.path || "/")}</td>
                  <td>${escapeHtml(visitor.lastSeenLabel || "")}</td>
                </tr>`
            )
            .join("")}
        </tbody>
      </table>
    </section>
  `;
}

function casesView() {
  return `
    <section class="panel">
      <h2>Case Management</h2>
      <form id="case-form">
        <div class="row">
          <input name="subjectId" placeholder="Subject ID" required />
          <input name="title" placeholder="Case title" required />
        </div>
        <div class="row">
          <select name="priority" class="small">
            <option value="low">Low</option>
            <option value="normal" selected>Normal</option>
            <option value="high">High</option>
            <option value="critical">Critical</option>
          </select>
          <input name="description" placeholder="Case description" required />
          <button class="primary" type="submit">Open Case</button>
        </div>
      </form>
      <table>
        <thead><tr><th>Title</th><th>Subject</th><th>Priority</th><th>Status</th></tr></thead>
        <tbody>
          ${state.cases
            .map(
              (item) =>
                `<tr><td>${escapeHtml(item.title)}</td><td>${escapeHtml(item.subjectId)}</td><td>${escapeHtml(item.priority)}</td><td>${escapeHtml(item.status)}</td></tr>`
            )
            .join("")}
        </tbody>
      </table>
    </section>
  `;
}

function sanctionsView() {
  return `
    <section class="panel">
      <h2>Enforcement Actions</h2>
      <p class="muted">Website and Discord enforcement with action receipts.</p>
      <form id="sanction-form">
        <div class="row">
          <input name="subjectId" placeholder="Subject ID" required />
          <input name="caseId" placeholder="Case ID (optional)" />
          <select name="target" class="small">
            <option value="website">Website</option>
            <option value="discord">Discord</option>
          </select>
          <select name="sanction" class="small">
            <option value="warning">Warning</option>
            <option value="read_only">Read-only</option>
            <option value="quarantine">Quarantine</option>
            <option value="timeout">Timeout</option>
            <option value="kick">Kick</option>
            <option value="ban">Ban</option>
          </select>
        </div>
        <div class="row">
          <input name="guildId" placeholder="Discord guild ID (required for Discord target)" />
          <input name="reason" placeholder="Reason" required />
          <button class="danger" type="submit">Apply Sanction</button>
        </div>
      </form>
      <table>
        <thead><tr><th>Target</th><th>Type</th><th>Status</th><th>Reason</th></tr></thead>
        <tbody>
          ${state.sanctions
            .map(
              (item) =>
                `<tr><td>${escapeHtml(item.target)}</td><td>${escapeHtml(item.sanction)}</td><td>${escapeHtml(item.status)}</td><td>${escapeHtml(item.reason)}</td></tr>`
            )
            .join("")}
        </tbody>
      </table>
    </section>
  `;
}

function appealsView() {
  return `
    <section class="panel">
      <h2>Appeals</h2>
      <form id="appeal-form">
        <div class="row">
          <input name="sanctionId" placeholder="Sanction ID" required />
          <input name="caseId" placeholder="Case ID (optional)" />
        </div>
        <div class="row">
          <textarea name="appealReason" placeholder="Appeal reason" required></textarea>
          <button class="primary" type="submit">Submit Appeal</button>
        </div>
      </form>
      <table>
        <thead><tr><th>Status</th><th>Sanction ID</th><th>Reason</th></tr></thead>
        <tbody>
          ${state.appeals
            .map(
              (appeal) =>
                `<tr><td>${escapeHtml(appeal.status)}</td><td>${escapeHtml(appeal.sanctionId)}</td><td>${escapeHtml(appeal.appealReason)}</td></tr>`
            )
            .join("")}
        </tbody>
      </table>
    </section>
  `;
}

function auditView() {
  return `
    <section class="panel">
      <h2>Audit Timeline</h2>
      <table>
        <thead><tr><th>Time</th><th>Type</th><th>Source</th></tr></thead>
        <tbody>
          ${state.events
            .map(
              (event) =>
                `<tr><td>${escapeHtml(new Date(event.occurredAt).toLocaleString())}</td><td>${escapeHtml(event.eventType)}</td><td>${escapeHtml(event.source)}</td></tr>`
            )
            .join("")}
        </tbody>
      </table>
    </section>
  `;
}

function viewForTab() {
  if (state.tab === "cases") {
    return casesView();
  }
  if (state.tab === "sanctions") {
    return sanctionsView();
  }
  if (state.tab === "appeals") {
    return appealsView();
  }
  if (state.tab === "audit") {
    return auditView();
  }
  return usersView();
}

function render() {
  const brand = shell.dataset.brand || "Spectre";
  shell.innerHTML = `
    <div class="shell">
      <header class="top">
        <div>
          <h1>${escapeHtml(brand)} Admin Moderation Platform</h1>
          <p class="muted">Cross-platform moderation command center for users, cases, sanctions, appeals, and audit.</p>
          <p class="muted">Auth: ${escapeHtml(state.authStatus)}</p>
        </div>
        <a href="/admin/legacy" class="muted">Open legacy admin</a>
      </header>
      <div class="tabs">
        ${renderTab("users", "Users")}
        ${renderTab("cases", "Cases")}
        ${renderTab("sanctions", "Sanctions")}
        ${renderTab("appeals", "Appeals")}
        ${renderTab("audit", "Audit")}
      </div>
      ${state.error ? `<p class="error">${escapeHtml(state.error)}</p>` : ""}
      ${viewForTab()}
    </div>
  `;
  bindEvents();
}

function renderTab(tab, label) {
  const active = state.tab === tab ? "active" : "";
  return `<button type="button" data-tab="${tab}" class="${active}">${label}</button>`;
}

function bindEvents() {
  document.querySelectorAll("[data-tab]").forEach((element) => {
    element.addEventListener("click", () => setTab(element.getAttribute("data-tab")));
  });
  const subjectForm = document.getElementById("subject-form");
  if (subjectForm) {
    subjectForm.addEventListener("submit", onCreateSubject);
  }
  const caseForm = document.getElementById("case-form");
  if (caseForm) {
    caseForm.addEventListener("submit", onCreateCase);
  }
  const sanctionForm = document.getElementById("sanction-form");
  if (sanctionForm) {
    sanctionForm.addEventListener("submit", onCreateSanction);
  }
  const appealForm = document.getElementById("appeal-form");
  if (appealForm) {
    appealForm.addEventListener("submit", onCreateAppeal);
  }
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

render();
loadAll().finally(() => {
  render();
});
