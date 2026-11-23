import { getIntlLocale, getLanguage, t, translateApiMessage } from "./i18n/index.js";

const AUTH_EXEMPT_401_PATHS = new Set([
  "/api/auth/login",
  "/api/auth/setup",
  "/api/auth/status",
  "/api/auth/change-password",
]);

let unauthorizedHandler = null;
let staticModPromise = null;

export function isStaticMode() {
  if (typeof document === "undefined") return false;
  const meta = document.querySelector('meta[name="clan-static-mode"]');
  return meta?.getAttribute("content") === "true";
}

function getStaticBackend() {
  if (!staticModPromise) {
    staticModPromise = import("./staticBackend.js");
  }
  return staticModPromise;
}

export class ApiError extends Error {
  constructor(status, message, data = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
  }
}

export function setUnauthorizedHandler(fn) {
  unauthorizedHandler = fn;
}

export function escapeHtml(value) {
  if (value === null || value === undefined) {
    return "";
  }
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export async function request(path, options = {}) {
  const { body, headers = {}, ...rest } = options;
  const finalHeaders = { ...headers };
  let finalBody = body;

  if (body !== undefined && !(body instanceof FormData) && typeof body !== "string") {
    finalHeaders["Content-Type"] = finalHeaders["Content-Type"] || "application/json";
    finalBody = JSON.stringify(body);
  }

  const response = await fetch(path, {
    credentials: "same-origin",
    headers: finalHeaders,
    body: finalBody,
    ...rest,
  });

  const contentType = response.headers.get("content-type") || "";
  let data = null;
  if (contentType.includes("application/json")) {
    data = await response.json();
  } else {
    const text = await response.text();
    data = text ? { detail: text } : null;
  }

  if (!response.ok) {
    let detail = t("api.requestFailed", { status: response.status });
    if (data) {
      if (Array.isArray(data.detail)) {
        detail = data.detail
          .map((item) =>
            typeof item?.msg === "string" ? translateApiMessage(item.msg) : JSON.stringify(item)
          )
          .join("; ");
      } else if (typeof data.detail === "string" && data.detail) {
        detail = translateApiMessage(data.detail);
      } else if (typeof data.message === "string" && data.message) {
        detail = translateApiMessage(data.message);
      }
    }
    if (
      response.status === 401 &&
      !AUTH_EXEMPT_401_PATHS.has(path) &&
      typeof unauthorizedHandler === "function"
    ) {
      unauthorizedHandler();
    }
    throw new ApiError(response.status, detail, data);
  }

  return data;
}

export async function getAuthStatus() {
  if (isStaticMode()) return (await getStaticBackend()).getAuthStatus();
  return request("/api/auth/status", { method: "GET" });
}

export async function setupAdmin({ username, password, clanName }) {
  if (isStaticMode()) return (await getStaticBackend()).setupAdmin({ username, password, clanName });
  return request("/api/auth/setup", {
    method: "POST",
    body: { username, password, clanName },
  });
}

export async function loginAdmin({ username, password }) {
  if (isStaticMode()) return (await getStaticBackend()).loginAdmin({ username, password });
  return request("/api/auth/login", {
    method: "POST",
    body: { username, password },
  });
}

export async function logoutAdmin() {
  if (isStaticMode()) return (await getStaticBackend()).logoutAdmin();
  return request("/api/auth/logout", { method: "POST" });
}

export async function getMe() {
  if (isStaticMode()) return (await getStaticBackend()).getMe();
  return request("/api/auth/me", { method: "GET" });
}

export async function changePassword({ currentPassword, newPassword }) {
  if (isStaticMode()) {
    return (await getStaticBackend()).changePassword({ currentPassword, newPassword });
  }
  return request("/api/auth/change-password", {
    method: "POST",
    body: { currentPassword, newPassword },
  });
}

export async function updateClanName(clanName) {
  if (isStaticMode()) return (await getStaticBackend()).updateClanName(clanName);
  return request("/api/settings/clan", {
    method: "PUT",
    body: { clanName },
  });
}

// ---------------------------------------------------------------- helpers
const NUMBER_FMT_CACHE = new Map();

function getNumberFormatter() {
  const loc = getIntlLocale();
  if (!NUMBER_FMT_CACHE.has(loc)) {
    NUMBER_FMT_CACHE.set(loc, new Intl.NumberFormat(loc));
  }
  return NUMBER_FMT_CACHE.get(loc);
}

export const CLAN_RANKS = ["R1", "R2", "R3", "R4", "R5"];
export const TOWER_LEVELS = ["I1", "I2", "I3", "I4", "I5", "I6", "I7", "I8", "I9", "I10"];

export function renderSelectOptions(values, selected = "", emptyLabel = null) {
  const cur = selected ? String(selected) : "";
  const resolvedEmptyLabel =
    emptyLabel === null || emptyLabel === undefined ? t("common.notSelected") : emptyLabel;
  return [
    `<option value="">${escapeHtml(resolvedEmptyLabel)}</option>`,
    ...values.map(
      (v) =>
        `<option value="${escapeHtml(v)}" ${cur === v ? "selected" : ""}>${escapeHtml(v)}</option>`
    ),
  ].join("");
}

export function fmtNum(value) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? getNumberFormatter().format(n) : escapeHtml(value);
}

export function fmtDate(value) {
  if (!value) return "—";
  const s = String(value);
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return s;
  const lang = getLanguage();
  if (lang === "en") {
    return `${m[2]}/${m[3]}/${m[1]}`;
  }
  if (lang === "it" || lang === "ar") {
    return `${m[3]}/${m[2]}/${m[1]}`;
  }
  return `${m[3]}.${m[2]}.${m[1]}`;
}

export function fmtDateTime(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString(getIntlLocale());
}

export function todayIso() {
  const d = new Date();
  const pad = (x) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

const qs = (params) => {
  const sp = new URLSearchParams();
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") sp.set(k, v);
  });
  const s = sp.toString();
  return s ? `?${s}` : "";
};

// ---------------------------------------------------------------- fields
export async function listFields(params = {}) {
  if (isStaticMode()) return (await getStaticBackend()).listFields(params);
  return request(`/api/fields${qs(params)}`);
}
export async function createField(body) {
  if (isStaticMode()) return (await getStaticBackend()).createField(body);
  return request("/api/fields", { method: "POST", body });
}
export async function updateField(id, body) {
  if (isStaticMode()) return (await getStaticBackend()).updateField(id, body);
  return request(`/api/fields/${id}`, { method: "PATCH", body });
}
export async function deleteField(id) {
  if (isStaticMode()) return (await getStaticBackend()).deleteField(id);
  return request(`/api/fields/${id}`, { method: "DELETE" });
}

// ---------------------------------------------------------------- players
export async function listPlayers(params = {}) {
  if (isStaticMode()) return (await getStaticBackend()).listPlayers(params);
  return request(`/api/players${qs(params)}`);
}
export async function createPlayer(body) {
  if (isStaticMode()) return (await getStaticBackend()).createPlayer(body);
  return request("/api/players", { method: "POST", body });
}
export async function getPlayer(id) {
  if (isStaticMode()) return (await getStaticBackend()).getPlayer(id);
  return request(`/api/players/${id}`);
}
export async function updatePlayer(id, body) {
  if (isStaticMode()) return (await getStaticBackend()).updatePlayer(id, body);
  return request(`/api/players/${id}`, { method: "PATCH", body });
}
export async function deletePlayer(id) {
  if (isStaticMode()) return (await getStaticBackend()).deletePlayer(id);
  return request(`/api/players/${id}`, { method: "DELETE" });
}
export async function addAlias(id, alias_name) {
  if (isStaticMode()) return (await getStaticBackend()).addAlias(id, alias_name);
  return request(`/api/players/${id}/aliases`, { method: "POST", body: { alias_name } });
}
export async function deleteAlias(id, aliasId) {
  if (isStaticMode()) return (await getStaticBackend()).deleteAlias(id, aliasId);
  return request(`/api/players/${id}/aliases/${aliasId}`, { method: "DELETE" });
}
export async function extractPlayersFromPhoto(file) {
  if (isStaticMode()) return (await getStaticBackend()).extractPlayersFromPhoto(file);
  const fd = new FormData();
  fd.append("file", file);
  return request("/api/players/import-ocr", { method: "POST", body: fd });
}
export async function bulkImportPlayers(body) {
  if (isStaticMode()) return (await getStaticBackend()).bulkImportPlayers(body);
  return request("/api/players/import-bulk", { method: "POST", body });
}
export async function createProgression(id, body) {
  if (isStaticMode()) return (await getStaticBackend()).createProgression(id, body);
  return request(`/api/players/${id}/progression`, { method: "POST", body });
}
export async function updateProgression(entryId, body) {
  if (isStaticMode()) return (await getStaticBackend()).updateProgression(entryId, body);
  return request(`/api/progression/${entryId}`, { method: "PATCH", body });
}
export async function deleteProgression(entryId) {
  if (isStaticMode()) return (await getStaticBackend()).deleteProgression(entryId);
  return request(`/api/progression/${entryId}`, { method: "DELETE" });
}

// ---------------------------------------------------------------- duels
export async function getDashboard() {
  if (isStaticMode()) return (await getStaticBackend()).getDashboard();
  return request("/api/dashboard");
}
export async function listDuels() {
  if (isStaticMode()) return (await getStaticBackend()).listDuels();
  return request("/api/duels");
}
export async function createDuel(body) {
  if (isStaticMode()) return (await getStaticBackend()).createDuel(body);
  return request("/api/duels", { method: "POST", body });
}
export async function getDuel(id) {
  if (isStaticMode()) return (await getStaticBackend()).getDuel(id);
  return request(`/api/duels/${id}`);
}
export async function updateDuel(id, body) {
  if (isStaticMode()) return (await getStaticBackend()).updateDuel(id, body);
  return request(`/api/duels/${id}`, { method: "PATCH", body });
}
export async function deleteDuel(id) {
  if (isStaticMode()) return (await getStaticBackend()).deleteDuel(id);
  return request(`/api/duels/${id}`, { method: "DELETE" });
}
export async function extractScreenshot(duelId, file, scoreDate) {
  if (isStaticMode()) return (await getStaticBackend()).extractScreenshot(duelId, file, scoreDate);
  const fd = new FormData();
  fd.append("file", file);
  fd.append("score_date", scoreDate);
  return request(`/api/duels/${duelId}/screenshots/extract`, { method: "POST", body: fd });
}
export async function commitScreenshot(duelId, screenshotId, body) {
  if (isStaticMode()) {
    return (await getStaticBackend()).commitScreenshot(duelId, screenshotId, body);
  }
  return request(`/api/duels/${duelId}/screenshots/${screenshotId}/commit`, { method: "POST", body });
}
export async function previewWeeklyDiff(duelId, formData) {
  if (isStaticMode()) return (await getStaticBackend()).previewWeeklyDiff(duelId, formData);
  return request(`/api/duels/${duelId}/weekly-diff/preview`, { method: "POST", body: formData });
}
export async function commitWeeklyDiff(duelId, body) {
  if (isStaticMode()) return (await getStaticBackend()).commitWeeklyDiff(duelId, body);
  return request(`/api/duels/${duelId}/weekly-diff/commit`, { method: "POST", body });
}
export async function addScore(duelId, body) {
  if (isStaticMode()) return (await getStaticBackend()).addScore(duelId, body);
  return request(`/api/duels/${duelId}/scores`, { method: "POST", body });
}
export async function updateScore(id, body) {
  if (isStaticMode()) return (await getStaticBackend()).updateScore(id, body);
  return request(`/api/scores/${id}`, { method: "PATCH", body });
}
export async function deleteScore(id) {
  if (isStaticMode()) return (await getStaticBackend()).deleteScore(id);
  return request(`/api/scores/${id}`, { method: "DELETE" });
}

// ---------------------------------------------------------------- limits
export async function getDailyLimit() {
  if (isStaticMode()) return (await getStaticBackend()).getDailyLimit();
  return request("/api/limits/daily");
}
export async function setDailyLimit(minScore, note) {
  if (isStaticMode()) return (await getStaticBackend()).setDailyLimit(minScore, note);
  return request("/api/limits/daily", { method: "PUT", body: { minScore, note: note || null } });
}
export async function evaluateLimits(params = {}) {
  if (isStaticMode()) return (await getStaticBackend()).evaluateLimits(params);
  return request(`/api/limits/evaluate${qs(params)}`);
}

// ---------------------------------------------------------------- static backup
export async function exportStaticBackup() {
  return (await getStaticBackend()).exportBackupJson();
}
export async function importStaticBackup(rawText) {
  return (await getStaticBackend()).importBackupJson(rawText);
}
export async function resetStaticData() {
  return (await getStaticBackend()).resetToSeed();
}
