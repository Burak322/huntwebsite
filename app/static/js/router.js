import {
  escapeHtml,
  getAuthStatus,
  isStaticMode,
  logoutAdmin,
  setUnauthorizedHandler,
} from "./api.js";
import {
  applyDocumentLocale,
  getLanguage,
  onLanguageChange,
  renderLanguageSelect,
  t,
  wireLanguageSelect,
} from "./i18n/index.js";
import { renderNavLayout } from "./components/nav.js";
import { renderDashboardPage } from "./pages/dashboardPage.js";
import { renderDuelDetailPage } from "./pages/duelDetailPage.js";
import { renderDuelsPage } from "./pages/duelsPage.js";
import { renderLoginPage } from "./pages/loginPage.js";
import { renderPlayerDetailPage } from "./pages/playerDetailPage.js";
import { renderPlayersPage } from "./pages/playersPage.js";
import { renderSettingsPage } from "./pages/settingsPage.js";
import { renderSetupPage } from "./pages/setupPage.js";

const appRoot = document.getElementById("app");

let authState = {
  needsSetup: false,
  authenticated: false,
  admin: null,
  clanName: "",
};
let bootFailed = false;

function normalizePath(pathname) {
  if (!pathname || pathname === "/") {
    return "/";
  }
  return pathname.endsWith("/") ? pathname.slice(0, -1) : pathname;
}

function getCurrentPath() {
  if (isStaticMode()) {
    const rawHash = window.location.hash || "";
    const stripped = rawHash.startsWith("#") ? rawHash.slice(1) : rawHash;
    return normalizePath(stripped.startsWith("/") ? stripped : `/${stripped}`);
  }
  return normalizePath(window.location.pathname);
}

function setRoutePath(targetPath, { replace = false } = {}) {
  const normalized = normalizePath(targetPath);
  if (isStaticMode()) {
    const targetHash = `#${normalized}`;
    if (window.location.hash !== targetHash) {
      if (replace) {
        window.history.replaceState({}, "", targetHash);
      } else {
        window.location.hash = targetHash;
      }
    }
    return;
  }
  if (normalizePath(window.location.pathname) !== normalized) {
    if (replace) {
      window.history.replaceState({}, "", normalized);
    } else {
      window.history.pushState({}, "", normalized);
    }
  }
}

function renderPlaceholderSection(container, { title, description }) {
  container.innerHTML = `
    <div class="page-header">
      <h1>${escapeHtml(title)}</h1>
      <span class="badge badge-gold">${escapeHtml(t("common.preparing"))}</span>
    </div>
    <section class="card">
      <p style="margin: 0; color: var(--text-muted);">${escapeHtml(description)}</p>
    </section>
  `;
}

function renderBootError() {
  appRoot.innerHTML = `
    <div class="auth-wrapper">
      <section class="auth-card">
        <div class="auth-lang-bar">
          ${renderLanguageSelect({ id: "boot-lang-select", testId: "lang-select" })}
        </div>
        <div class="alert alert-error" role="alert">
          ${escapeHtml(t("boot.connectionError"))}
        </div>
      </section>
    </div>
  `;
  wireLanguageSelect(appRoot);
}

export function navigate(targetPath, { replace = false } = {}) {
  setRoutePath(targetPath, { replace });
  renderRoute();
}

async function handleLogout() {
  try {
    await logoutAdmin();
  } catch {
    // Ignore errors during logout and clear local auth state
  }
  authState = {
    ...authState,
    authenticated: false,
    admin: null,
  };
  navigate("/login", { replace: true });
}

function renderRoute() {
  const path = getCurrentPath();

  if (authState.needsSetup) {
    if (path !== "/setup") {
      setRoutePath("/setup", { replace: true });
    }
    renderSetupPage(appRoot, {
      authState,
      onSuccess: async (data) => {
        authState = {
          needsSetup: false,
          authenticated: true,
          admin: data.admin,
          clanName: data.clanName || t("common.defaultClanName"),
        };
        navigate("/", { replace: true });
      },
    });
    return;
  }

  if (!authState.authenticated) {
    if (path !== "/login") {
      setRoutePath("/login", { replace: true });
    }
    renderLoginPage(appRoot, {
      authState,
      onSuccess: async (data) => {
        authState = {
          needsSetup: false,
          authenticated: true,
          admin: data.admin,
          clanName: data.clanName || authState.clanName,
        };
        navigate("/", { replace: true });
      },
    });
    return;
  }

  if (path === "/setup" || path === "/login") {
    setRoutePath("/", { replace: true });
    renderAuthenticatedView("/");
    return;
  }

  renderAuthenticatedView(path);
}

function renderAuthenticatedView(path) {
  const pageContent = renderNavLayout(appRoot, {
    authState,
    currentPath: path,
    onNavigate: (target) => navigate(target),
    onLogout: handleLogout,
  });

  if (path === "/") {
    renderDashboardPage(pageContent, {
      authState,
      onNavigate: (target) => navigate(target),
    });
    return;
  }

  if (path === "/players") {
    renderPlayersPage(pageContent, {
      onNavigate: (target) => navigate(target),
    });
    return;
  }

  const playerMatch = path.match(/^\/players\/(\d+)$/);
  if (playerMatch) {
    renderPlayerDetailPage(pageContent, {
      playerId: Number(playerMatch[1]),
      onNavigate: (target) => navigate(target),
    });
    return;
  }

  if (path === "/duels") {
    renderDuelsPage(pageContent, {
      onNavigate: (target) => navigate(target),
    });
    return;
  }

  const duelMatch = path.match(/^\/duels\/(\d+)$/);
  if (duelMatch) {
    renderDuelDetailPage(pageContent, {
      duelId: Number(duelMatch[1]),
      onNavigate: (target) => navigate(target),
    });
    return;
  }

  if (path === "/settings") {
    renderSettingsPage(pageContent, {
      authState,
      onClanNameChange: (newName) => {
        authState = { ...authState, clanName: newName || t("common.defaultClanName") };
        renderRoute();
      },
    });
    return;
  }

  renderPlaceholderSection(pageContent, {
    title: t("router.notFoundTitle"),
    description: t("router.notFoundDescription"),
  });
}

async function boot() {
  applyDocumentLocale(getLanguage());

  onLanguageChange(() => {
    if (bootFailed) {
      renderBootError();
    } else {
      renderRoute();
    }
  });

  setUnauthorizedHandler(() => {
    authState = {
      ...authState,
      authenticated: false,
      admin: null,
    };
    navigate("/login", { replace: true });
  });

  window.addEventListener("popstate", () => {
    renderRoute();
  });
  if (isStaticMode()) {
    window.addEventListener("hashchange", () => {
      renderRoute();
    });
  }

  try {
    authState = await getAuthStatus();
    bootFailed = false;
  } catch {
    bootFailed = true;
    renderBootError();
    return;
  }

  renderRoute();
}

boot();
