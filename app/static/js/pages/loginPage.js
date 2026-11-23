import { escapeHtml, loginAdmin } from "../api.js";
import { renderLanguageSelect, t, wireLanguageSelect } from "../i18n/index.js";

export function renderLoginPage(root, { authState, onSuccess }) {
  const clanName = authState.clanName || t("common.defaultClanName");

  root.innerHTML = `
    <div class="auth-wrapper">
      <section class="auth-card">
        <div class="auth-lang-bar">
          ${renderLanguageSelect({ id: "auth-lang-select", testId: "lang-select", className: "lang-select" })}
        </div>
        <div class="auth-header">
          <span class="auth-badge">${escapeHtml(t("auth.login.badge"))}</span>
          <h1>${escapeHtml(t("auth.login.title"))}</h1>
          <p class="auth-subtitle">${escapeHtml(t("auth.login.subtitle", { clanName }))}</p>
        </div>

        <div
          id="login-error"
          class="alert alert-error hidden"
          role="alert"
          data-testid="login-error"
        ></div>

        <form id="login-form" class="form-stack">
          <div class="form-field">
            <label for="login-username">${escapeHtml(t("auth.login.usernameLabel"))}</label>
            <input
              id="login-username"
              name="username"
              type="text"
              required
              autocomplete="username"
              placeholder="${escapeHtml(t("auth.login.usernamePlaceholder"))}"
            >
          </div>

          <div class="form-field">
            <label for="login-password">${escapeHtml(t("auth.login.passwordLabel"))}</label>
            <input
              id="login-password"
              name="password"
              type="password"
              required
              autocomplete="current-password"
              placeholder="${escapeHtml(t("auth.login.passwordPlaceholder"))}"
            >
          </div>

          <button type="submit" class="btn btn-primary" data-testid="login-submit">
            ${escapeHtml(t("auth.login.submitBtn"))}
          </button>
        </form>
      </section>
    </div>
  `;

  wireLanguageSelect(root);

  const form = root.querySelector("#login-form");
  const errorBox = root.querySelector('[data-testid="login-error"]');
  const submitBtn = root.querySelector('[data-testid="login-submit"]');

  function showError(message) {
    errorBox.textContent = message;
    errorBox.classList.remove("hidden");
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorBox.classList.add("hidden");
    errorBox.textContent = "";

    const formData = new FormData(form);
    const username = String(formData.get("username") || "").trim();
    const password = String(formData.get("password") || "");

    if (!username || !password) {
      showError(t("auth.login.errMissingCredentials"));
      return;
    }

    submitBtn.disabled = true;
    try {
      const data = await loginAdmin({ username, password });
      await onSuccess(data);
    } catch (err) {
      showError(err.message || t("auth.login.errFailed"));
    } finally {
      submitBtn.disabled = false;
    }
  });
}
