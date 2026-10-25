// Admin console: section navigation and the moderation workspace.
const config = JSON.parse(document.getElementById("console-config")?.textContent || "{}");
const SECTIONS = ["overview", "people", "cases", "sanctions", "appeals", "servers", "audit", "site", "tools", "system"];
const NEEDS_SERVER = new Set(["read_only", "quarantine", "timeout", "kick", "ban"]);
const OPEN_CASE = new Set(["open", "investigating"]);
const PENDING_APPEAL = new Set(["submitted", "under_review"]);
const REQUEST_TIMEOUT_MS = 15000;

const state = {
  rules: { discord: [], website: [] },
  caseStatuses: [],
  people: [],
  cases: [],
  sanctions: [],
  appeals: [],
  audit: [],
  selectedPerson: null,
  profile: null,
  filters: { cases: "active", sanctions: "active" },
  loaded: false,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

const dateFormat = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
function when(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : dateFormat.format(date);
}
function ago(iso) {
  const date = new Date(iso);
  if (!iso || Number.isNaN(date.getTime())) return "";
  const minutes = Math.round((Date.now() - date.getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

// ---------------------------------------------------------------- navigation
function route() {
  const id = SECTIONS.includes(location.hash.slice(1)) ? location.hash.slice(1) : "overview";
  $$(".section").forEach((section) => section.classList.toggle("is-visible", section.id === id));
  $$("[data-nav]").forEach((link) => {
    const active = link.dataset.nav === id;
    link.classList.toggle("is-active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  $("#sidebar")?.classList.remove("is-open");
  $(".nav-toggle")?.setAttribute("aria-expanded", "false");
  window.scrollTo({ top: 0 });
}
window.addEventListener("hashchange", route);
route();

$(".nav-toggle")?.addEventListener("click", (event) => {
  const open = $("#sidebar").classList.toggle("is-open");
  event.currentTarget.setAttribute("aria-expanded", String(open));
});

document.addEventListener("click", (event) => {
  const toggle = event.target.closest("[data-toggle]");
  if (toggle) {
    const target = document.getElementById(toggle.dataset.toggle);
    if (target) {
      target.hidden = !target.hidden;
      if (!target.hidden) target.querySelector("input, select, textarea")?.focus();
    }
  }
  const intent = event.target.closest("[data-intent]");
  if (intent) {
    const form = intent.dataset.intent === "new-person" ? "person-form" : "case-form";
    setTimeout(() => {
      const target = document.getElementById(form);
      if (target) {
        target.hidden = false;
        target.querySelector("input, select")?.focus();
      }
    });
  }
});

document.addEventListener("submit", (event) => {
  const message = event.submitter?.dataset.confirm;
  if (message && !window.confirm(message)) event.preventDefault();
});

// --------------------------------------------------------------- feedback UI
let toastTimer = null;
function toast(message, isError = false) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.toggle("is-error", isError);
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.hidden = true; }, isError ? 8000 : 4000);
}

function ask({ title, label, placeholder = "", confirm = "Confirm", required = true, danger = false }) {
  return new Promise((resolve) => {
    const dialog = document.createElement("dialog");
    dialog.className = "panel";
    dialog.innerHTML = `
      <form method="dialog">
        <h2>${esc(title)}</h2>
        <label>${esc(label)}<textarea name="text" rows="3" ${required ? "required minlength=\"3\"" : ""} placeholder="${esc(placeholder)}"></textarea></label>
        <div class="actions">
          <button class="btn ${danger ? "btn--danger" : "btn--primary"}" value="ok">${esc(confirm)}</button>
          <button class="btn" value="cancel" formnovalidate>Cancel</button>
        </div>
      </form>`;
    document.body.append(dialog);
    dialog.addEventListener("close", () => {
      const text = dialog.querySelector("textarea").value.trim();
      resolve(dialog.returnValue === "ok" ? text : null);
      dialog.remove();
    });
    dialog.showModal();
  });
}

// ----------------------------------------------------------------------- API
let token = "";
let tokenExpiresAt = 0;

async function fetchWithTimeout(url, init = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    return await fetch(url, { credentials: "same-origin", ...init, signal: controller.signal });
  } catch (error) {
    throw new Error(error?.name === "AbortError" ? "The server took too long to respond." : "Could not reach the server.");
  } finally {
    clearTimeout(timer);
  }
}

async function ensureToken(force = false) {
  if (!force && token && Date.now() < tokenExpiresAt - 15000) return token;
  const response = await fetchWithTimeout("/api/auth/token");
  const body = await response.json().catch(() => ({}));
  if (!response.ok || !body.token) {
    throw new Error(response.status === 401 ? "Your session expired. Reload the page to sign in again." : "Could not authorise the moderation tools.");
  }
  token = body.token;
  tokenExpiresAt = Date.now() + Math.max(Number(body.expiresIn) || 60, 60) * 1000;
  return token;
}

async function api(path, { method = "GET", body, retry = true } = {}) {
  const bearer = await ensureToken();
  const response = await fetchWithTimeout(`/api/moderation${path}`, {
    method,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${bearer}` },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 401 && retry) {
    await ensureToken(true);
    return api(path, { method, body, retry: false });
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map((item) => item.msg).join("; ") : data.detail;
    throw new Error(detail || `The server returned an error (${response.status}).`);
  }
  return data;
}

// ------------------------------------------------------------------- lookups
const personById = (id) => state.people.find((person) => person.id === id);
const personName = (id) => personById(id)?.canonicalLabel || "Unknown person";
const caseById = (id) => state.cases.find((item) => item.id === id);
const sanctionById = (id) => state.sanctions.find((item) => item.id === id);
const platformLabel = (target) => (target === "website" ? "Website" : "Discord");

function actionLabel(target, action) {
  const rule = (state.rules[target] || []).find((item) => item.value === action);
  return rule?.label || action.replace(/_/g, " ");
}

function sanctionState(sanction) {
  if (sanction.status === "active" && sanction.endsAt && new Date(sanction.endsAt) <= new Date()) return "expired";
  return sanction.status;
}
const isInEffect = (sanction) => sanctionState(sanction) === "active";
const SANCTION_TONES = { active: "bad", completed: "muted", expired: "muted", revoked: "ok", failed: "warn", pending: "warn" };
const SANCTION_WORDS = { active: "In effect", completed: "Done", expired: "Expired", revoked: "Lifted", failed: "Failed", pending: "Pending" };
function sanctionPill(sanction) {
  const key = sanctionState(sanction);
  return `<span class="pill tone-${SANCTION_TONES[key] || "muted"}">${esc(SANCTION_WORDS[key] || key)}</span>`;
}
const PRIORITY_TONES = { critical: "bad", high: "warn", normal: "muted", low: "muted" };
const priorityPill = (priority) => `<span class="pill tone-${PRIORITY_TONES[priority] || "muted"}">${esc(priority)}</span>`;

function sanctionEffect(target, action) {
  const rule = (state.rules[target] || []).find((item) => item.value === action);
  const hours = rule?.duration ? Math.round(rule.duration / 3600) : 0;
  const span = hours >= 48 ? `${Math.round(hours / 24)} days` : `${hours} hour${hours === 1 ? "" : "s"}`;
  if (action === "note") return "Only recorded here. Nothing is sent to them.";
  if (target === "website") {
    if (action === "warning") return "Recorded here. The website has no way to notify them, so tell them on Discord if needed.";
    if (action === "ban") return "Signs them out and blocks them from the website until you lift it.";
    return `Signs them out and blocks them from the website for ${span}.`;
  }
  if (action === "warning") return "Sends them a direct message from the bot with your reason.";
  if (action === "kick") return "Removes them from the server. They can rejoin with an invite.";
  if (action === "ban") return "Bans them from the server until you lift it.";
  return `Times them out in the server for ${span}: they can read but not talk or react.`;
}

// ----------------------------------------------------------------- rendering
function setCount(name, value) {
  $$(`[data-count="${name}"]`).forEach((node) => { node.textContent = value ? String(value) : ""; });
  $$(`[data-stat="${name}"]`).forEach((node) => { node.textContent = String(value); });
}

function renderCounts() {
  const openCases = state.cases.filter((item) => OPEN_CASE.has(item.status));
  const pendingAppeals = state.appeals.filter((item) => PENDING_APPEAL.has(item.status));
  setCount("people", state.people.length);
  setCount("open-cases", openCases.length);
  setCount("active-sanctions", state.sanctions.filter(isInEffect).length);
  setCount("pending-appeals", pendingAppeals.length);

  const items = [
    ...pendingAppeals.map((appeal) => {
      const sanction = sanctionById(appeal.sanctionId);
      return `<li><a href="#appeals"><span class="pill tone-warn">Appeal</span><span class="grow">${esc(personName(sanction?.subjectId))}: ${esc(appeal.appealReason)}</span><span class="muted">${esc(ago(appeal.submittedAt))}</span></a></li>`;
    }),
    ...openCases
      .filter((item) => item.priority === "critical" || item.priority === "high")
      .map((item) => `<li><a href="#cases">${priorityPill(item.priority)}<span class="grow">${esc(item.title)} · ${esc(personName(item.subjectId))}</span><span class="muted">${esc(ago(item.openedAt))}</span></a></li>`),
    ...state.sanctions
      .filter((item) => item.status === "failed")
      .slice(0, 3)
      .map((item) => `<li><a href="#sanctions"><span class="pill tone-warn">Failed</span><span class="grow">${esc(actionLabel(item.target, item.sanction))} · ${esc(personName(item.subjectId))}</span><span class="muted">${esc(ago(item.startsAt))}</span></a></li>`),
  ];
  $("#attention-list").innerHTML = items.length ? items.join("") : '<li class="empty">Nothing is waiting on you.</li>';
}

function renderPeopleSelects() {
  const options = state.people
    .map((person) => `<option value="${esc(person.id)}">${esc(person.canonicalLabel)}${person.discordUserId ? ` (${esc(person.discordUserId)})` : ""}</option>`)
    .join("");
  $$("[data-people-select]").forEach((select) => {
    const current = select.value;
    select.innerHTML = `<option value="">Choose a person…</option>${options}`;
    if (current) select.value = current;
  });
}

function renderPeople() {
  const query = ($("#people-search")?.value || "").trim().toLowerCase();
  const matches = state.people.filter((person) =>
    !query || person.canonicalLabel.toLowerCase().includes(query) || String(person.discordUserId || "").includes(query));
  const list = $("#people-list");
  if (!state.people.length) {
    list.innerHTML = '<p class="empty">No one is tracked yet. Use <strong>Add person</strong> to start a record.</p>';
    return;
  }
  if (!matches.length) {
    list.innerHTML = '<p class="empty">No one matches that search.</p>';
    return;
  }
  list.innerHTML = matches.map((person) => {
    const active = state.sanctions.filter((item) => item.subjectId === person.id && isInEffect(item)).length;
    return `<button type="button" class="list-item${person.id === state.selectedPerson ? " is-selected" : ""}" data-person="${esc(person.id)}">
      <span class="name">${esc(person.canonicalLabel)}${active ? `<span class="pill tone-bad">${active} active</span>` : ""}</span>
      <span class="sub">${person.discordUserId ? `Discord ${esc(person.discordUserId)}` : "No Discord account linked"}</span>
    </button>`;
  }).join("");
}

function sanctionRows(sanctions, { showPerson = true } = {}) {
  if (!sanctions.length) return "";
  return sanctions.map((item) => {
    const appealOpen = state.appeals.some((appeal) => appeal.sanctionId === item.id && PENDING_APPEAL.has(appeal.status));
    const server = item.metadata?.guildName || item.metadata?.guildId;
    const error = item.status === "failed" ? (item.metadata?.error || item.error) : "";
    const actions = [
      isInEffect(item) ? `<button type="button" class="btn btn--small" data-revoke="${esc(item.id)}">Lift</button>` : "",
      isInEffect(item) && !appealOpen ? `<button type="button" class="btn btn--small" data-appeal="${esc(item.id)}">Log appeal</button>` : "",
    ].join("");
    return `<tr>
      ${showPerson ? `<td><a class="link" href="#people" data-open-person="${esc(item.subjectId)}">${esc(personName(item.subjectId))}</a></td>` : ""}
      <td>${esc(actionLabel(item.target, item.sanction))}<div class="muted">${esc(platformLabel(item.target))}${server ? ` · ${esc(server)}` : ""}</div></td>
      <td>${sanctionPill(item)}${item.endsAt && isInEffect(item) ? `<div class="muted">until ${esc(when(item.endsAt))}</div>` : ""}</td>
      <td class="reason">${esc(item.reason)}${error ? `<div class="error-text">${esc(error)}</div>` : ""}${item.revokeReason ? `<div class="muted">Lifted: ${esc(item.revokeReason)}</div>` : ""}</td>
      <td class="muted nowrap">${esc(when(item.startsAt))}<br>${esc(item.metadata?.actor?.name || "")}</td>
      <td><div class="row-actions">${actions}</div></td>
    </tr>`;
  }).join("");
}

function renderSanctions() {
  const filter = state.filters.sanctions;
  const rows = state.sanctions.filter((item) =>
    filter === "all" ? true : filter === "failed" ? item.status === "failed" : isInEffect(item));
  const empty = { active: "No sanctions are in effect.", failed: "No failed sanctions.", all: "No sanctions yet." }[filter];
  $("#sanctions-table").innerHTML = `
    <thead><tr><th>Person</th><th>Sanction</th><th>Status</th><th>Reason</th><th>Applied</th><th></th></tr></thead>
    <tbody>${sanctionRows(rows) || `<tr><td colspan="6" class="empty">${empty}</td></tr>`}</tbody>`;
}

function caseStatusSelect(item) {
  const options = state.caseStatuses
    .map((status) => `<option value="${esc(status)}"${status === item.status ? " selected" : ""}>${esc(status)}</option>`)
    .join("");
  return `<select data-case-status="${esc(item.id)}" aria-label="Case status">${options}</select>`;
}

function renderCases() {
  const filter = state.filters.cases;
  const rows = state.cases.filter((item) =>
    filter === "all" ? true : filter === "closed" ? !OPEN_CASE.has(item.status) : OPEN_CASE.has(item.status));
  const empty = { active: "No open cases.", closed: "No closed cases yet.", all: "No cases yet." }[filter];
  $("#cases-table").innerHTML = `
    <thead><tr><th>Case</th><th>Person</th><th>Priority</th><th>Status</th><th>Opened</th></tr></thead>
    <tbody>${rows.map((item) => `<tr>
      <td><strong>${esc(item.title)}</strong><div class="muted reason">${esc(item.description)}</div></td>
      <td><a class="link" href="#people" data-open-person="${esc(item.subjectId)}">${esc(personName(item.subjectId))}</a></td>
      <td>${priorityPill(item.priority)}</td>
      <td>${caseStatusSelect(item)}</td>
      <td class="muted nowrap">${esc(when(item.openedAt))}<br>${esc(item.metadata?.actor?.name || "")}</td>
    </tr>`).join("") || `<tr><td colspan="5" class="empty">${empty}</td></tr>`}</tbody>`;
}

function renderAppeals() {
  const pending = state.appeals.filter((item) => PENDING_APPEAL.has(item.status));
  const decided = state.appeals.filter((item) => !PENDING_APPEAL.has(item.status));
  const card = (appeal) => {
    const sanction = sanctionById(appeal.sanctionId);
    const summary = sanction ? `${actionLabel(sanction.target, sanction.sanction)} · ${platformLabel(sanction.target)}` : "Sanction";
    const open = PENDING_APPEAL.has(appeal.status);
    return `<article class="panel appeal-card">
      <div class="panel-head">
        <h2>${esc(personName(sanction?.subjectId))}</h2>
        <span class="pill tone-${open ? "warn" : appeal.status === "approved" ? "ok" : "muted"}">${esc(appeal.status.replace("_", " "))}</span>
      </div>
      <p class="muted">${esc(summary)} · originally for “${esc(sanction?.reason || "")}”</p>
      <p class="reason">${esc(appeal.appealReason)}</p>
      ${appeal.decisionSummary ? `<p class="muted">Decision: ${esc(appeal.decisionSummary)}</p>` : ""}
      <p class="muted">Submitted ${esc(when(appeal.submittedAt))}${appeal.decidedAt ? ` · decided ${esc(when(appeal.decidedAt))}` : ""}</p>
      ${open ? `<div class="actions">
        <button type="button" class="btn btn--primary" data-decide="${esc(appeal.id)}" data-decision="approved">Approve and lift sanction</button>
        <button type="button" class="btn" data-decide="${esc(appeal.id)}" data-decision="denied">Deny</button>
      </div>` : ""}
    </article>`;
  };
  $("#appeals-list").innerHTML = `
    ${pending.length ? pending.map(card).join("") : '<p class="empty">No appeals are waiting. Log one from a sanction when someone asks for it to be lifted.</p>'}
    ${decided.length ? `<h3 class="sub-head">Decided</h3>${decided.map(card).join("")}` : ""}`;
}

function describeEvent(event) {
  const meta = event.metadata || {};
  const label = (target, action) => actionLabel(target || "discord", action || "");
  switch (event.eventType) {
    case "subject.created": return `Added ${esc(meta.canonicalLabel || "a person")}`;
    case "identity.linked": return `Linked ${esc(meta.provider)} account <code>${esc(meta.providerUserId)}</code>`;
    case "case.created": return `Opened case “${esc(meta.title || "")}” (${esc(meta.priority || "normal")})`;
    case "case.status_changed": return `Set a case to <strong>${esc(meta.status)}</strong>${meta.note ? `: ${esc(meta.note)}` : ""}`;
    case "sanction.imposed": return `${esc(label(meta.target, meta.sanction))} on ${esc(platformLabel(meta.target))} · ${esc(meta.status)}${meta.error ? ` <span class="error-text">${esc(meta.error)}</span>` : ""}`;
    case "sanction.revoked": return `Lifted ${esc(label(meta.target, meta.sanction).toLowerCase())}: ${esc(meta.reason || "")}`;
    case "appeal.submitted": return "Logged an appeal";
    case "appeal.decided": return `${meta.status === "approved" ? "Approved" : meta.status === "denied" ? "Denied" : "Updated"} an appeal${meta.sanctionLifted ? " and lifted the sanction" : ""}`;
    default: return esc(event.eventType);
  }
}

function renderAudit() {
  $("#audit-table").innerHTML = `
    <thead><tr><th>When</th><th>Who</th><th>What</th><th>Person</th></tr></thead>
    <tbody>${state.audit.map((event) => `<tr>
      <td class="muted nowrap" title="${esc(event.occurredAt)}">${esc(when(event.occurredAt))}</td>
      <td>${esc(event.metadata?.actor?.name || event.metadata?.actor?.id || "System")}</td>
      <td>${describeEvent(event)}</td>
      <td>${event.subjectId ? `<a class="link" href="#people" data-open-person="${esc(event.subjectId)}">${esc(personName(event.subjectId))}</a>` : ""}</td>
    </tr>`).join("") || '<tr><td colspan="4" class="empty">Nothing has been recorded yet.</td></tr>'}</tbody>`;
}

function serverOptions() {
  return (config.discordServers || [])
    .map((guild) => `<option value="${esc(guild.id)}">${esc(guild.name)}</option>`)
    .join("");
}

function renderPersonDetail() {
  const node = $("#person-detail");
  const profile = state.profile;
  if (!state.selectedPerson || !profile) {
    node.innerHTML = '<p class="empty">Select a person to see their history and take action.</p>';
    return;
  }
  const person = profile.subject;
  const identities = profile.identities || [];
  const hasDiscord = identities.some((identity) => identity.provider === "discord");
  const sanctions = state.sanctions.filter((item) => item.subjectId === person.id);
  const cases = state.cases.filter((item) => item.subjectId === person.id);
  const caseOptions = cases.map((item) => `<option value="${esc(item.id)}">${esc(item.title)}</option>`).join("");
  const servers = serverOptions();

  node.innerHTML = `
    <div class="detail-head">
      <h2>${esc(person.canonicalLabel)}</h2>
      <div class="row-actions">
        <button type="button" class="btn btn--primary" data-toggle="sanction-form">Apply sanction</button>
        <button type="button" class="btn" data-toggle="person-case-form">Open case</button>
      </div>
    </div>
    <p class="muted">Tracked since ${esc(when(person.createdAt))}</p>

    <h3 class="sub-head">Accounts</h3>
    ${identities.length ? `<ul class="identity-list">${identities.map((identity) => `
      <li><span class="provider">${esc(identity.provider)}</span><code>${esc(identity.providerUserId)}</code><span class="muted">${esc(identity.displayName || "")}</span></li>`).join("")}</ul>`
      : '<p class="effect is-warning">No accounts linked. Link their Discord account so sanctions can reach them.</p>'}
    <form class="inline-form" id="identity-form" ${identities.length ? "hidden" : ""}>
      <h3>Link an account</h3>
      <div class="form-grid">
        <label>Platform<select name="provider"><option value="discord">Discord</option><option value="website">Website-only account</option></select></label>
        <label>User ID<input name="providerUserId" required placeholder="e.g. 1059522006602752150"></label>
      </div>
      <div class="actions"><button class="btn btn--primary" type="submit">Link account</button></div>
    </form>
    ${identities.length ? '<div class="actions"><button type="button" class="btn btn--small" data-toggle="identity-form">Link another account</button></div>' : ""}

    <form class="inline-form" id="sanction-form" hidden>
      <h3>Apply a sanction</h3>
      <fieldset class="radio-field">
        <legend>Where</legend>
        <span class="radio-row">
          <label><input type="radio" name="target" value="discord" checked> Discord</label>
          <label><input type="radio" name="target" value="website"> Website</label>
        </span>
      </fieldset>
      <div class="form-grid">
        <label>Action<select name="sanction"></select></label>
        <label data-server-field>Server
          <select name="guildId">${servers ? `<option value="">Choose a server…</option>${servers}` : '<option value="">No servers available</option>'}</select>
        </label>
        <label class="span-2"><span>Reason <span class="optional">they see this for warnings</span></span><textarea name="reason" rows="3" required minlength="3" maxlength="2000" placeholder="Which rule, and what they did"></textarea></label>
        ${cases.length ? `<label class="span-2"><span>Related case <span class="optional">optional</span></span><select name="caseId"><option value="">None</option>${caseOptions}</select></label>` : ""}
      </div>
      <p class="effect" data-effect></p>
      ${hasDiscord ? "" : '<p class="effect is-warning">This person has no linked Discord account, so only notes can be recorded until you link one.</p>'}
      ${servers ? "" : '<p class="effect is-warning">The bot\'s server list is unavailable (no bot token, or Discord is unreachable), so Discord mutes, kicks and bans can\'t be applied right now.</p>'}
      <div class="actions"><button class="btn btn--danger" type="submit">Apply sanction</button><button class="btn" type="button" data-toggle="sanction-form">Cancel</button></div>
    </form>

    <form class="inline-form" id="person-case-form" hidden>
      <h3>Open a case</h3>
      <div class="form-grid">
        <label class="span-2">Title<input name="title" required minlength="3" maxlength="200"></label>
        <label>Priority<select name="priority"><option value="low">Low</option><option value="normal" selected>Normal</option><option value="high">High</option><option value="critical">Critical</option></select></label>
        <label class="span-2">Details<textarea name="description" rows="3" required minlength="5" maxlength="5000"></textarea></label>
      </div>
      <div class="actions"><button class="btn btn--primary" type="submit">Open case</button><button class="btn" type="button" data-toggle="person-case-form">Cancel</button></div>
    </form>

    <h3 class="sub-head">Sanctions</h3>
    ${sanctions.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Sanction</th><th>Status</th><th>Reason</th><th>Applied</th><th></th></tr></thead><tbody>${sanctionRows(sanctions, { showPerson: false })}</tbody></table></div>` : '<p class="empty">No sanctions.</p>'}

    <h3 class="sub-head">Cases</h3>
    ${cases.length ? `<ul class="attention">${cases.map((item) => `<li><a href="#cases">${priorityPill(item.priority)}<span class="grow">${esc(item.title)}</span><span class="muted">${esc(item.status)}</span></a></li>`).join("")}</ul>` : '<p class="empty">No cases.</p>'}
  `;
  syncSanctionForm();
}

function syncSanctionForm() {
  const form = $("#sanction-form");
  if (!form) return;
  const target = form.querySelector("input[name=target]:checked").value;
  const select = form.elements.sanction;
  const previous = select.value;
  select.innerHTML = (state.rules[target] || [])
    .map((rule) => `<option value="${esc(rule.value)}">${esc(rule.label)}</option>`)
    .join("");
  if ([...select.options].some((option) => option.value === previous)) select.value = previous;
  const needsServer = target === "discord" && NEEDS_SERVER.has(select.value);
  form.querySelector("[data-server-field]").hidden = !needsServer;
  form.elements.guildId.required = needsServer;
  form.querySelector("[data-effect]").textContent = sanctionEffect(target, select.value);
}

function renderAll() {
  renderCounts();
  renderPeopleSelects();
  renderPeople();
  renderCases();
  renderSanctions();
  renderAppeals();
  renderAudit();
  renderPersonDetail();
}

// ------------------------------------------------------------------- loading
function showBanner(message) {
  const banner = $("#api-banner");
  if (!message) {
    banner.hidden = true;
    return;
  }
  banner.innerHTML = `<strong>Moderation tools are unavailable.</strong> ${esc(message)} <button type="button" class="btn btn--small" id="retry-load">Try again</button>`;
  banner.hidden = false;
}

async function loadAll() {
  try {
    const [rules, people, cases, sanctions, appeals, audit] = await Promise.all([
      api("/actions"),
      api("/subjects"),
      api("/cases"),
      api("/sanctions"),
      api("/appeals"),
      api("/audit-events?limit=200"),
    ]);
    state.rules = rules.actions || state.rules;
    state.caseStatuses = rules.caseStatuses || [];
    state.people = people.subjects || [];
    state.cases = cases.cases || [];
    state.sanctions = sanctions.sanctions || [];
    state.appeals = appeals.appeals || [];
    state.audit = audit.events || [];
    state.loaded = true;
    showBanner("");
  } catch (error) {
    showBanner(error.message);
    $("#attention-list").innerHTML = '<li class="empty">Unavailable until the moderation tools load.</li>';
    return;
  }
  if (state.selectedPerson) await loadProfile(state.selectedPerson, { render: false });
  renderAll();
}

async function loadProfile(id, { render = true } = {}) {
  try {
    state.profile = await api(`/subjects/${encodeURIComponent(id)}`);
    state.selectedPerson = id;
  } catch (error) {
    state.profile = null;
    state.selectedPerson = null;
    toast(error.message, true);
  }
  if (render) {
    renderPeople();
    renderPersonDetail();
    // On narrow screens the profile sits below the list.
    if (state.profile && window.matchMedia("(max-width: 900px)").matches) {
      $("#person-detail").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }
}

async function run(action, success) {
  try {
    const result = await action();
    await loadAll();
    if (success) toast(typeof success === "function" ? success(result) : success);
    return result;
  } catch (error) {
    toast(error.message, true);
    return null;
  }
}

// ------------------------------------------------------------------- actions
document.addEventListener("click", async (event) => {
  const target = event.target;
  if (target.closest("#retry-load")) return loadAll();

  const personButton = target.closest("[data-person]");
  if (personButton) return loadProfile(personButton.dataset.person);

  const openPerson = target.closest("[data-open-person]");
  if (openPerson) {
    loadProfile(openPerson.dataset.openPerson);
    return;
  }

  const filter = target.closest("[data-filter]");
  if (filter) {
    const group = filter.closest("[data-filter-group]");
    $$("[data-filter]", group).forEach((chip) => chip.classList.toggle("is-active", chip === filter));
    state.filters[group.dataset.filterGroup] = filter.dataset.filter;
    return group.dataset.filterGroup === "cases" ? renderCases() : renderSanctions();
  }

  const revoke = target.closest("[data-revoke]");
  if (revoke) {
    const sanction = sanctionById(revoke.dataset.revoke);
    const reason = await ask({
      title: `Lift ${actionLabel(sanction.target, sanction.sanction).toLowerCase()}`,
      label: "Why are you lifting it?",
      placeholder: "e.g. Served their time, or it was a mistake",
      confirm: "Lift sanction",
    });
    if (reason) await run(() => api(`/sanctions/${sanction.id}/revoke`, { method: "POST", body: { reason } }), "Sanction lifted.");
    return;
  }

  const appeal = target.closest("[data-appeal]");
  if (appeal) {
    const reason = await ask({
      title: "Log an appeal",
      label: "What did they say?",
      placeholder: "Paste or summarise their appeal",
      confirm: "Log appeal",
    });
    if (reason && reason.length >= 5) {
      await run(() => api("/appeals", { method: "POST", body: { sanctionId: appeal.dataset.appeal, appealReason: reason } }), "Appeal logged. Decide it under Appeals.");
    } else if (reason) {
      toast("Appeals need at least a short sentence.", true);
    }
    return;
  }

  const decide = target.closest("[data-decide]");
  if (decide) {
    const approve = decide.dataset.decision === "approved";
    const note = await ask({
      title: approve ? "Approve appeal" : "Deny appeal",
      label: approve ? "Note for the record (optional)" : "Why is it denied? (optional)",
      confirm: approve ? "Approve and lift" : "Deny appeal",
      required: false,
    });
    if (note === null) return;
    await run(
      () => api(`/appeals/${decide.dataset.decide}`, { method: "PATCH", body: { status: decide.dataset.decision, decisionSummary: note || null } }),
      (result) => (result.appeal?.sanctionLifted ? "Appeal approved and sanction lifted." : approve ? "Appeal approved." : "Appeal denied."),
    );
  }
});

document.addEventListener("change", async (event) => {
  if (event.target.closest("#sanction-form")) {
    syncSanctionForm();
    return;
  }
  const select = event.target.closest("[data-case-status]");
  if (select) {
    await run(() => api(`/cases/${select.dataset.caseStatus}`, { method: "PATCH", body: { status: select.value } }), `Case set to ${select.value}.`);
  }
});

$("#people-search")?.addEventListener("input", renderPeople);

document.addEventListener("submit", async (event) => {
  const form = event.target;
  const data = Object.fromEntries(new FormData(form).entries());
  const handlers = {
    "person-form": async () => {
      const result = await run(
        () => api("/subjects", { method: "POST", body: { canonicalLabel: data.canonicalLabel, discordUserId: data.discordUserId || null } }),
        `${data.canonicalLabel} added.`,
      );
      if (result) {
        form.reset();
        form.hidden = true;
        await loadProfile(result.subject.id);
      }
    },
    "case-form": async () => {
      const result = await run(() => api("/cases", { method: "POST", body: data }), "Case opened.");
      if (result) {
        form.reset();
        form.hidden = true;
      }
    },
    "person-case-form": () => run(
      () => api("/cases", { method: "POST", body: { ...data, subjectId: state.selectedPerson } }),
      "Case opened.",
    ),
    "identity-form": () => run(
      () => api(`/subjects/${state.selectedPerson}/identities`, { method: "POST", body: data }),
      "Account linked.",
    ),
    "sanction-form": () => {
      const guild = (config.discordServers || []).find((item) => item.id === data.guildId);
      const body = { ...data, subjectId: state.selectedPerson, caseId: data.caseId || null, guildId: data.guildId || null, guildName: guild?.name || null };
      return run(
        () => api("/sanctions", { method: "POST", body }),
        (result) => (result.sanction.status === "failed" ? `Saved, but it failed: ${result.sanction.error}` : "Sanction applied."),
      );
    },
  };
  const handler = handlers[form.id];
  if (!handler) return;
  event.preventDefault();
  const button = event.submitter;
  if (button) button.disabled = true;
  try {
    await handler();
  } finally {
    if (button) button.disabled = false;
  }
});

// ------------------------------------------------------------- system tools
$("#copy-curl")?.addEventListener("click", async (event) => {
  const guild = $("#curl-guild").value || "<GUILD_ID>";
  const payload = event.currentTarget.dataset.payload;
  const command = `curl -u USER:PASS -H "Content-Type: application/json" -X PUT -d '${payload}' ${location.origin}/configs/${guild}`;
  const status = $("#copy-curl-status");
  try {
    await navigator.clipboard.writeText(command);
    status.textContent = "Copied. Replace USER:PASS with the dashboard credentials before running it.";
  } catch {
    status.textContent = command;
  }
});

loadAll();
