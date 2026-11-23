import ar from "./locales/ar.js";
import en from "./locales/en.js";
import it from "./locales/it.js";
import tr from "./locales/tr.js";

export const LANG_STORAGE_KEY = "clan_ui_lang";
export const SUPPORTED_LANGS = ["tr", "en", "ar", "it"];

export const LANGUAGE_META = {
  tr: { code: "tr", nativeName: "Türkçe", dir: "ltr", intlLocale: "tr-TR" },
  en: { code: "en", nativeName: "English", dir: "ltr", intlLocale: "en-US" },
  ar: { code: "ar", nativeName: "العربية", dir: "rtl", intlLocale: "ar-u-nu-latn" },
  it: { code: "it", nativeName: "Italiano", dir: "ltr", intlLocale: "it-IT" },
};

const DICTS = { tr, en, ar, it };

const BACKEND_ERROR_KEY_MAP = {
  "Kullanıcı adı veya şifre hatalı.": "apiErrors.invalidCredentials",
  "Mevcut şifre hatalı.": "apiErrors.invalidCurrentPassword",
  "Yetkisiz erişim. Lütfen giriş yapın.": "apiErrors.unauthorized",
  "Oturum geçersiz veya süresi dolmuş.": "apiErrors.sessionExpired",
  "Yönetici hesabı zaten oluşturulmuş.": "apiErrors.adminAlreadyExists",
  "Dosya çok büyük (en fazla 15 MB).": "apiErrors.fileTooLarge",
  "Görüntü dosyası bulunamadı.": "apiErrors.imageNotFound",
  NO_LEADERBOARD_ROWS_DETECTED: "apiErrors.noLeaderboardRows",
  NO_PLAYERS_DETECTED: "apiErrors.noPlayersDetected",
};

const listeners = new Set();

function escapeAttr(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function normalizeLang(lang) {
  return SUPPORTED_LANGS.includes(lang) ? lang : "tr";
}

function loadInitialLang() {
  try {
    const stored = window.localStorage.getItem(LANG_STORAGE_KEY);
    return normalizeLang(stored);
  } catch {
    return "tr";
  }
}

let currentLang = loadInitialLang();

export function getLanguage() {
  return currentLang;
}

export function getLanguageMeta(lang = currentLang) {
  return LANGUAGE_META[normalizeLang(lang)] || LANGUAGE_META.tr;
}

export function getIntlLocale(lang = currentLang) {
  return getLanguageMeta(lang).intlLocale;
}

export function isRtl(lang = currentLang) {
  return getLanguageMeta(lang).dir === "rtl";
}

export function t(key, params = {}) {
  const dict = DICTS[currentLang] || DICTS.tr;
  const fallback = DICTS.tr;
  let template = Object.prototype.hasOwnProperty.call(dict, key)
    ? dict[key]
    : Object.prototype.hasOwnProperty.call(fallback, key)
      ? fallback[key]
      : key;

  if (params && typeof params === "object") {
    template = String(template).replace(/\{(\w+)\}/g, (_, name) =>
      Object.prototype.hasOwnProperty.call(params, name) &&
      params[name] !== null &&
      params[name] !== undefined
        ? String(params[name])
        : `{${name}}`
    );
  }
  return template;
}

export function translateApiMessage(message) {
  if (typeof message !== "string") return message;
  const mappedKey = BACKEND_ERROR_KEY_MAP[message];
  if (mappedKey) {
    return t(mappedKey);
  }
  return message;
}

export function applyDocumentLocale(lang = currentLang) {
  const meta = getLanguageMeta(lang);
  if (typeof document !== "undefined" && document.documentElement) {
    document.documentElement.lang = meta.code;
    document.documentElement.dir = meta.dir;
    document.title = t("app.title");
  }
}

export function setLanguage(lang) {
  const next = normalizeLang(lang);
  const changed = next !== currentLang;
  currentLang = next;
  try {
    window.localStorage.setItem(LANG_STORAGE_KEY, next);
  } catch {
    // Ignore storage errors in restricted contexts
  }
  applyDocumentLocale(next);
  if (changed) {
    listeners.forEach((fn) => {
      try {
        fn(next);
      } catch {
        // Ignore listener errors so other listeners continue
      }
    });
  }
  return next;
}

export function onLanguageChange(fn) {
  if (typeof fn !== "function") return () => {};
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function renderLanguageSelect({
  id = "lang-select",
  testId = "lang-select",
  className = "lang-select",
} = {}) {
  const cur = getLanguage();
  const optionsHtml = SUPPORTED_LANGS.map((code) => {
    const meta = LANGUAGE_META[code];
    const sel = cur === code ? "selected" : "";
    return `<option value="${escapeAttr(code)}" ${sel}>${escapeAttr(meta.nativeName)}</option>`;
  }).join("");

  return `
    <select
      id="${escapeAttr(id)}"
      class="${escapeAttr(className)}"
      data-testid="${escapeAttr(testId)}"
      aria-label="${escapeAttr(t("lang.label"))}"
    >
      ${optionsHtml}
    </select>
  `;
}

export function wireLanguageSelect(root, selector = '[data-testid="lang-select"]') {
  if (!root) return;
  root.querySelectorAll(selector).forEach((el) => {
    el.value = getLanguage();
    el.addEventListener("change", () => {
      setLanguage(el.value);
    });
  });
}

applyDocumentLocale(currentLang);
