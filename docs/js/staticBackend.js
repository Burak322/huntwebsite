import { translateApiMessage } from "./i18n/index.js";

const STORAGE_KEY = "clan_static_db_v1";
const VALID_STATUSES = new Set(["active", "inactive", "left"]);
const VALID_RANKS = new Set(["R1", "R2", "R3", "R4", "R5"]);
const VALID_TOWERS = new Set(["I1", "I2", "I3", "I4", "I5", "I6", "I7", "I8", "I9", "I10"]);
const VALID_DUEL_STATUSES = new Set(["ongoing", "completed", "cancelled"]);
const VALID_SORTS = new Set([
  "name_asc",
  "name_desc",
  "rank_desc",
  "rank_asc",
  "tower_desc",
  "tower_asc",
]);
const VALID_SCOPES = new Set(["profile", "progression"]);
const VALID_FIELD_TYPES = new Set(["text", "number", "boolean", "select", "date"]);

const TESSERACT_CDN = "https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js";

let memDb = null;
let initPromise = null;
let tesseractPromise = null;

function makeError(status, message) {
  const err = new Error(translateApiMessage(message));
  err.status = status;
  return err;
}

function nowIso() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

function todayDate() {
  const d = new Date();
  const pad = (x) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function foldTr(value) {
  return String(value || "")
    .trim()
    .replaceAll("İ", "i")
    .replaceAll("I", "ı")
    .toLowerCase();
}

function foldAscii(value) {
  return String(value || "")
    .trim()
    .toLowerCase();
}

function slugifyFieldKey(label) {
  const trMap = {
    "Ç": "c", "ç": "c", "Ğ": "g", "ğ": "g",
    "İ": "i", "I": "i", "ı": "i", "Ö": "o",
    "ö": "o", "Ş": "s", "ş": "s", "Ü": "u", "ü": "u",
  };
  let mapped = "";
  for (const ch of String(label || "")) {
    mapped += trMap[ch] ?? ch;
  }
  const ascii = mapped.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  const slug = ascii.replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 64).replace(/_+$/g, "");
  if (!slug) {
    throw makeError(422, "Alan etiketinden geçerli bir alan anahtarı üretilemedi.");
  }
  return slug;
}

async function sha256Hex(text) {
  const input = String(text ?? "");
  if (typeof crypto !== "undefined" && crypto.subtle && typeof TextEncoder !== "undefined") {
    try {
      const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(input));
      return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
    } catch {
      // Fall through to lightweight fallback on non-HTTPS contexts
    }
  }
  let h1 = 0xdeadbeef ^ input.length;
  let h2 = 0x41c6ce57 ^ input.length;
  for (let i = 0; i < input.length; i += 1) {
    const ch = input.charCodeAt(i);
    h1 = Math.imul(h1 ^ ch, 2654435761);
    h2 = Math.imul(h2 ^ ch, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return (4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(16);
}

function emptyDbSkeleton() {
  return {
    version: 1,
    auth: {
      authenticated: true,
      username: "Admin",
      clanName: "Hunt",
      passwordHash: null,
    },
    activeDailyMinScore: 0,
    dailyLimitUpdatedAt: null,
    dailyLimitHistory: [],
    trackingFields: [],
    players: [],
    playerAliases: [],
    progressionEntries: [],
    duels: [],
    duelScreenshots: [],
    duelScores: [],
    nextIds: {
      field: 1,
      player: 1,
      alias: 1,
      progression: 1,
      duel: 1,
      screenshot: 1,
      score: 1,
      limitHistory: 1,
    },
  };
}

function maxId(arr) {
  let m = 0;
  for (const item of arr || []) {
    const n = Number(item?.id || 0);
    if (n > m) m = n;
  }
  return m + 1;
}

function normalizeDb(raw) {
  const base = emptyDbSkeleton();
  const src = raw && typeof raw === "object" ? raw : {};
  const authSrc = src.auth && typeof src.auth === "object" ? src.auth : {};
  const db = {
    version: 1,
    auth: {
      authenticated: authSrc.authenticated !== undefined ? Boolean(authSrc.authenticated) : true,
      username: typeof authSrc.username === "string" && authSrc.username.trim() ? authSrc.username.trim() : "Admin",
      clanName: typeof src.clanName === "string" && src.clanName.trim()
        ? src.clanName.trim()
        : typeof authSrc.clanName === "string" && authSrc.clanName.trim()
          ? authSrc.clanName.trim()
          : "Hunt",
      passwordHash: typeof authSrc.passwordHash === "string" ? authSrc.passwordHash : null,
    },
    activeDailyMinScore: Number.isFinite(Number(src.activeDailyMinScore))
      ? Math.max(0, Math.trunc(Number(src.activeDailyMinScore)))
      : 0,
    dailyLimitUpdatedAt: src.dailyLimitUpdatedAt || null,
    dailyLimitHistory: Array.isArray(src.dailyLimitHistory) ? src.dailyLimitHistory : [],
    trackingFields: Array.isArray(src.trackingFields) ? src.trackingFields : [],
    players: Array.isArray(src.players) ? src.players : [],
    playerAliases: Array.isArray(src.playerAliases) ? src.playerAliases : [],
    progressionEntries: Array.isArray(src.progressionEntries) ? src.progressionEntries : [],
    duels: Array.isArray(src.duels) ? src.duels : [],
    duelScreenshots: Array.isArray(src.duelScreenshots) ? src.duelScreenshots : [],
    duelScores: Array.isArray(src.duelScores) ? src.duelScores : [],
    nextIds: { ...base.nextIds, ...(src.nextIds && typeof src.nextIds === "object" ? src.nextIds : {}) },
  };
  db.nextIds.field = Math.max(Number(db.nextIds.field || 1), maxId(db.trackingFields));
  db.nextIds.player = Math.max(Number(db.nextIds.player || 1), maxId(db.players));
  db.nextIds.alias = Math.max(Number(db.nextIds.alias || 1), maxId(db.playerAliases));
  db.nextIds.progression = Math.max(Number(db.nextIds.progression || 1), maxId(db.progressionEntries));
  db.nextIds.duel = Math.max(Number(db.nextIds.duel || 1), maxId(db.duels));
  db.nextIds.screenshot = Math.max(Number(db.nextIds.screenshot || 1), maxId(db.duelScreenshots));
  db.nextIds.score = Math.max(Number(db.nextIds.score || 1), maxId(db.duelScores));
  db.nextIds.limitHistory = Math.max(Number(db.nextIds.limitHistory || 1), maxId(db.dailyLimitHistory));
  return db;
}

function saveDb(db) {
  memDb = db;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(db));
  } catch {
    // Retry after stripping large screenshot data URLs if quota exceeded
    const trimmed = {
      ...db,
      duelScreenshots: (db.duelScreenshots || []).map((s) =>
        typeof s.imageUrl === "string" && s.imageUrl.startsWith("data:")
          ? { ...s, imageUrl: "" }
          : s
      ),
    };
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
    } catch {
      // Keep in-memory state if storage is full/disabled
    }
  }
}

async function fetchSeedData() {
  try {
    const resp = await fetch("./seed.json", { cache: "no-store" });
    if (!resp.ok) return emptyDbSkeleton();
    const raw = await resp.json();
    return normalizeDb(raw);
  } catch {
    return emptyDbSkeleton();
  }
}

async function ensureDb() {
  if (memDb) return memDb;
  if (!initPromise) {
    initPromise = (async () => {
      try {
        const existing = window.localStorage.getItem(STORAGE_KEY);
        if (existing) {
          memDb = normalizeDb(JSON.parse(existing));
          return memDb;
        }
      } catch {
        // Ignore corrupt storage and re-seed
      }
      const seeded = await fetchSeedData();
      saveDb(seeded);
      return memDb;
    })();
  }
  return initPromise;
}

function validateRank(val) {
  if (val === null || val === undefined || val === "") return null;
  const cleaned = String(val).trim().toUpperCase();
  if (!VALID_RANKS.has(cleaned)) {
    throw makeError(422, "Rank R1 ile R5 arasında olmalıdır.");
  }
  return cleaned;
}

function validateTower(val) {
  if (val === null || val === undefined || val === "") return null;
  const cleaned = String(val)
    .trim()
    .replaceAll("ı", "I")
    .replaceAll("İ", "I")
    .replaceAll("i", "I")
    .toUpperCase();
  if (!VALID_TOWERS.has(cleaned)) {
    throw makeError(422, "Kule seviyesi I1 ile I10 arasında olmalıdır.");
  }
  return cleaned;
}

function evaluateScore(score, activeLimit) {
  const s = Math.trunc(Number(score || 0));
  const limit = Math.max(0, Math.trunc(Number(activeLimit || 0)));
  const pct = limit === 0 ? 100 : Math.round((s / limit) * 100);
  return {
    activeDailyMinScore: limit,
    delta: s - limit,
    meetsLimit: s >= limit,
    completionPct: pct,
  };
}

function evaluateDailyScores(db, scoresList, activeLimit) {
  const playerMap = new Map(db.players.map((p) => [Number(p.id), p]));
  const buckets = new Map();
  for (const rec of scoresList) {
    const pid = rec.player_id !== null && rec.player_id !== undefined ? Number(rec.player_id) : null;
    const pObj = pid !== null ? playerMap.get(pid) : null;
    const displayName = pObj ? pObj.display_name : rec.extracted_name;
    const pKey = pid !== null ? `id:${pid}` : `name:${foldAscii(rec.extracted_name)}`;
    const dateStr = String(rec.score_date);
    const key = `${dateStr}|${pKey}`;
    let bucket = buckets.get(key);
    if (!bucket) {
      bucket = {
        playerId: pid,
        playerName: String(displayName || ""),
        scoreDate: dateStr,
        totalScore: 0,
        entryCount: 0,
      };
      buckets.set(key, bucket);
    }
    bucket.totalScore += Math.trunc(Number(rec.score || 0));
    bucket.entryCount += 1;
  }

  const results = [...buckets.values()].map((b) => ({
    ...b,
    ...evaluateScore(b.totalScore, activeLimit),
  }));

  results.sort((a, b) => {
    if (a.scoreDate !== b.scoreDate) return b.scoreDate.localeCompare(a.scoreDate);
    if (a.totalScore !== b.totalScore) return b.totalScore - a.totalScore;
    return a.playerName.localeCompare(b.playerName, "tr");
  });
  return results;
}

function summarizeCompliance(evals) {
  const total = evals.length;
  const met = evals.filter((e) => e.meetsLimit).length;
  return { total, met, missed: total - met };
}

function getLatestProgressionMap(db) {
  const latest = new Map();
  const sorted = [...db.progressionEntries].sort((a, b) => {
    if (a.recorded_at !== b.recorded_at) return String(b.recorded_at).localeCompare(String(a.recorded_at));
    return Number(b.id) - Number(a.id);
  });
  for (const entry of sorted) {
    const pid = Number(entry.player_id);
    if (!latest.has(pid)) {
      latest.set(pid, entry);
    }
  }
  return latest;
}

function computePlayerProgressionWithDeltas(db, playerId) {
  const asc = db.progressionEntries
    .filter((e) => Number(e.player_id) === Number(playerId))
    .sort((a, b) => {
      if (a.recorded_at !== b.recorded_at) return String(a.recorded_at).localeCompare(String(b.recorded_at));
      return Number(a.id) - Number(b.id);
    });
  const prevNum = new Map();
  const enriched = asc.map((entry) => {
    const deltas = {};
    const metrics = entry.metrics || {};
    for (const [k, v] of Object.entries(metrics)) {
      if (typeof v === "number" && Number.isFinite(v)) {
        if (prevNum.has(k)) {
          deltas[k] = Number((v - prevNum.get(k)).toFixed(4));
        }
        prevNum.set(k, v);
      }
    }
    return { ...entry, deltas };
  });
  return enriched.reverse();
}

function formatPlayerRecord(p, aliases, latestProg) {
  return {
    ...p,
    aliases: aliases || [],
    latestProgression: latestProg || null,
  };
}

function checkNameOrAliasUnique(db, candidateName, excludePlayerId = null) {
  const target = foldTr(candidateName);
  for (const p of db.players) {
    if (excludePlayerId !== null && Number(p.id) === Number(excludePlayerId)) continue;
    if (foldTr(p.display_name) === target) {
      throw makeError(409, `"${candidateName}" adı zaten başka bir oyuncuda kayıtlı.`);
    }
  }
  for (const a of db.playerAliases) {
    if (foldTr(a.alias_name) === target) {
      throw makeError(409, `"${candidateName}" zaten bir takma ad olarak kayıtlı.`);
    }
  }
}

function numFromRank(r) {
  return r && VALID_RANKS.has(r) ? Number(r.slice(1)) : null;
}

function numFromTower(tVal) {
  return tVal && VALID_TOWERS.has(tVal) ? Number(tVal.slice(1)) : null;
}

function cmpNullableNum(a, b, desc) {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return desc ? b - a : a - b;
}

function validateDynamicFieldValues(fields, values, { partial = false, existing = {} } = {}) {
  const byKey = new Map(fields.map((f) => [f.field_key, f]));
  const merged = partial ? { ...existing } : {};
  for (const [k, v] of Object.entries(values || {})) {
    const def = byKey.get(k);
    if (!def) {
      throw makeError(422, `Tanımsız alan anahtarı: ${k}`);
    }
    if (v === null || v === undefined || v === "") {
      delete merged[k];
      continue;
    }
    if (def.field_type === "number") {
      const n = Number(v);
      if (!Number.isFinite(n)) {
        throw makeError(422, `'${def.label}' alanı sayısal bir değer olmalıdır.`);
      }
      merged[k] = n;
    } else if (def.field_type === "boolean") {
      merged[k] = Boolean(v);
    } else {
      merged[k] = String(v).trim();
    }
  }
  for (const f of fields) {
    if (f.is_active && f.is_required && merged[f.field_key] === undefined) {
      throw makeError(422, `'${f.label}' alanı zorunludur.`);
    }
  }
  return merged;
}

// ---------------------------------------------------------------- Auth / Clan

export async function getAuthStatus() {
  const db = await ensureDb();
  return {
    needsSetup: false,
    authenticated: Boolean(db.auth.authenticated),
    admin: db.auth.authenticated ? { id: 1, username: db.auth.username } : null,
    clanName: db.auth.clanName,
  };
}

export async function setupAdmin({ username, password, clanName }) {
  const db = await ensureDb();
  db.auth.username = String(username || "Admin").trim() || "Admin";
  if (clanName && String(clanName).trim()) {
    db.auth.clanName = String(clanName).trim();
  }
  db.auth.passwordHash = password ? await sha256Hex(password) : null;
  db.auth.authenticated = true;
  saveDb(db);
  return { admin: { id: 1, username: db.auth.username }, clanName: db.auth.clanName };
}

export async function loginAdmin({ username, password }) {
  const db = await ensureDb();
  const cleanUser = String(username || "").trim();
  const rawPass = String(password || "");
  if (!cleanUser || !rawPass) {
    throw makeError(401, "Kullanıcı adı veya şifre hatalı.");
  }
  if (db.auth.passwordHash) {
    const incomingHash = await sha256Hex(rawPass);
    if (cleanUser !== db.auth.username || incomingHash !== db.auth.passwordHash) {
      throw makeError(401, "Kullanıcı adı veya şifre hatalı.");
    }
  }
  db.auth.authenticated = true;
  saveDb(db);
  return { admin: { id: 1, username: db.auth.username }, clanName: db.auth.clanName };
}

export async function logoutAdmin() {
  const db = await ensureDb();
  db.auth.authenticated = false;
  saveDb(db);
  return { ok: true };
}

export async function getMe() {
  const db = await ensureDb();
  return { admin: { id: 1, username: db.auth.username }, clanName: db.auth.clanName };
}

export async function changePassword({ currentPassword, newPassword }) {
  const db = await ensureDb();
  if (String(newPassword || "").length < 6) {
    throw makeError(422, "Şifre en az 6, en fazla 256 karakter olmalıdır.");
  }
  if (db.auth.passwordHash) {
    const curHash = await sha256Hex(currentPassword || "");
    if (curHash !== db.auth.passwordHash) {
      throw makeError(400, "Mevcut şifre hatalı.");
    }
  }
  db.auth.passwordHash = await sha256Hex(newPassword);
  saveDb(db);
  return { ok: true };
}

export async function updateClanName(clanName) {
  const db = await ensureDb();
  const clean = String(clanName || "").trim();
  if (!clean || clean.length > 80) {
    throw makeError(422, "Klan adı 1 ile 80 karakter arasında olmalıdır.");
  }
  db.auth.clanName = clean;
  saveDb(db);
  return { clanName: clean };
}

// ---------------------------------------------------------------- Fields

export async function listFields(params = {}) {
  const db = await ensureDb();
  let items = [...db.trackingFields];
  if (params.scope) {
    items = items.filter((f) => f.scope === params.scope);
  }
  if (params.activeOnly === true || params.activeOnly === "true") {
    items = items.filter((f) => f.is_active !== false);
  }
  items.sort((a, b) => Number(a.sort_order || 0) - Number(b.sort_order || 0) || Number(a.id) - Number(b.id));
  return { fields: items };
}

export async function createField(body) {
  const db = await ensureDb();
  const label = String(body?.label || "").trim();
  if (!label || label.length > 80) {
    throw makeError(422, "Alan etiketi 1 ile 80 karakter arasında olmalıdır.");
  }
  const scope = VALID_SCOPES.has(body?.scope) ? body.scope : "profile";
  const fieldType = VALID_FIELD_TYPES.has(body?.field_type) ? body.field_type : "text";
  const key = body?.field_key ? String(body.field_key).trim() : slugifyFieldKey(label);
  if (db.trackingFields.some((f) => f.field_key === key)) {
    throw makeError(409, `Alan anahtarı zaten mevcut: ${key}`);
  }
  const field = {
    id: db.nextIds.field++,
    field_key: key,
    label,
    scope,
    field_type: fieldType,
    unit: body?.unit ? String(body.unit).trim() : null,
    options: Array.isArray(body?.options) ? body.options : null,
    is_required: Boolean(body?.is_required),
    is_active: body?.is_active !== undefined ? Boolean(body.is_active) : true,
    sort_order: Number.isInteger(Number(body?.sort_order)) ? Number(body.sort_order) : 0,
    created_at: nowIso(),
  };
  db.trackingFields.push(field);
  saveDb(db);
  return { field };
}

export async function updateField(id, body) {
  const db = await ensureDb();
  const field = db.trackingFields.find((f) => Number(f.id) === Number(id));
  if (!field) throw makeError(404, "Takip alanı bulunamadı.");
  if (body.label !== undefined) field.label = String(body.label).trim();
  if (body.unit !== undefined) field.unit = body.unit ? String(body.unit).trim() : null;
  if (body.options !== undefined) field.options = body.options;
  if (body.is_required !== undefined) field.is_required = Boolean(body.is_required);
  if (body.is_active !== undefined) field.is_active = Boolean(body.is_active);
  if (body.sort_order !== undefined) field.sort_order = Number(body.sort_order) || 0;
  saveDb(db);
  return { field };
}

export async function deleteField(id) {
  const db = await ensureDb();
  const idx = db.trackingFields.findIndex((f) => Number(f.id) === Number(id));
  if (idx === -1) throw makeError(404, "Takip alanı bulunamadı.");
  db.trackingFields.splice(idx, 1);
  saveDb(db);
  return { deleted: true };
}

// ---------------------------------------------------------------- Players

export async function listPlayers(params = {}) {
  const db = await ensureDb();
  const sortKey = params.sort && String(params.sort).trim() ? String(params.sort).trim() : "name_asc";
  if (!VALID_SORTS.has(sortKey)) {
    throw makeError(422, `Geçersiz sıralama seçeneği: ${sortKey}`);
  }

  const aliasesByPlayer = new Map();
  for (const a of db.playerAliases) {
    const pid = Number(a.player_id);
    if (!aliasesByPlayer.has(pid)) aliasesByPlayer.set(pid, []);
    aliasesByPlayer.get(pid).push(a);
  }
  const latestMap = getLatestProgressionMap(db);
  const needle = foldTr(params.search || "");

  let items = db.players.filter((p) => {
    if (params.status && p.status !== params.status) return false;
    if (params.clan_rank && p.clan_rank !== validateRank(params.clan_rank)) return false;
    if (params.tower_level && p.tower_level !== validateTower(params.tower_level)) return false;
    if (needle) {
      const pAliases = aliasesByPlayer.get(Number(p.id)) || [];
      const inName = foldTr(p.display_name).includes(needle);
      const inAlias = pAliases.some((a) => foldTr(a.alias_name).includes(needle));
      if (!inName && !inAlias) return false;
    }
    return true;
  });

  items.sort((a, b) => {
    if (sortKey === "name_asc") {
      return a.display_name.localeCompare(b.display_name, undefined, { sensitivity: "base" }) || a.id - b.id;
    }
    if (sortKey === "name_desc") {
      return b.display_name.localeCompare(a.display_name, undefined, { sensitivity: "base" }) || b.id - a.id;
    }
    const rankCmp = (desc) => cmpNullableNum(numFromRank(a.clan_rank), numFromRank(b.clan_rank), desc);
    const towerCmp = (desc) => cmpNullableNum(numFromTower(a.tower_level), numFromTower(b.tower_level), desc);
    if (sortKey === "rank_desc" || sortKey === "rank_asc") {
      const desc = sortKey === "rank_desc";
      return rankCmp(desc) || towerCmp(desc) || a.display_name.localeCompare(b.display_name, undefined, { sensitivity: "base" }) || a.id - b.id;
    }
    const desc = sortKey === "tower_desc";
    return towerCmp(desc) || rankCmp(desc) || a.display_name.localeCompare(b.display_name, undefined, { sensitivity: "base" }) || a.id - b.id;
  });

  return {
    players: items.map((p) =>
      formatPlayerRecord(p, aliasesByPlayer.get(Number(p.id)) || [], latestMap.get(Number(p.id)) || null)
    ),
  };
}

export async function createPlayer(body) {
  const db = await ensureDb();
  const displayName = String(body?.display_name || "").trim();
  if (!displayName || displayName.length > 100) {
    throw makeError(422, "Oyuncu adı 1 ile 100 karakter arasında olmalıdır.");
  }
  const status = VALID_STATUSES.has(body?.status) ? body.status : "active";
  const clanRank = validateRank(body?.clan_rank);
  const towerLevel = validateTower(body?.tower_level);
  checkNameOrAliasUnique(db, displayName);

  const rawAliases = Array.isArray(body?.aliases) ? body.aliases : [];
  const cleanAliases = [];
  const seen = new Set([foldTr(displayName)]);
  for (const raw of rawAliases) {
    const cleanA = String(raw || "").trim();
    if (!cleanA) continue;
    const f = foldTr(cleanA);
    if (seen.has(f)) continue;
    checkNameOrAliasUnique(db, cleanA);
    seen.add(f);
    cleanAliases.push(cleanA);
  }

  const profileFields = db.trackingFields.filter((f) => f.scope === "profile");
  const profileValues = validateDynamicFieldValues(profileFields, body?.profile_values || {});
  const ts = nowIso();
  const player = {
    id: db.nextIds.player++,
    display_name: displayName,
    status,
    clan_rank: clanRank,
    tower_level: towerLevel,
    joined_at: body?.joined_at ? String(body.joined_at).trim() : null,
    notes: body?.notes ? String(body.notes).trim() : null,
    profile_values: profileValues,
    created_at: ts,
    updated_at: ts,
  };
  db.players.push(player);

  const createdAliases = cleanAliases.map((aliasName) => {
    const a = {
      id: db.nextIds.alias++,
      player_id: player.id,
      alias_name: aliasName,
      created_at: ts,
    };
    db.playerAliases.push(a);
    return a;
  });

  saveDb(db);
  return { player: formatPlayerRecord(player, createdAliases, null) };
}

export async function getPlayer(id) {
  const db = await ensureDb();
  const p = db.players.find((item) => Number(item.id) === Number(id));
  if (!p) throw makeError(404, "Oyuncu bulunamadı.");
  const aliases = db.playerAliases.filter((a) => Number(a.player_id) === Number(p.id));
  const progEntries = computePlayerProgressionWithDeltas(db, p.id);
  const duelMap = new Map(db.duels.map((d) => [Number(d.id), d]));
  const activeLimit = db.activeDailyMinScore;

  const recentDuelScores = db.duelScores
    .filter((s) => Number(s.player_id) === Number(p.id))
    .sort((a, b) => String(b.score_date).localeCompare(String(a.score_date)) || Number(b.id) - Number(a.id))
    .slice(0, 50)
    .map((s) => {
      const duel = duelMap.get(Number(s.duel_id));
      return {
        ...s,
        opponent_clan_name: duel?.opponent_clan_name || "",
        duel_title: duel?.title || null,
        duel_status: duel?.status || "ongoing",
        ...evaluateScore(s.score, activeLimit),
      };
    });

  return {
    player: formatPlayerRecord(p, aliases, progEntries[0] || null),
    aliases,
    progressionEntries: progEntries,
    recentDuelScores,
  };
}

export async function updatePlayer(id, body) {
  const db = await ensureDb();
  const p = db.players.find((item) => Number(item.id) === Number(id));
  if (!p) throw makeError(404, "Oyuncu bulunamadı.");

  if (body.display_name !== undefined) {
    const cleanName = String(body.display_name || "").trim();
    if (!cleanName) throw makeError(422, "Oyuncu adı boş olamaz.");
    checkNameOrAliasUnique(db, cleanName, p.id);
    p.display_name = cleanName;
  }
  if (body.status !== undefined && VALID_STATUSES.has(body.status)) {
    p.status = body.status;
  }
  if ("clan_rank" in body) p.clan_rank = validateRank(body.clan_rank);
  if ("tower_level" in body) p.tower_level = validateTower(body.tower_level);
  if ("joined_at" in body) p.joined_at = body.joined_at ? String(body.joined_at).trim() : null;
  if ("notes" in body) p.notes = body.notes ? String(body.notes).trim() : null;
  if (body.profile_values !== undefined) {
    const profileFields = db.trackingFields.filter((f) => f.scope === "profile");
    p.profile_values = validateDynamicFieldValues(profileFields, body.profile_values, {
      partial: true,
      existing: p.profile_values || {},
    });
  }
  p.updated_at = nowIso();
  saveDb(db);
  const aliases = db.playerAliases.filter((a) => Number(a.player_id) === Number(p.id));
  const latestMap = getLatestProgressionMap(db);
  return { player: formatPlayerRecord(p, aliases, latestMap.get(Number(p.id)) || null) };
}

export async function deletePlayer(id) {
  const db = await ensureDb();
  const idx = db.players.findIndex((p) => Number(p.id) === Number(id));
  if (idx === -1) throw makeError(404, "Oyuncu bulunamadı.");
  const player = db.players[idx];
  db.players.splice(idx, 1);
  db.playerAliases = db.playerAliases.filter((a) => Number(a.player_id) !== Number(id));
  db.progressionEntries = db.progressionEntries.filter((e) => Number(e.player_id) !== Number(id));
  for (const s of db.duelScores) {
    if (Number(s.player_id) === Number(id)) {
      s.player_id = null;
      if (!s.extracted_name) s.extracted_name = player.display_name;
    }
  }
  saveDb(db);
  return { deleted: true };
}

export async function addAlias(playerId, aliasName) {
  const db = await ensureDb();
  const p = db.players.find((item) => Number(item.id) === Number(playerId));
  if (!p) throw makeError(404, "Oyuncu bulunamadı.");
  const clean = String(aliasName || "").trim();
  if (!clean) throw makeError(422, "Takma ad boş olamaz.");
  checkNameOrAliasUnique(db, clean);
  const alias = {
    id: db.nextIds.alias++,
    player_id: Number(playerId),
    alias_name: clean,
    created_at: nowIso(),
  };
  db.playerAliases.push(alias);
  saveDb(db);
  return { alias };
}

export async function deleteAlias(playerId, aliasId) {
  const db = await ensureDb();
  const idx = db.playerAliases.findIndex(
    (a) => Number(a.id) === Number(aliasId) && Number(a.player_id) === Number(playerId)
  );
  if (idx === -1) throw makeError(404, "Takma ad bulunamadı.");
  db.playerAliases.splice(idx, 1);
  saveDb(db);
  return { deleted: true };
}

export async function bulkImportPlayers(body) {
  const db = await ensureDb();
  const items = Array.isArray(body?.players) ? body.players : [];
  if (items.length === 0) {
    throw makeError(422, "İçe aktarılacak en az bir oyuncu olmalıdır.");
  }
  const skipExisting = body?.skip_existing !== false;
  const createdPlayers = [];
  const skipped = [];

  for (const item of items) {
    const cleanName = String(item?.display_name || "").trim();
    if (!cleanName) continue;
    const exists = db.players.some((p) => foldTr(p.display_name) === foldTr(cleanName)) ||
      db.playerAliases.some((a) => foldTr(a.alias_name) === foldTr(cleanName));
    if (exists && skipExisting) {
      skipped.push({ display_name: cleanName, reason: "already_exists" });
      continue;
    }
    const { player } = await createPlayer(item);
    let finalPlayer = player;
    if (item.initial_metrics && Object.keys(item.initial_metrics).length > 0) {
      const { entry } = await createProgression(player.id, {
        recorded_at: body?.recorded_at || item.joined_at || todayDate(),
        metrics: item.initial_metrics,
        note: "Fotoğraftan ilk kayıt",
      });
      finalPlayer = { ...player, latestProgression: entry };
    }
    createdPlayers.push(finalPlayer);
  }

  return {
    createdPlayers,
    skipped,
    createdCount: createdPlayers.length,
    skippedCount: skipped.length,
  };
}

// ---------------------------------------------------------------- Progression

export async function createProgression(playerId, body) {
  const db = await ensureDb();
  if (!db.players.some((p) => Number(p.id) === Number(playerId))) {
    throw makeError(404, "Oyuncu bulunamadı.");
  }
  const progFields = db.trackingFields.filter((f) => f.scope === "progression");
  const cleanMetrics = validateDynamicFieldValues(progFields, body?.metrics || {});
  if (Object.keys(cleanMetrics).length === 0) {
    throw makeError(422, "En az bir gelişim değeri girilmelidir.");
  }
  const ts = nowIso();
  const entry = {
    id: db.nextIds.progression++,
    player_id: Number(playerId),
    recorded_at: String(body?.recorded_at || todayDate()).slice(0, 10),
    metrics: cleanMetrics,
    note: body?.note ? String(body.note).trim() : null,
    created_at: ts,
    updated_at: ts,
  };
  db.progressionEntries.push(entry);
  saveDb(db);
  return { entry };
}

export async function updateProgression(entryId, body) {
  const db = await ensureDb();
  const entry = db.progressionEntries.find((e) => Number(e.id) === Number(entryId));
  if (!entry) throw makeError(404, "Gelişim kaydı bulunamadı.");
  if (body.recorded_at !== undefined) entry.recorded_at = String(body.recorded_at).slice(0, 10);
  if (body.note !== undefined) entry.note = body.note ? String(body.note).trim() : null;
  if (body.metrics !== undefined) {
    const progFields = db.trackingFields.filter((f) => f.scope === "progression");
    entry.metrics = validateDynamicFieldValues(progFields, body.metrics, {
      partial: true,
      existing: entry.metrics || {},
    });
  }
  entry.updated_at = nowIso();
  saveDb(db);
  return { entry };
}

export async function deleteProgression(entryId) {
  const db = await ensureDb();
  const idx = db.progressionEntries.findIndex((e) => Number(e.id) === Number(entryId));
  if (idx === -1) throw makeError(404, "Gelişim kaydı bulunamadı.");
  db.progressionEntries.splice(idx, 1);
  saveDb(db);
  return { deleted: true };
}

// ---------------------------------------------------------------- Duels & Limits

export async function getDailyLimit() {
  const db = await ensureDb();
  const history = [...db.dailyLimitHistory].sort(
    (a, b) => String(b.changedAt).localeCompare(String(a.changedAt)) || Number(b.id) - Number(a.id)
  );
  return {
    activeMinScore: db.activeDailyMinScore,
    updatedAt: db.dailyLimitUpdatedAt,
    history,
  };
}

export async function setDailyLimit(minScore, note) {
  const db = await ensureDb();
  const clean = Number(minScore);
  if (!Number.isInteger(clean) || clean < 0) {
    throw makeError(422, "Günlük limit sıfır veya pozitif tam sayı olmalıdır.");
  }
  const ts = nowIso();
  db.activeDailyMinScore = clean;
  db.dailyLimitUpdatedAt = ts;
  db.dailyLimitHistory.unshift({
    id: db.nextIds.limitHistory++,
    minScore: clean,
    note: note ? String(note).trim().slice(0, 500) || null : null,
    changedAt: ts,
  });
  saveDb(db);
  return getDailyLimit();
}

export async function evaluateLimits(params = {}) {
  const db = await ensureDb();
  let rows = [...db.duelScores];
  if (params.duelId) rows = rows.filter((r) => Number(r.duel_id) === Number(params.duelId));
  if (params.date) rows = rows.filter((r) => String(r.score_date) === String(params.date));
  if (params.playerId) rows = rows.filter((r) => Number(r.player_id) === Number(params.playerId));
  const evaluations = evaluateDailyScores(db, rows, db.activeDailyMinScore);
  return {
    activeDailyMinScore: db.activeDailyMinScore,
    evaluations,
    compliance: summarizeCompliance(evaluations),
  };
}

export async function listDuels() {
  const db = await ensureDb();
  const active = db.activeDailyMinScore;
  const sortedDuels = [...db.duels].sort(
    (a, b) => String(b.start_date).localeCompare(String(a.start_date)) || Number(b.id) - Number(a.id)
  );
  const duels = sortedDuels.map((d) => {
    const rows = db.duelScores.filter((s) => Number(s.duel_id) === Number(d.id));
    const evals = evaluateDailyScores(db, rows, active);
    const latestDate = evals[0]?.scoreDate || null;
    const latest = latestDate ? evals.filter((e) => e.scoreDate === latestDate) : [];
    const participants = new Set(evals.map((e) => `${e.playerId ?? "n"}:${e.playerName}`));
    return {
      ...d,
      scoreCount: rows.length,
      totalScore: rows.reduce((acc, r) => acc + Math.trunc(Number(r.score || 0)), 0),
      participantCount: participants.size,
      latestScoreDate: latestDate,
      latestDayCompliance: summarizeCompliance(latest),
    };
  });
  return { duels, activeDailyMinScore: active };
}

export async function getDashboard() {
  const db = await ensureDb();
  const { duels, activeDailyMinScore } = await listDuels();
  let active = 0;
  let inactive = 0;
  let left = 0;
  for (const p of db.players) {
    if (p.status === "active") active += 1;
    else if (p.status === "inactive") inactive += 1;
    else if (p.status === "left") left += 1;
  }
  const latestDate =
    db.duelScores.reduce((mx, s) => (!mx || s.score_date > mx ? s.score_date : mx), null) || null;
  const latestEval = latestDate
    ? evaluateDailyScores(
        db,
        db.duelScores.filter((s) => s.score_date === latestDate),
        activeDailyMinScore
      )
    : [];

  return {
    activeDailyMinScore,
    playerCounts: { active, inactive, left, total: db.players.length },
    duelCounts: {
      total: duels.length,
      ongoing: duels.filter((d) => d.status === "ongoing").length,
    },
    recentDuels: duels.slice(0, 5),
    latestScoreDate: latestDate,
    latestDayEvaluations: latestEval,
    latestDayCompliance: summarizeCompliance(latestEval),
  };
}

export async function createDuel(body) {
  const db = await ensureDb();
  const opp = String(body?.opponent_clan_name || "").trim();
  if (!opp) throw makeError(422, "Rakip klan adı zorunludur.");
  const startDate = String(body?.start_date || "").slice(0, 10);
  const endDate = body?.end_date ? String(body.end_date).slice(0, 10) : null;
  if (!startDate) throw makeError(422, "Başlangıç tarihi zorunludur.");
  if (endDate && endDate < startDate) {
    throw makeError(422, "Bitiş tarihi başlangıç tarihinden önce olamaz.");
  }
  const ts = nowIso();
  const duel = {
    id: db.nextIds.duel++,
    opponent_clan_name: opp,
    title: body?.title ? String(body.title).trim() : null,
    start_date: startDate,
    end_date: endDate,
    status: VALID_DUEL_STATUSES.has(body?.status) ? body.status : "ongoing",
    notes: body?.notes ? String(body.notes).trim() : null,
    created_at: ts,
    updated_at: ts,
  };
  db.duels.push(duel);
  saveDb(db);
  return { duel };
}

export async function getDuel(duelId) {
  const db = await ensureDb();
  const duel = db.duels.find((d) => Number(d.id) === Number(duelId));
  if (!duel) throw makeError(404, "Düello bulunamadı.");
  const active = db.activeDailyMinScore;
  const playerMap = new Map(db.players.map((p) => [Number(p.id), p]));

  const rawRows = db.duelScores
    .filter((s) => Number(s.duel_id) === Number(duelId))
    .sort((a, b) => {
      if (a.score_date !== b.score_date) return String(b.score_date).localeCompare(String(a.score_date));
      if (a.score !== b.score) return Number(b.score) - Number(a.score);
      return Number(a.id) - Number(b.id);
    });

  const scores = rawRows.map((s) => {
    const pObj = s.player_id !== null && s.player_id !== undefined ? playerMap.get(Number(s.player_id)) : null;
    return {
      ...s,
      player_name: pObj ? pObj.display_name : null,
      ...evaluateScore(s.score, active),
    };
  });

  const summaries = evaluateDailyScores(db, rawRows, active);
  const screenshots = db.duelScreenshots
    .filter((sh) => Number(sh.duel_id) === Number(duelId))
    .sort((a, b) => String(b.uploaded_at).localeCompare(String(a.uploaded_at)) || Number(b.id) - Number(a.id));

  const dateMap = new Map();
  for (const r of rawRows) {
    const dStr = String(r.score_date);
    const cur = dateMap.get(dStr) || { scoreDate: dStr, entryCount: 0, totalScore: 0 };
    cur.entryCount += 1;
    cur.totalScore += Math.trunc(Number(r.score || 0));
    dateMap.set(dStr, cur);
  }
  const recordedDates = [...dateMap.values()].sort((a, b) =>
    a.scoreDate.localeCompare(b.scoreDate)
  );

  return {
    duel,
    activeDailyMinScore: active,
    dailySummaries: summaries,
    compliance: summarizeCompliance(summaries),
    scores,
    screenshots,
    recordedDates,
  };
}

export async function updateDuel(duelId, body) {
  const db = await ensureDb();
  const duel = db.duels.find((d) => Number(d.id) === Number(duelId));
  if (!duel) throw makeError(404, "Düello bulunamadı.");
  if (body.opponent_clan_name !== undefined) {
    const clean = String(body.opponent_clan_name || "").trim();
    if (!clean) throw makeError(422, "Rakip klan adı zorunludur.");
    duel.opponent_clan_name = clean;
  }
  if ("title" in body) duel.title = body.title ? String(body.title).trim() : null;
  if (body.start_date !== undefined) duel.start_date = String(body.start_date).slice(0, 10);
  if ("end_date" in body) duel.end_date = body.end_date ? String(body.end_date).slice(0, 10) : null;
  if (duel.end_date && duel.end_date < duel.start_date) {
    throw makeError(422, "Bitiş tarihi başlangıç tarihinden önce olamaz.");
  }
  if (body.status !== undefined && VALID_DUEL_STATUSES.has(body.status)) duel.status = body.status;
  if ("notes" in body) duel.notes = body.notes ? String(body.notes).trim() : null;
  duel.updated_at = nowIso();
  saveDb(db);
  return { duel };
}

export async function deleteDuel(duelId) {
  const db = await ensureDb();
  const idx = db.duels.findIndex((d) => Number(d.id) === Number(duelId));
  if (idx === -1) throw makeError(404, "Düello bulunamadı.");
  db.duels.splice(idx, 1);
  db.duelScreenshots = db.duelScreenshots.filter((s) => Number(s.duel_id) !== Number(duelId));
  db.duelScores = db.duelScores.filter((s) => Number(s.duel_id) !== Number(duelId));
  saveDb(db);
  return { deleted: true };
}

function upsertScoreInternal(db, { duelId, playerId, extractedName, score, scoreDate, source, screenshotId }) {
  const ts = nowIso();
  if (playerId !== null && playerId !== undefined) {
    const existing = db.duelScores.find(
      (s) =>
        Number(s.duel_id) === Number(duelId) &&
        String(s.score_date) === String(scoreDate) &&
        Number(s.player_id) === Number(playerId)
    );
    if (existing) {
      existing.extracted_name = extractedName;
      existing.score = Math.trunc(Number(score));
      existing.source = source;
      existing.screenshot_id = screenshotId;
      existing.updated_at = ts;
      return existing;
    }
  }
  const rec = {
    id: db.nextIds.score++,
    duel_id: Number(duelId),
    player_id: playerId !== null && playerId !== undefined ? Number(playerId) : null,
    extracted_name: extractedName,
    score: Math.trunc(Number(score)),
    score_date: String(scoreDate).slice(0, 10),
    screenshot_id: screenshotId || null,
    source,
    created_at: ts,
    updated_at: ts,
  };
  db.duelScores.push(rec);
  return rec;
}

export async function addScore(duelId, body) {
  const db = await ensureDb();
  if (!db.duels.some((d) => Number(d.id) === Number(duelId))) {
    throw makeError(404, "Düello bulunamadı.");
  }
  const pid = body.player_id !== null && body.player_id !== undefined ? Number(body.player_id) : null;
  const pObj = pid !== null ? db.players.find((p) => Number(p.id) === pid) : null;
  if (pid !== null && !pObj) throw makeError(422, "Seçilen oyuncu bulunamadı.");
  const extractedName = body.extracted_name ? String(body.extracted_name).trim() : pObj?.display_name || "";
  if (!extractedName) throw makeError(422, "Oyuncu seçin veya özel isim girin.");
  const scoreVal = Math.trunc(Number(body.score));
  if (!Number.isInteger(scoreVal) || scoreVal < 0) {
    throw makeError(422, "Puan sıfır veya pozitif tam sayı olmalıdır.");
  }
  const rec = upsertScoreInternal(db, {
    duelId,
    playerId: pid,
    extractedName,
    score: scoreVal,
    scoreDate: String(body.score_date || todayDate()).slice(0, 10),
    source: "manual",
    screenshotId: null,
  });
  saveDb(db);
  return { score: { ...rec, player_name: pObj?.display_name || null, ...evaluateScore(rec.score, db.activeDailyMinScore) } };
}

export async function updateScore(scoreId, body) {
  const db = await ensureDb();
  const s = db.duelScores.find((item) => Number(item.id) === Number(scoreId));
  if (!s) throw makeError(404, "Puan kaydı bulunamadı.");
  if (body.score !== undefined) {
    const val = Math.trunc(Number(body.score));
    if (!Number.isInteger(val) || val < 0) throw makeError(422, "Puan negatif olamaz.");
    s.score = val;
  }
  if (body.score_date !== undefined) s.score_date = String(body.score_date).slice(0, 10);
  if (body.extracted_name !== undefined) s.extracted_name = String(body.extracted_name).trim();
  s.updated_at = nowIso();
  saveDb(db);
  return { score: { ...s, ...evaluateScore(s.score, db.activeDailyMinScore) } };
}

export async function deleteScore(scoreId) {
  const db = await ensureDb();
  const idx = db.duelScores.findIndex((item) => Number(item.id) === Number(scoreId));
  if (idx === -1) throw makeError(404, "Puan kaydı bulunamadı.");
  db.duelScores.splice(idx, 1);
  saveDb(db);
  return { deleted: true };
}

// ---------------------------------------------------------------- Browser OCR + Screenshots

async function compressImageToDataUrl(file, maxWidth = 800, quality = 0.65) {
  return new Promise((resolve) => {
    const objUrl = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      try {
        const scale = img.width > maxWidth ? maxWidth / img.width : 1;
        const canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.round(img.width * scale));
        canvas.height = Math.max(1, Math.round(img.height * scale));
        const ctx = canvas.getContext("2d");
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        resolve(canvas.toDataURL("image/jpeg", quality));
      } catch {
        resolve(objUrl);
      } finally {
        if (objUrl.startsWith("blob:")) URL.revokeObjectURL(objUrl);
      }
    };
    img.onerror = () => resolve(objUrl);
    img.src = objUrl;
  });
}

async function runBrowserOcr(file) {
  if (typeof window === "undefined") return "";
  if (!window.Tesseract) {
    if (!tesseractPromise) {
      tesseractPromise = new Promise((resolve, reject) => {
        const s = document.createElement("script");
        s.src = TESSERACT_CDN;
        s.async = true;
        s.onload = () => resolve(window.Tesseract);
        s.onerror = () => reject(new Error("OCR library could not be loaded."));
        document.head.appendChild(s);
      });
    }
    try {
      await Promise.race([
        tesseractPromise,
        new Promise((_, rej) => setTimeout(() => rej(new Error("OCR timeout")), 15000)),
      ]);
    } catch {
      tesseractPromise = null;
      return "";
    }
  }
  try {
    const result = await window.Tesseract.recognize(file, "eng+tur");
    return String(result?.data?.text || "");
  } catch {
    return "";
  }
}

function matchPlayerInDb(db, candidateName) {
  const f = foldTr(candidateName);
  if (!f) return { matchedPlayerId: null, matchedPlayerName: null, matchStatus: "unmatched" };
  for (const p of db.players) {
    if (p.display_name === candidateName) {
      return { matchedPlayerId: p.id, matchedPlayerName: p.display_name, matchStatus: "exact" };
    }
  }
  for (const a of db.playerAliases) {
    if (foldTr(a.alias_name) === f) {
      const owner = db.players.find((p) => Number(p.id) === Number(a.player_id));
      if (owner) return { matchedPlayerId: owner.id, matchedPlayerName: owner.display_name, matchStatus: "alias" };
    }
  }
  for (const p of db.players) {
    if (foldTr(p.display_name) === f) {
      return { matchedPlayerId: p.id, matchedPlayerName: p.display_name, matchStatus: "case_insensitive" };
    }
  }
  return { matchedPlayerId: null, matchedPlayerName: null, matchStatus: "unmatched" };
}

function parseScoreToken(raw) {
  const s = String(raw || "").trim().toUpperCase();
  const m = s.match(/^(\d+(?:[.,]\d+)?)\s*([KM]?)$/);
  if (!m) return null;
  let numStr = m[1];
  const suffix = m[2];
  if (suffix) {
    const n = Number(numStr.replace(",", "."));
    if (!Number.isFinite(n)) return null;
    return Math.round(n * (suffix === "M" ? 1_000_000 : 1_000));
  }
  numStr = numStr.replace(/[.,]/g, "");
  const n = Number(numStr);
  return Number.isInteger(n) ? n : null;
}

export async function extractPlayersFromPhoto(file) {
  const db = await ensureDb();
  const rawText = await runBrowserOcr(file);
  const candidates = [];
  const seen = new Set();

  for (const line of rawText.split(/\r?\n/)) {
    let cleaned = line.trim();
    if (cleaned.length < 2) continue;
    const rankMatch = cleaned.match(/\b(R[1-5])\b/i);
    const towerMatch = cleaned.match(/\b([Iİı]10|[Iİı][1-9])\b/);
    const detectedRank = rankMatch ? rankMatch[1].toUpperCase() : null;
    const detectedTowerLevel = towerMatch
      ? towerMatch[1].replaceAll("ı", "I").replaceAll("İ", "I").toUpperCase()
      : null;
    if (rankMatch) cleaned = cleaned.replace(rankMatch[0], " ");
    if (towerMatch) cleaned = cleaned.replace(towerMatch[0], " ");
    cleaned = cleaned.replace(/^\d+[.)\s-]+/, "").replace(/^\[[^\]]+\]\s*/, "").replace(/\s+/g, " ").trim();
    if (!cleaned || /^\d+$/.test(cleaned)) continue;
    const f = foldTr(cleaned);
    if (seen.has(f)) continue;
    seen.add(f);
    const match = matchPlayerInDb(db, cleaned);
    candidates.push({
      extractedName: line.trim(),
      cleanName: cleaned,
      suggestedAlias: "",
      detectedNumber: null,
      detectedRank,
      detectedTowerLevel,
      alreadyExists: match.matchedPlayerId !== null,
      matchedPlayerId: match.matchedPlayerId,
      matchedPlayerName: match.matchedPlayerName,
      matchStatus: match.matchedPlayerId !== null ? match.matchStatus : "unmatched",
      needsReview: false,
      warnings: [],
    });
  }

  return {
    candidates,
    rawText,
    warnings: candidates.length === 0 ? ["NO_PLAYERS_DETECTED"] : [],
  };
}

export async function extractScreenshot(duelId, file, scoreDate) {
  const db = await ensureDb();
  if (!db.duels.some((d) => Number(d.id) === Number(duelId))) {
    throw makeError(404, "Düello bulunamadı.");
  }
  const cleanDate = String(scoreDate || todayDate()).slice(0, 10);
  const [rawText, imageUrl] = await Promise.all([
    runBrowserOcr(file),
    compressImageToDataUrl(file),
  ]);

  const parsedRows = [];
  rawText.split(/\r?\n/).forEach((line, idx) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    const m = trimmed.match(/^(?:\d+[.)\s]+)?(.+?)\s+([0-9][0-9.,]*\s*[KMkm]?)$/);
    if (!m) return;
    const name = m[1].trim();
    const score = parseScoreToken(m[2]);
    if (!name || score === null) return;
    const match = matchPlayerInDb(db, name);
    parsedRows.push({
      tempId: `row-${idx + 1}`,
      extractedName: name,
      extractedScore: score,
      matchedPlayerId: match.matchedPlayerId,
      matchStatus: match.matchStatus,
      needsReview: match.matchedPlayerId === null,
      warnings: match.matchedPlayerId === null ? ["unmatched_player"] : [],
    });
  });

  const shot = {
    id: db.nextIds.screenshot++,
    duel_id: Number(duelId),
    score_date: cleanDate,
    original_filename: file?.name || "screenshot.jpg",
    status: "pending_review",
    uploaded_at: nowIso(),
    row_count: parsedRows.length,
    imageUrl,
  };
  db.duelScreenshots.push(shot);
  saveDb(db);

  return {
    screenshotId: shot.id,
    imageUrl: shot.imageUrl,
    scoreDate: cleanDate,
    rawText,
    parsedRows,
    passUsed: rawText ? "tesseract-js" : null,
    warnings: parsedRows.length === 0 ? ["NO_LEADERBOARD_ROWS_DETECTED"] : [],
  };
}

export async function commitScreenshot(duelId, screenshotId, body) {
  const db = await ensureDb();
  const shot = db.duelScreenshots.find(
    (s) => Number(s.id) === Number(screenshotId) && Number(s.duel_id) === Number(duelId)
  );
  if (!shot) throw makeError(404, "Ekran görüntüsü bulunamadı.");

  const cleanDate = String(body?.score_date || shot.score_date || todayDate()).slice(0, 10);
  const rows = Array.isArray(body?.rows) ? body.rows : [];
  if (rows.length === 0) throw makeError(422, "Kaydedilecek en az bir satır olmalıdır.");

  const savedScores = [];
  const createdPlayers = [];
  const warnings = [];
  const playerMap = new Map(db.players.map((p) => [Number(p.id), p]));

  for (const row of rows) {
    const name = String(row.extractedName || "").trim();
    let pid = row.playerId !== null && row.playerId !== undefined ? Number(row.playerId) : null;
    if (row.createPlayer && pid === null) {
      try {
        const res = await createPlayer({ display_name: name });
        pid = res.player.id;
        playerMap.set(Number(pid), res.player);
        createdPlayers.push(res.player);
      } catch (err) {
        warnings.push(`${name}: ${err.message}`);
      }
    } else if (pid !== null && row.saveAlias) {
      const owner = playerMap.get(pid);
      if (owner && foldTr(owner.display_name) !== foldTr(name)) {
        try {
          await addAlias(pid, name);
        } catch (err) {
          warnings.push(`${name}: ${err.message}`);
        }
      }
    }
    const saved = upsertScoreInternal(db, {
      duelId,
      playerId: pid,
      extractedName: name,
      score: row.score,
      scoreDate: cleanDate,
      source: "ocr",
      screenshotId: shot.id,
    });
    const pObj = pid !== null ? playerMap.get(pid) : null;
    savedScores.push({
      ...saved,
      player_name: pObj?.display_name || null,
      ...evaluateScore(saved.score, db.activeDailyMinScore),
    });
  }

  shot.status = "committed";
  shot.score_date = cleanDate;
  shot.row_count = rows.length;
  saveDb(db);

  const evaluated = await evaluateLimits({ duelId, date: cleanDate });
  return {
    savedScores,
    createdPlayers,
    evaluatedDailySummaries: evaluated.evaluations,
    warnings,
  };
}

// ---------------------------------------------------------------- Weekly Diff

function parseScoreRowsFromRawText(db, rawText) {
  const rows = [];
  String(rawText || "").split(/\r?\n/).forEach((line, idx) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    const m = trimmed.match(/^(?:\d+[.)\s]+)?(.+?)\s+([0-9][0-9.,]*\s*[KMkm]?)$/);
    if (!m) return;
    const name = m[1].trim();
    const score = parseScoreToken(m[2]);
    if (!name || score === null) return;
    const match = matchPlayerInDb(db, name);
    rows.push({
      tempId: `row-${idx + 1}`,
      extractedName: name,
      cleanName: name,
      extractedScore: score,
      ocrConfidence: 0.9,
      matchedPlayerId: match.matchedPlayerId,
      matchedPlayerName: match.matchedPlayerName,
      matchStatus: match.matchStatus,
      needsReview: match.matchedPlayerId === null,
      warnings: match.matchedPlayerId === null ? ["unmatched_player"] : [],
    });
  });
  return rows;
}

function mergeBatchRowsStatic(batches) {
  const merged = new Map();
  const order = [];
  for (const batch of batches) {
    for (const raw of batch) {
      const key =
        raw.matchedPlayerId !== null && raw.matchedPlayerId !== undefined
          ? `id:${raw.matchedPlayerId}`
          : `name:${foldTr(raw.cleanName || raw.extractedName)}`;
      if (!merged.has(key)) {
        merged.set(key, { ...raw, warnings: [...(raw.warnings || [])] });
        order.push(key);
        continue;
      }
      const ex = merged.get(key);
      if (ex.extractedScore !== raw.extractedScore) {
        ex.extractedScore = Math.max(ex.extractedScore, raw.extractedScore);
        ex.needsReview = true;
        if (!ex.warnings.includes("conflicting_duplicate_in_batch")) {
          ex.warnings.push("conflicting_duplicate_in_batch");
        }
      }
    }
  }
  return order.map((k) => merged.get(k));
}

export async function previewWeeklyDiff(duelId, formData) {
  const db = await ensureDb();
  const detail = await getDuel(duelId);
  const targetDate = String(formData.get("target_date") || todayDate()).slice(0, 10);
  const rawToday = formData.get("today_date");
  const todayDateVal = rawToday ? String(rawToday).slice(0, 10) : null;
  const rawPrev = formData.get("included_previous_dates");

  let selectedPrevDates = [];
  if (rawPrev && String(rawPrev).trim()) {
    try {
      const parsed = JSON.parse(String(rawPrev));
      if (Array.isArray(parsed)) selectedPrevDates = parsed.map((d) => String(d).slice(0, 10));
    } catch {
      selectedPrevDates = [];
    }
  } else {
    selectedPrevDates = (detail.recordedDates || [])
      .map((d) => d.scoreDate)
      .filter((d) => d < targetDate);
  }

  const wFiles = formData.getAll("weekly_files").filter((f) => f && f.size > 0);
  const tFiles = formData.getAll("today_files").filter((f) => f && f.size > 0);
  const wBatches = [];
  const tBatches = [];
  const wRaws = [];
  const tRaws = [];

  for (const f of wFiles) {
    const txt = await runBrowserOcr(f);
    if (txt) wRaws.push(`[${f.name}]\n${txt}`);
    wBatches.push(parseScoreRowsFromRawText(db, txt));
  }
  for (const f of tFiles) {
    const txt = await runBrowserOcr(f);
    if (txt) tRaws.push(`[${f.name}]\n${txt}`);
    tBatches.push(parseScoreRowsFromRawText(db, txt));
  }

  const weeklyRows = mergeBatchRowsStatic(wBatches);
  const todayRows = mergeBatchRowsStatic(tBatches);

  const prevSet = new Set(selectedPrevDates);
  const prevByPlayer = {};
  const prevByName = {};
  for (const s of db.duelScores) {
    if (Number(s.duel_id) !== Number(duelId)) continue;
    if (!prevSet.has(String(s.score_date))) continue;
    const val = Math.trunc(Number(s.score || 0));
    if (s.player_id !== null && s.player_id !== undefined) {
      const k = String(s.player_id);
      prevByPlayer[k] = (prevByPlayer[k] || 0) + val;
    } else {
      const fn = foldTr(s.extracted_name);
      prevByName[fn] = (prevByName[fn] || 0) + val;
    }
  }

  const wMap = new Map();
  const tMap = new Map();
  const ordered = [];
  const keyOf = (r) =>
    r.matchedPlayerId !== null && r.matchedPlayerId !== undefined
      ? `id:${r.matchedPlayerId}`
      : `name:${foldTr(r.cleanName || r.extractedName)}`;

  for (const w of weeklyRows) {
    const k = keyOf(w);
    if (!wMap.has(k)) {
      wMap.set(k, w);
      ordered.push(k);
    }
  }
  for (const t of todayRows) {
    const k = keyOf(t);
    if (!tMap.has(k)) tMap.set(k, t);
    if (!wMap.has(k) && !ordered.includes(k)) ordered.push(k);
  }

  const rows = ordered.map((k, idx) => {
    const w = wMap.get(k);
    const tRow = tMap.get(k);
    const ref = w || tRow;
    const pid = ref.matchedPlayerId !== null && ref.matchedPlayerId !== undefined ? Number(ref.matchedPlayerId) : null;
    const wVal = w ? Math.trunc(Number(w.extractedScore || 0)) : 0;
    const tVal = tRow ? Math.trunc(Number(tRow.extractedScore || 0)) : 0;
    const prevSum = pid !== null ? prevByPlayer[String(pid)] || 0 : prevByName[foldTr(ref.extractedName)] || 0;
    const derived = wVal - tVal - prevSum;
    const warns = [...new Set([...(w?.warnings || []), ...(tRow?.warnings || [])])];
    if (!w) warns.push("missing_from_weekly");
    else if (!tRow) warns.push("missing_today_score");
    if (derived < 0) warns.push("negative_derived_score");

    return {
      tempId: `diff-${idx + 1}`,
      extractedName: ref.extractedName,
      cleanName: ref.cleanName || ref.extractedName,
      matchedPlayerId: pid,
      matchedPlayerName: ref.matchedPlayerName || null,
      matchStatus: ref.matchStatus || "unmatched",
      weeklyTotal: wVal,
      todayLiveScore: tVal,
      previousDaysSum: prevSum,
      derivedScore: derived,
      needsReview: derived < 0 || pid === null || !w,
      warnings: warns,
    };
  });

  const recSet = new Set((detail.recordedDates || []).map((d) => d.scoreDate));
  const missingCalendarDates = [];
  if (detail.duel?.start_date && detail.duel.start_date < targetDate) {
    const cur = new Date(`${detail.duel.start_date}T00:00:00Z`);
    const end = new Date(`${targetDate}T00:00:00Z`);
    for (let i = 0; i < 31 && cur < end; i += 1) {
      const iso = cur.toISOString().slice(0, 10);
      if (!recSet.has(iso)) missingCalendarDates.push(iso);
      cur.setUTCDate(cur.getUTCDate() + 1);
    }
  }

  return {
    targetDate,
    todayDate: todayDateVal,
    includedPreviousDates: selectedPrevDates,
    availablePreviousDates: detail.recordedDates || [],
    previousSumsByPlayer: prevByPlayer,
    missingCalendarDates,
    rows,
    weeklyRawText: wRaws.join("\n\n"),
    todayRawText: tRaws.join("\n\n"),
    warnings: [],
  };
}

export async function commitWeeklyDiff(duelId, body) {
  const db = await ensureDb();
  if (!db.duels.some((d) => Number(d.id) === Number(duelId))) {
    throw makeError(404, "Düello bulunamadı.");
  }
  const targetDate = String(body?.target_date || "").slice(0, 10);
  const todayDateVal = body?.today_date ? String(body.today_date).slice(0, 10) : null;
  const saveToday = Boolean(body?.save_today_scores);
  const prevDates = Array.isArray(body?.included_previous_dates) ? body.included_previous_dates : [];
  const rows = Array.isArray(body?.rows) ? body.rows : [];
  if (rows.length === 0) throw makeError(422, "Kaydedilecek en az bir satır olmalıdır.");

  const savedScores = [];
  const createdPlayers = [];
  const warnings = [];
  let savedTodayCount = 0;
  const playerMap = new Map(db.players.map((p) => [Number(p.id), p]));

  for (const row of rows) {
    const derived = Math.trunc(Number(row.derivedScore));
    if (!Number.isInteger(derived) || derived < 0) {
      throw makeError(422, "Puan negatif olamaz.");
    }
    const name = String(row.extractedName || "").trim();
    let pid = row.playerId !== null && row.playerId !== undefined ? Number(row.playerId) : null;
    if (row.createPlayer && pid === null) {
      try {
        const res = await createPlayer({ display_name: name });
        pid = res.player.id;
        playerMap.set(Number(pid), res.player);
        createdPlayers.push(res.player);
      } catch (err) {
        warnings.push(`${name}: ${err.message}`);
      }
    } else if (pid !== null && row.saveAlias) {
      const owner = playerMap.get(pid);
      if (owner && foldTr(owner.display_name) !== foldTr(name)) {
        try {
          await addAlias(pid, name);
        } catch (err) {
          warnings.push(`${name}: ${err.message}`);
        }
      }
    }

    const saved = upsertScoreInternal(db, {
      duelId,
      playerId: pid,
      extractedName: name,
      score: derived,
      scoreDate: targetDate,
      source: row.weeklyTotal > 0 || row.todayLiveScore > 0 ? "ocr" : "manual",
      screenshotId: null,
    });
    saved.calculationMeta = {
      method: "weekly_diff",
      weeklyTotal: Math.trunc(Number(row.weeklyTotal || 0)),
      todayLiveScore: Math.trunc(Number(row.todayLiveScore || 0)),
      previousDaysSum: Math.trunc(Number(row.previousDaysSum || 0)),
      previousDates: prevDates,
    };
    const pObj = pid !== null ? playerMap.get(pid) : null;
    savedScores.push({
      ...saved,
      player_name: pObj?.display_name || null,
      ...evaluateScore(saved.score, db.activeDailyMinScore),
    });

    if (saveToday && todayDateVal && Number(row.todayLiveScore || 0) > 0) {
      upsertScoreInternal(db, {
        duelId,
        playerId: pid,
        extractedName: name,
        score: Math.trunc(Number(row.todayLiveScore)),
        scoreDate: todayDateVal,
        source: "ocr",
        screenshotId: null,
      });
      savedTodayCount += 1;
    }
  }

  saveDb(db);
  const evaluated = await evaluateLimits({ duelId, date: targetDate });
  return {
    savedScores,
    savedTodayCount,
    createdPlayers,
    evaluatedDailySummaries: evaluated.evaluations,
    warnings,
  };
}

// ---------------------------------------------------------------- Backup / Restore / Reset

export async function exportBackupJson() {
  const db = await ensureDb();
  return JSON.stringify(db, null, 2);
}

export async function importBackupJson(rawText) {
  let parsed;
  try {
    parsed = JSON.parse(String(rawText || ""));
  } catch {
    throw makeError(422, "Geçersiz JSON.");
  }
  if (!parsed || typeof parsed !== "object" || !Array.isArray(parsed.players)) {
    throw makeError(422, "Geçersiz yedek yapısı.");
  }
  const normalized = normalizeDb(parsed);
  saveDb(normalized);
  return { ok: true, clanName: normalized.auth.clanName };
}

export async function resetToSeed() {
  const seeded = await fetchSeedData();
  saveDb(seeded);
  return { ok: true, clanName: seeded.auth.clanName };
}
