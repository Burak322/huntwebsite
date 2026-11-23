import { escapeHtml, setupAdmin } from "../api.js";
import { renderLanguageSelect, t, wireLanguageSelect } from "../i18n/index.js";

export function renderSetupPage(root, { authState, onSuccess }) {
  const defaultClanName = escapeHtml(authState.clanName || t("common.defaultClanName"));

  root.innerHTML = `
    <div class="auth-wrapper">
      <section class="auth-card">
        <div class="auth-lang-bar">
          ${renderLanguageSelect({ id: "auth-lang-select", testId: "lang-select", className: "lang-select" })}
        </div>
        <div class="auth-header">
          <span class="auth-badge">${escapeHtml(t("auth.setup.badge"))}</span>
          <h1>${escapeHtml(t("auth.setup.title"))}</h1>
          <p class="auth-subtitle">${escapeHtml(t("auth.setup.subtitle"))}</p>
        </div>

        <div
          id="setup-error"
          class="alert alert-error hidden"
          role="alert"
          data-testid="setup-error"
        ></div>

        <form id="setup-form" class="form-stack">
          <div class="form-field">
            <label for="setup-clan-name">${escapeHtml(t("auth.setup.clanNameLabel"))}</label>
            <input
              id="setup-clan-name"
              name="clanName"
              type="text"
              value="${defaultClanName}"
              maxlength="80"
              placeholder="${escapeHtml(t("common.defaultClanName"))}"
            >
          </div>

          <div class="form-field">
            <label for="setup-username">${escapeHtml(t("auth.setup.usernameLabel"))}</label>
            <input
              id="setup-username"
              name="username"
              type="text"
              required
              maxlength="64"
              autocomplete="username"
              placeholder="${escapeHtml(t("auth.setup.usernamePlaceholder"))}"
            >
          </div>

          <div class="form-field">
            <label for="setup-password">${escapeHtml(t("auth.setup.passwordLabel"))}</label>
            <input
              id="setup-password"
              name="password"
              type="password"
              required
              minlength="6"
              maxlength="256"
              autocomplete="new-password"
              placeholder="${escapeHtml(t("auth.setup.passwordPlaceholder"))}"
            >
          </div>

          <div class="form-field">
            <label for="setup-confirm-password">${escapeHtml(t("auth.setup.confirmPasswordLabel"))}</label>
            <input
              id="setup-confirm-password"
              name="confirmPassword"
              type="password"
              required
              minlength="6"
              maxlength="256"
              autocomplete="new-password"
              placeholder="${escapeHtml(t("auth.setup.confirmPasswordPlaceholder"))}"
            >
          </div>

          <button type="submit" class="btn btn-primary" data-testid="setup-submit">
            ${escapeHtml(t("auth.setup.submitBtn"))}
          </button>
        </form>
      </section>
    </div>
  `;

  wireLanguageSelect(root);

  const form = root.querySelector("#setup-form");
  const errorBox = root.querySelector('[data-testid="setup-error"]');
  const submitBtn = root.querySelector('[data-testid="setup-submit"]');

  function showError(message) {
    errorBox.textContent = message;
    errorBox.classList.remove("hidden");
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorBox.classList.add("hidden");
    errorBox.textContent = "";

    const formData = new FormData(form);
    const clanName = String(formData.get("clanName") || "").trim();
    const username = String(formData.get("username") || "").trim();
    const password = String(formData.get("password") || "");
    const confirmPassword = String(formData.get("confirmPassword") || "");

    if (!username) {
      showError(t("auth.setup.errUsernameRequired"));
      return;
    }
    if (password.length < 6) {
      showError(t("auth.setup.errPasswordMin"));
      return;
    }
    if (password !== confirmPassword) {
      showError(t("auth.setup.errPasswordMismatch"));
      return;
    }

    submitBtn.disabled = true;
    try {
      const data = await setupAdmin({
        username,
        password,
        clanName: clanName || null,
      });
      await onSuccess(data);
    } catch (err) {
      showError(err.message || t("auth.setup.errFailed"));
    } finally {
      submitBtn.disabled = false;
    }
  });
}
