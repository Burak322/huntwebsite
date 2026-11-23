import { getIntlLocale, getLanguage, t, translateApiMessage } from "./i18n/index.js";

const AUTH_EXEMPT_401_PATHS = new Set([
  "/api/auth/login",
  "/api/auth/setup",
  "/api/auth/status",
  "/api/auth/change-password",
]);

let unauthorizedHandler = null;

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

export function getAuthStatus() {
  return request("/api/auth/status", { method: "GET" });
}

export function setupAdmin({ username, password, clanName }) {
  return request("/api/auth/setup", {
    method: "POST",
    body: { username, password, clanName },
  });
}

export function loginAdmin({ username, password }) {
  return request("/api/auth/login", {
    method: "POST",
    body: { username, password },
  });
}

export function logoutAdmin() {
  return request("/api/auth/logout", { method: "POST" });
}

export function getMe() {
  return request("/api/auth/me", { method: "GET" });
}

export function changePassword({ currentPassword, newPassword }) {
  return request("/api/auth/change-password", {
    method: "POST",
    body: { currentPassword, newPassword },
  });
}

export function updateClanName(clanName) {
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
export const listFields = (params = {}) => request(`/api/fields${qs(params)}`);
export const createField = (body) => request("/api/fields", { method: "POST", body });
export const updateField = (id, body) => request(`/api/fields/${id}`, { method: "PATCH", body });
export const deleteField = (id) => request(`/api/fields/${id}`, { method: "DELETE" });

// ---------------------------------------------------------------- players
export const listPlayers = (params = {}) => request(`/api/players${qs(params)}`);
export const createPlayer = (body) => request("/api/players", { method: "POST", body });
export const getPlayer = (id) => request(`/api/players/${id}`);
export const updatePlayer = (id, body) => request(`/api/players/${id}`, { method: "PATCH", body });
export const deletePlayer = (id) => request(`/api/players/${id}`, { method: "DELETE" });
export const addAlias = (id, alias_name) =>
  request(`/api/players/${id}/aliases`, { method: "POST", body: { alias_name } });
export const deleteAlias = (id, aliasId) =>
  request(`/api/players/${id}/aliases/${aliasId}`, { method: "DELETE" });
export function extractPlayersFromPhoto(file) {
  const fd = new FormData();
  fd.append("file", file);
  return request("/api/players/import-ocr", { method: "POST", body: fd });
}
export const bulkImportPlayers = (body) =>
  request("/api/players/import-bulk", { method: "POST", body });
export const createProgression = (id, body) =>
  request(`/api/players/${id}/progression`, { method: "POST", body });
export const updateProgression = (entryId, body) =>
  request(`/api/progression/${entryId}`, { method: "PATCH", body });
export const deleteProgression = (entryId) => request(`/api/progression/${entryId}`, { method: "DELETE" });

// ---------------------------------------------------------------- duels
export const getDashboard = () => request("/api/dashboard");
export const listDuels = () => request("/api/duels");
export const createDuel = (body) => request("/api/duels", { method: "POST", body });
export const getDuel = (id) => request(`/api/duels/${id}`);
export const updateDuel = (id, body) => request(`/api/duels/${id}`, { method: "PATCH", body });
export const deleteDuel = (id) => request(`/api/duels/${id}`, { method: "DELETE" });
export function extractScreenshot(duelId, file, scoreDate) {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("score_date", scoreDate);
  return request(`/api/duels/${duelId}/screenshots/extract`, { method: "POST", body: fd });
}
export const commitScreenshot = (duelId, screenshotId, body) =>
  request(`/api/duels/${duelId}/screenshots/${screenshotId}/commit`, { method: "POST", body });
export const addScore = (duelId, body) => request(`/api/duels/${duelId}/scores`, { method: "POST", body });
export const updateScore = (id, body) => request(`/api/scores/${id}`, { method: "PATCH", body });
export const deleteScore = (id) => request(`/api/scores/${id}`, { method: "DELETE" });

// ---------------------------------------------------------------- limits
export const getDailyLimit = () => request("/api/limits/daily");
export const setDailyLimit = (minScore, note) =>
  request("/api/limits/daily", { method: "PUT", body: { minScore, note: note || null } });
export const evaluateLimits = (params = {}) => request(`/api/limits/evaluate${qs(params)}`);
