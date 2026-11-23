import { escapeHtml } from "../api.js";
import { renderLanguageSelect, t, wireLanguageSelect } from "../i18n/index.js";

const NAV_ITEMS = [
  { href: "/", labelKey: "nav.dashboard", testId: "nav-dashboard", match: (p) => p === "/" },
  {
    href: "/players",
    labelKey: "nav.players",
    testId: "nav-players",
    match: (p) => p === "/players" || p.startsWith("/players/"),
  },
  {
    href: "/duels",
    labelKey: "nav.duels",
    testId: "nav-duels",
    match: (p) => p === "/duels" || p.startsWith("/duels/"),
  },
  {
    href: "/settings",
    labelKey: "nav.settings",
    testId: "nav-settings",
    match: (p) => p === "/settings",
  },
];

export function renderNavLayout(root, { authState, currentPath, onNavigate, onLogout }) {
  const safeClanName = escapeHtml(authState.clanName || t("common.defaultClanName"));
  const adminUsername = authState.admin?.username || t("common.defaultAdminName");

  const navLinksHtml = NAV_ITEMS.map((item) => {
    const activeClass = item.match(currentPath) ? "active" : "";
    return `
      <a
        href="${item.href}"
        data-link
        data-testid="${item.testId}"
        class="nav-link ${activeClass}"
      >${escapeHtml(t(item.labelKey))}</a>
    `;
  }).join("");

  root.innerHTML = `
    <div class="app-shell">
      <aside class="sidebar">
        <div class="brand">
          <p class="brand-title">${safeClanName}</p>
          <p class="brand-subtitle">${escapeHtml(t("app.title"))}</p>
        </div>
        <nav class="nav-list" aria-label="${escapeHtml(t("nav.mainMenuAria"))}">
          ${navLinksHtml}
        </nav>
      </aside>
      <div class="main-area">
        <header class="topbar">
          <div class="topbar-clan">${safeClanName}</div>
          <div class="topbar-actions">
            ${renderLanguageSelect({ id: "topbar-lang-select", testId: "lang-select", className: "lang-select" })}
            <span class="admin-pill">${escapeHtml(t("nav.adminPill", { username: adminUsername }))}</span>
            <button type="button" class="btn btn-danger-outline" data-testid="logout-btn">
              ${escapeHtml(t("nav.logoutBtn"))}
            </button>
          </div>
        </header>
        <main id="page-content" class="page-content"></main>
      </div>
    </div>
  `;

  wireLanguageSelect(root);

  root.querySelectorAll("[data-link]").forEach((anchor) => {
    anchor.addEventListener("click", (event) => {
      event.preventDefault();
      const target = anchor.getAttribute("href") || "/";
      onNavigate(target);
    });
  });

  const logoutBtn = root.querySelector('[data-testid="logout-btn"]');
  if (logoutBtn) {
    logoutBtn.addEventListener("click", async () => {
      logoutBtn.disabled = true;
      await onLogout();
    });
  }

  return root.querySelector("#page-content");
}
