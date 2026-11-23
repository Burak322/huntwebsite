import {
  changePassword,
  createField,
  deleteField,
  escapeHtml,
  exportStaticBackup,
  fmtDateTime,
  fmtNum,
  getDailyLimit,
  importStaticBackup,
  isStaticMode,
  listFields,
  resetStaticData,
  setDailyLimit,
  updateClanName,
  updateField,
} from "../api.js";
import { renderLanguageSelect, t, wireLanguageSelect } from "../i18n/index.js";

const VALID_SCOPE_KEYS = new Set(["profile", "progression"]);
const VALID_TYPE_KEYS = new Set(["number", "text", "boolean", "select", "date"]);

function getScopeLabel(scope) {
  return VALID_SCOPE_KEYS.has(scope) ? t(`settings.scope.${scope}`) : scope;
}

function getTypeLabel(fieldType) {
  return VALID_TYPE_KEYS.has(fieldType) ? t(`settings.fieldType.${fieldType}`) : fieldType;
}

export function renderSettingsPage(container, { authState, onClanNameChange }) {
  let limitFeedback = { error: false, text: "" };
  let fieldsFeedback = { error: false, text: "" };
  let clanFeedback = { error: false, text: "" };
  let passwordFeedback = { error: false, text: "" };
  let backupFeedback = { error: false, text: "" };
  let confirmDeleteFieldId = null;
  let confirmResetSeed = false;

  async function load() {
    container.setAttribute("aria-busy", "true");
    try {
      const [limitState, fieldsRes] = await Promise.all([
        getDailyLimit(),
        listFields({ activeOnly: false }),
      ]);
      renderContent(limitState, fieldsRes.fields || []);
    } catch (err) {
      container.innerHTML = `
        <div class="page-header"><h1>${escapeHtml(t("settings.title"))}</h1></div>
        <div class="alert alert-error" role="alert">
          ${escapeHtml(err.message || t("settings.errLoadFailed"))}
        </div>
      `;
    } finally {
      container.removeAttribute("aria-busy");
    }
  }

  function renderFeedback(fb) {
    if (!fb.text) return "";
    return `<div class="alert ${fb.error ? "alert-error" : "alert-success"}" role="${
      fb.error ? "alert" : "status"
    }" style="margin-bottom: 0.9rem;">${escapeHtml(fb.text)}</div>`;
  }

  function renderContent(limitState, fields) {
    const activeMin = Number(limitState.activeMinScore ?? 0);
    const history = Array.isArray(limitState.history) ? limitState.history : [];

    const historyRows =
      history.length === 0
        ? `<tr><td colspan="3" class="empty-cell">${escapeHtml(t("settings.emptyLimitHistory"))}</td></tr>`
        : history
            .map(
              (h) => `
                <tr>
                  <td><strong>${escapeHtml(fmtNum(h.minScore))}</strong></td>
                  <td>${h.note ? escapeHtml(h.note) : '<span class="muted-text">—</span>'}</td>
                  <td>${escapeHtml(fmtDateTime(h.changedAt))}</td>
                </tr>
              `
            )
            .join("");

    const fieldRows =
      fields.length === 0
        ? `<tr><td colspan="7" class="empty-cell">${escapeHtml(t("settings.emptyFields"))}</td></tr>`
        : fields
            .map((f) => {
              const scopeText = getScopeLabel(f.scope);
              const typeText = getTypeLabel(f.field_type);
              const optsHint =
                f.field_type === "select" && Array.isArray(f.options)
                  ? ` (${f.options.join(", ")})`
                  : "";
              const statusBadge = f.is_active
                ? `<span class="badge badge-success">${escapeHtml(t("common.status.active"))}</span>`
                : `<span class="badge badge-muted">${escapeHtml(t("settings.archivedBadge"))}</span>`;
              const isConfirming = confirmDeleteFieldId === f.id;
              const deleteBtns = isConfirming
                ? `
                    <button type="button" class="btn btn-danger-outline btn-sm" data-confirm-delete-field="${f.id}">
                      ${escapeHtml(t("settings.confirmDeleteField"))}
                    </button>
                    <button type="button" class="btn btn-secondary btn-sm" data-cancel-delete-field="${f.id}">
                      ${escapeHtml(t("common.discard"))}
                    </button>
                  `
                : `
                    <button type="button" class="btn btn-danger-outline btn-sm" data-ask-delete-field="${f.id}">
                      ${escapeHtml(t("common.delete"))}
                    </button>
                  `;

              return `
                <tr data-field-id="${f.id}">
                  <td><strong>${escapeHtml(f.label)}</strong></td>
                  <td><code>${escapeHtml(f.field_key)}</code></td>
                  <td>${escapeHtml(scopeText)}</td>
                  <td>${escapeHtml(typeText + optsHint)}</td>
                  <td>${f.unit ? escapeHtml(f.unit) : "—"}</td>
                  <td>${statusBadge}</td>
                  <td>
                    <div class="action-row">
                      <button
                        type="button"
                        class="btn btn-secondary btn-sm"
                        data-toggle-field="${f.id}"
                        data-next-active="${f.is_active ? "0" : "1"}"
                      >
                        ${escapeHtml(f.is_active ? t("settings.archiveFieldBtn") : t("settings.activateFieldBtn"))}
                      </button>
                      ${deleteBtns}
                    </div>
                  </td>
                </tr>
              `;
            })
            .join("");

    container.innerHTML = `
      <div class="page-header">
        <div>
          <h1>${escapeHtml(t("settings.title"))}</h1>
          <p class="muted-text" style="margin: 0.25rem 0 0;">
            ${escapeHtml(t("settings.subtitle"))}
          </p>
        </div>
      </div>

      <section class="card section-card" data-testid="settings-language-section">
        <div class="section-head">
          <div>
            <h2>${escapeHtml(t("settings.languageCardTitle"))}</h2>
            <p class="muted-text">${escapeHtml(t("settings.languageCardDesc"))}</p>
          </div>
          <div class="form-field" style="min-width: 210px;">
            <label for="settings-lang-select">${escapeHtml(t("settings.languageSelectLabel"))}</label>
            ${renderLanguageSelect({
              id: "settings-lang-select",
              testId: "settings-lang-select",
              className: "lang-select",
            })}
          </div>
        </div>
      </section>

      <section class="card section-card" data-testid="settings-limit-section">
        <div class="section-head">
          <div>
            <h2>${escapeHtml(t("settings.limitCardTitle"))}</h2>
            <p class="muted-text">
              ${escapeHtml(t("settings.currentLimitPrefix"))} <strong style="color: var(--gold);" data-testid="settings-active-limit">${escapeHtml(
                fmtNum(activeMin)
              )}</strong>${
                limitState.updatedAt
                  ? escapeHtml(t("settings.lastUpdatedPrefix", { date: fmtDateTime(limitState.updatedAt) }))
                  : ""
              }
            </p>
          </div>
        </div>

        ${renderFeedback(limitFeedback)}

        <form data-testid="settings-limit-form" class="form-inline" style="margin-top: 0.75rem;">
          <div class="form-field">
            <label for="settings-min-score">${escapeHtml(t("dashboard.minDailyLimitLabel"))}</label>
            <input
              id="settings-min-score"
              name="minScore"
              type="number"
              min="0"
              step="1"
              required
              value="${escapeHtml(activeMin)}"
            >
          </div>
          <div class="form-field" style="flex: 1; min-width: 220px;">
            <label for="settings-limit-note">${escapeHtml(t("duelDetail.changeNoteLabel"))}</label>
            <input
              id="settings-limit-note"
              name="note"
              type="text"
              placeholder="${escapeHtml(t("settings.limitNotePlaceholder"))}"
            >
          </div>
          <div style="align-self: flex-end;">
            <button type="submit" class="btn btn-primary" data-testid="settings-limit-submit">
              ${escapeHtml(t("settings.saveLimitBtn"))}
            </button>
          </div>
        </form>

        <h3 style="margin: 1.25rem 0 0.65rem; font-size: 1rem;">${escapeHtml(t("settings.limitHistoryTitle"))}</h3>
        <div class="table-wrap">
          <table data-testid="limit-history-table">
            <thead>
              <tr>
                <th>${escapeHtml(t("settings.colDailyLimit"))}</th>
                <th>${escapeHtml(t("playerDetail.colNote"))}</th>
                <th>${escapeHtml(t("settings.colChangedAt"))}</th>
              </tr>
            </thead>
            <tbody>${historyRows}</tbody>
          </table>
        </div>
      </section>

      <section class="card section-card" data-testid="settings-fields-section">
        <div class="section-head">
          <div>
            <h2>${escapeHtml(t("settings.fieldsCardTitle"))}</h2>
            <p class="muted-text">
              ${escapeHtml(t("settings.fieldsCardDesc"))}
            </p>
          </div>
        </div>

        ${renderFeedback(fieldsFeedback)}

        <form data-testid="create-field-form" class="form-stack" style="margin-top: 0.75rem;">
          <div class="form-grid">
            <div class="form-field">
              <label for="field-label">${escapeHtml(t("settings.fieldLabelRequired"))}</label>
              <input
                id="field-label"
                name="label"
                type="text"
                required
                placeholder="${escapeHtml(t("settings.fieldLabelPlaceholder"))}"
              >
            </div>
            <div class="form-field">
              <label for="field-scope">${escapeHtml(t("settings.fieldScopeLabel"))}</label>
              <select id="field-scope" name="scope">
                <option value="profile">${escapeHtml(t("settings.scope.profile"))}</option>
                <option value="progression">${escapeHtml(t("settings.scope.progression"))}</option>
              </select>
            </div>
            <div class="form-field">
              <label for="field-type">${escapeHtml(t("settings.fieldTypeLabel"))}</label>
              <select id="field-type" name="field_type">
                <option value="number">${escapeHtml(t("settings.fieldType.number"))}</option>
                <option value="text">${escapeHtml(t("settings.fieldType.text"))}</option>
                <option value="select">${escapeHtml(t("settings.fieldType.select"))}</option>
                <option value="boolean">${escapeHtml(t("settings.fieldType.boolean"))}</option>
                <option value="date">${escapeHtml(t("settings.fieldType.date"))}</option>
              </select>
            </div>
            <div class="form-field">
              <label for="field-unit">${escapeHtml(t("settings.fieldUnitLabel"))}</label>
              <input id="field-unit" name="unit" type="text" placeholder="${escapeHtml(t("settings.fieldUnitPlaceholder"))}">
            </div>
            <div class="form-field" data-testid="field-options-wrap">
              <label for="field-options">${escapeHtml(t("settings.fieldOptionsLabel"))}</label>
              <input
                id="field-options"
                name="options"
                type="text"
                placeholder="${escapeHtml(t("settings.fieldOptionsPlaceholder"))}"
              >
            </div>
            <div class="form-field">
              <label for="field-order">${escapeHtml(t("settings.fieldOrderLabel"))}</label>
              <input id="field-order" name="sort_order" type="number" step="1" value="0">
            </div>
          </div>

          <div class="form-inline" style="align-items: center;">
            <label class="checkbox-label" for="field-required">
              <input id="field-required" name="is_required" type="checkbox">
              <span>${escapeHtml(t("settings.fieldRequiredCheckbox"))}</span>
            </label>
            <button type="submit" class="btn btn-primary" data-testid="create-field-submit">
              ${escapeHtml(t("settings.addFieldBtn"))}
            </button>
          </div>
        </form>

        <div class="table-wrap" style="margin-top: 1.25rem;">
          <table data-testid="fields-table">
            <thead>
              <tr>
                <th>${escapeHtml(t("settings.colFieldLabel"))}</th>
                <th>${escapeHtml(t("settings.colFieldKey"))}</th>
                <th>${escapeHtml(t("settings.colScope"))}</th>
                <th>${escapeHtml(t("settings.colType"))}</th>
                <th>${escapeHtml(t("settings.colUnit"))}</th>
                <th>${escapeHtml(t("dashboard.colStatus"))}</th>
                <th>${escapeHtml(t("playerDetail.colActions"))}</th>
              </tr>
            </thead>
            <tbody>${fieldRows}</tbody>
          </table>
        </div>
      </section>

      <div class="two-col-grid">
        <section class="card section-card" data-testid="settings-clan-section">
          <h2 style="margin-top: 0;">${escapeHtml(t("settings.clanNameCardTitle"))}</h2>
          ${renderFeedback(clanFeedback)}
          <form data-testid="clan-name-form" class="form-stack">
            <div class="form-field">
              <label for="settings-clan-name">${escapeHtml(t("settings.clanNameLabel"))}</label>
              <input
                id="settings-clan-name"
                name="clanName"
                type="text"
                required
                value="${escapeHtml(authState.clanName || "")}"
              >
            </div>
            <div>
              <button type="submit" class="btn btn-primary">${escapeHtml(t("settings.updateClanNameBtn"))}</button>
            </div>
          </form>
        </section>

        <section class="card section-card" data-testid="settings-password-section">
          <h2 style="margin-top: 0;">${escapeHtml(t("settings.changePasswordCardTitle"))}</h2>
          ${renderFeedback(passwordFeedback)}
          <form data-testid="change-password-form" class="form-stack">
            <div class="form-field">
              <label for="pw-current">${escapeHtml(t("settings.currentPasswordLabel"))}</label>
              <input id="pw-current" name="currentPassword" type="password" required>
            </div>
            <div class="form-field">
              <label for="pw-new">${escapeHtml(t("settings.newPasswordLabel"))}</label>
              <input id="pw-new" name="newPassword" type="password" required>
            </div>
            <div class="form-field">
              <label for="pw-confirm">${escapeHtml(t("settings.confirmNewPasswordLabel"))}</label>
              <input id="pw-confirm" name="confirmPassword" type="password" required>
            </div>
            <div>
              <button type="submit" class="btn btn-primary">${escapeHtml(t("settings.updatePasswordBtn"))}</button>
            </div>
          </form>
        </section>
      </div>

      ${
        isStaticMode()
          ? `
            <section class="card section-card" data-testid="settings-backup-section">
              <div class="section-head">
                <div>
                  <h2>${escapeHtml(t("settings.backupCardTitle"))}</h2>
                  <p class="muted-text">${escapeHtml(t("settings.backupCardDesc"))}</p>
                </div>
              </div>
              ${renderFeedback(backupFeedback)}
              <div class="form-inline" style="margin-top: 0.9rem; align-items: flex-end; flex-wrap: wrap;">
                <button type="button" class="btn btn-primary" data-testid="export-backup-btn">
                  ${escapeHtml(t("settings.exportJsonBtn"))}
                </button>
                <form data-testid="import-backup-form" class="form-inline" style="align-items: flex-end;">
                  <div class="form-field">
                    <label for="import-backup-file">${escapeHtml(t("settings.importJsonLabel"))}</label>
                    <input
                      id="import-backup-file"
                      type="file"
                      accept="application/json,.json"
                      required
                      data-testid="import-backup-input"
                    >
                  </div>
                  <button type="submit" class="btn btn-secondary" data-testid="import-backup-btn">
                    ${escapeHtml(t("settings.importJsonBtn"))}
                  </button>
                </form>
                <div class="action-row">
                  ${
                    confirmResetSeed
                      ? `
                          <button type="button" class="btn btn-danger-outline" data-testid="confirm-reset-seed-btn">
                            ${escapeHtml(t("settings.confirmResetSeedBtn"))}
                          </button>
                          <button type="button" class="btn btn-secondary" data-testid="cancel-reset-seed-btn">
                            ${escapeHtml(t("common.discard"))}
                          </button>
                        `
                      : `
                          <button type="button" class="btn btn-danger-outline" data-testid="ask-reset-seed-btn">
                            ${escapeHtml(t("settings.resetSeedBtn"))}
                          </button>
                        `
                  }
                </div>
              </div>
            </section>
          `
          : ""
      }
    `;

    wireLanguageSelect(container, '[data-testid="settings-lang-select"]');

    // Toggle options input availability based on field_type
    const fieldTypeSel = container.querySelector("#field-type");
    const optionsWrap = container.querySelector('[data-testid="field-options-wrap"]');
    const optionsInput = container.querySelector("#field-options");
    function syncOptionsVisibility() {
      const isSelect = fieldTypeSel.value === "select";
      optionsWrap.classList.toggle("hidden", !isSelect);
      optionsInput.disabled = !isSelect;
    }
    syncOptionsVisibility();
    fieldTypeSel.addEventListener("change", syncOptionsVisibility);

    // Limit form submit
    const limitForm = container.querySelector('[data-testid="settings-limit-form"]');
    limitForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      limitFeedback = { error: false, text: "" };
      const minVal = Number(limitForm.querySelector('[name="minScore"]').value);
      const note = limitForm.querySelector('[name="note"]').value.trim();
      const btn = limitForm.querySelector('[data-testid="settings-limit-submit"]');

      if (!Number.isInteger(minVal) || minVal < 0) {
        limitFeedback = { error: true, text: t("dashboard.errLimitInvalid") };
        renderContent(limitState, fields);
        return;
      }

      btn.disabled = true;
      try {
        await setDailyLimit(minVal, note);
        limitFeedback = {
          error: false,
          text: t("dashboard.msgLimitUpdated", { limit: fmtNum(minVal) }),
        };
        await load();
      } catch (err) {
        limitFeedback = { error: true, text: err.message || t("dashboard.errLimitUpdateFailed") };
        renderContent(limitState, fields);
      } finally {
        btn.disabled = false;
      }
    });

    // Create field form submit
    const createFieldForm = container.querySelector('[data-testid="create-field-form"]');
    createFieldForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      fieldsFeedback = { error: false, text: "" };
      const label = createFieldForm.querySelector('[name="label"]').value.trim();
      const scope = createFieldForm.querySelector('[name="scope"]').value;
      const fieldType = createFieldForm.querySelector('[name="field_type"]').value;
      const unit = createFieldForm.querySelector('[name="unit"]').value.trim();
      const sortOrder = Number(createFieldForm.querySelector('[name="sort_order"]').value || 0);
      const isRequired = createFieldForm.querySelector('[name="is_required"]').checked;
      const btn = createFieldForm.querySelector('[data-testid="create-field-submit"]');

      let options = null;
      if (fieldType === "select") {
        options = createFieldForm
          .querySelector('[name="options"]')
          .value.split(",")
          .map((s) => s.trim())
          .filter(Boolean);
        if (options.length === 0) {
          fieldsFeedback = {
            error: true,
            text: t("settings.errSelectOptionsRequired"),
          };
          renderContent(limitState, fields);
          return;
        }
      }

      btn.disabled = true;
      try {
        const res = await createField({
          label,
          scope,
          field_type: fieldType,
          unit: unit || null,
          options,
          is_required: isRequired,
          sort_order: Number.isInteger(sortOrder) ? sortOrder : 0,
        });
        fieldsFeedback = { error: false, text: t("settings.msgFieldCreated", { label: res.field.label }) };
        await load();
      } catch (err) {
        fieldsFeedback = { error: true, text: err.message || t("settings.errFieldCreateFailed") };
        renderContent(limitState, fields);
      } finally {
        btn.disabled = false;
      }
    });

    // Toggle / Delete field buttons
    container.querySelectorAll("[data-toggle-field]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = Number(btn.getAttribute("data-toggle-field"));
        const nextActive = btn.getAttribute("data-next-active") === "1";
        btn.disabled = true;
        try {
          await updateField(id, { is_active: nextActive });
          fieldsFeedback = {
            error: false,
            text: nextActive ? t("settings.msgFieldActivated") : t("settings.msgFieldArchived"),
          };
          await load();
        } catch (err) {
          fieldsFeedback = { error: true, text: err.message || t("settings.errFieldUpdateFailed") };
          renderContent(limitState, fields);
        }
      });
    });

    container.querySelectorAll("[data-ask-delete-field]").forEach((btn) => {
      btn.addEventListener("click", () => {
        confirmDeleteFieldId = Number(btn.getAttribute("data-ask-delete-field"));
        renderContent(limitState, fields);
      });
    });

    container.querySelectorAll("[data-cancel-delete-field]").forEach((btn) => {
      btn.addEventListener("click", () => {
        confirmDeleteFieldId = null;
        renderContent(limitState, fields);
      });
    });

    container.querySelectorAll("[data-confirm-delete-field]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = Number(btn.getAttribute("data-confirm-delete-field"));
        btn.disabled = true;
        try {
          await deleteField(id);
          confirmDeleteFieldId = null;
          fieldsFeedback = { error: false, text: t("settings.msgFieldDeleted") };
          await load();
        } catch (err) {
          fieldsFeedback = { error: true, text: err.message || t("settings.errFieldDeleteFailed") };
          renderContent(limitState, fields);
        }
      });
    });

    // Clan name form
    const clanForm = container.querySelector('[data-testid="clan-name-form"]');
    clanForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      clanFeedback = { error: false, text: "" };
      const clanName = clanForm.querySelector('[name="clanName"]').value.trim();
      try {
        const res = await updateClanName(clanName);
        clanFeedback = { error: false, text: t("settings.msgClanNameUpdated") };
        if (typeof onClanNameChange === "function") {
          onClanNameChange(res.clanName);
        } else {
          await load();
        }
      } catch (err) {
        clanFeedback = { error: true, text: err.message || t("settings.errClanNameUpdateFailed") };
        renderContent(limitState, fields);
      }
    });

    // Change password form
    const pwForm = container.querySelector('[data-testid="change-password-form"]');
    pwForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      passwordFeedback = { error: false, text: "" };
      const currentPassword = pwForm.querySelector('[name="currentPassword"]').value;
      const newPassword = pwForm.querySelector('[name="newPassword"]').value;
      const confirmPassword = pwForm.querySelector('[name="confirmPassword"]').value;

      if (newPassword !== confirmPassword) {
        passwordFeedback = { error: true, text: t("settings.errNewPasswordMismatch") };
        renderContent(limitState, fields);
        return;
      }

      try {
        await changePassword({ currentPassword, newPassword });
        passwordFeedback = { error: false, text: t("settings.msgPasswordUpdated") };
        renderContent(limitState, fields);
      } catch (err) {
        passwordFeedback = { error: true, text: err.message || t("settings.errPasswordUpdateFailed") };
        renderContent(limitState, fields);
      }
    });

    if (isStaticMode()) {
      const exportBtn = container.querySelector('[data-testid="export-backup-btn"]');
      if (exportBtn) {
        exportBtn.addEventListener("click", async () => {
          backupFeedback = { error: false, text: "" };
          try {
            const jsonText = await exportStaticBackup();
            const blob = new Blob([jsonText], { type: "application/json;charset=utf-8" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = "clan-backup.json";
            document.body.appendChild(a);
            a.click();
            a.remove();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
            backupFeedback = { error: false, text: t("settings.msgExported") };
          } catch (err) {
            backupFeedback = { error: true, text: err.message || t("settings.errImportInvalid") };
          }
          renderContent(limitState, fields);
        });
      }

      const importForm = container.querySelector('[data-testid="import-backup-form"]');
      if (importForm) {
        importForm.addEventListener("submit", async (event) => {
          event.preventDefault();
          backupFeedback = { error: false, text: "" };
          const input = importForm.querySelector('[data-testid="import-backup-input"]');
          const file = input?.files?.[0];
          if (!file) return;
          try {
            const text = await file.text();
            const res = await importStaticBackup(text);
            backupFeedback = { error: false, text: t("settings.msgImported") };
            if (typeof onClanNameChange === "function" && res.clanName) {
              onClanNameChange(res.clanName);
            } else {
              await load();
            }
          } catch (err) {
            backupFeedback = { error: true, text: err.message || t("settings.errImportInvalid") };
            renderContent(limitState, fields);
          }
        });
      }

      const askResetBtn = container.querySelector('[data-testid="ask-reset-seed-btn"]');
      if (askResetBtn) {
        askResetBtn.addEventListener("click", () => {
          confirmResetSeed = true;
          renderContent(limitState, fields);
        });
      }
      const cancelResetBtn = container.querySelector('[data-testid="cancel-reset-seed-btn"]');
      if (cancelResetBtn) {
        cancelResetBtn.addEventListener("click", () => {
          confirmResetSeed = false;
          renderContent(limitState, fields);
        });
      }
      const confirmResetBtn = container.querySelector('[data-testid="confirm-reset-seed-btn"]');
      if (confirmResetBtn) {
        confirmResetBtn.addEventListener("click", async () => {
          confirmResetBtn.disabled = true;
          try {
            const res = await resetStaticData();
            confirmResetSeed = false;
            backupFeedback = { error: false, text: t("settings.msgResetDone") };
            if (typeof onClanNameChange === "function" && res.clanName) {
              onClanNameChange(res.clanName);
            } else {
              await load();
            }
          } catch (err) {
            confirmResetSeed = false;
            backupFeedback = { error: true, text: err.message || t("settings.errImportInvalid") };
            renderContent(limitState, fields);
          }
        });
      }
    }
  }

  load();
}
