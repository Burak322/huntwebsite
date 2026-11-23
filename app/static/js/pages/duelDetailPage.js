import {
  addScore,
  deleteDuel,
  deleteScore,
  escapeHtml,
  extractScreenshot,
  fmtDate,
  fmtNum,
  getDuel,
  listPlayers,
  setDailyLimit,
  todayIso,
  updateDuel,
  updateScore,
} from "../api.js";
import { t, translateApiMessage } from "../i18n/index.js";
import { renderComplianceSummary, renderLimitBadge } from "../components/limitBadge.js";
import { mountOcrReview } from "../components/ocrReview.js";

const DUEL_STATUS_CLASSES = {
  ongoing: "badge-info",
  completed: "badge-success",
  cancelled: "badge-muted",
};

function getDuelStatusMeta(status) {
  const cls = DUEL_STATUS_CLASSES[status];
  return cls
    ? { label: t(`duels.status.${status}`), cls }
    : { label: status, cls: "badge-muted" };
}

export function renderDuelDetailPage(container, { duelId, onNavigate }) {
  let feedback = { error: false, text: "" };
  let activeExtraction = null;
  let selectedDateFilter = "";
  let showEditDuel = false;
  let confirmDeleteDuel = false;
  let editingScoreId = null;
  let confirmDeleteScoreId = null;

  function wireLinks() {
    container.querySelectorAll("[data-link]").forEach((anchor) => {
      anchor.addEventListener("click", (event) => {
        event.preventDefault();
        onNavigate(anchor.getAttribute("href") || "/duels");
      });
    });
  }

  async function load() {
    container.setAttribute("aria-busy", "true");
    try {
      const [detail, playersRes] = await Promise.all([getDuel(duelId), listPlayers()]);
      renderContent(detail, playersRes.players || []);
    } catch (err) {
      container.innerHTML = `
        <div class="page-header">
          <h1>${escapeHtml(t("duelDetail.title"))}</h1>
          <a href="/duels" data-link class="btn btn-secondary">${escapeHtml(t("duelDetail.backToDuels"))}</a>
        </div>
        <div class="alert alert-error" role="alert">
          ${escapeHtml(err.message || t("duelDetail.errLoadFailed"))}
        </div>
      `;
      wireLinks();
    } finally {
      container.removeAttribute("aria-busy");
    }
  }

  function renderContent(detail, players) {
    const duel = detail.duel;
    const activeLimit = Number(detail.activeDailyMinScore ?? 0);
    const summaries = Array.isArray(detail.dailySummaries) ? detail.dailySummaries : [];
    const compliance = detail.compliance || { total: 0, met: 0, missed: 0 };
    const scores = Array.isArray(detail.scores) ? detail.scores : [];
    const screenshots = Array.isArray(detail.screenshots) ? detail.screenshots : [];

    const st = getDuelStatusMeta(duel.status);
    const dateRange = duel.end_date
      ? `${fmtDate(duel.start_date)} – ${fmtDate(duel.end_date)}`
      : fmtDate(duel.start_date);

    const feedbackHtml = feedback.text
      ? `<div class="alert ${feedback.error ? "alert-error" : "alert-success"}" role="${
          feedback.error ? "alert" : "status"
        }" style="margin-bottom: 1rem;">${escapeHtml(feedback.text)}</div>`
      : "";

    const distinctDates = [...new Set(summaries.map((s) => s.scoreDate))].sort().reverse();
    if (selectedDateFilter && !distinctDates.includes(selectedDateFilter)) {
      selectedDateFilter = "";
    }
    const filteredSummaries = selectedDateFilter
      ? summaries.filter((s) => s.scoreDate === selectedDateFilter)
      : summaries;

    const summaryRowsHtml =
      filteredSummaries.length === 0
        ? `<tr><td colspan="6" class="empty-cell">${escapeHtml(t("duelDetail.emptyDailySummaries"))}</td></tr>`
        : filteredSummaries
            .map((s) => {
              const playerCell =
                s.playerId !== null && s.playerId !== undefined
                  ? `<a href="/players/${s.playerId}" data-link class="text-link"><strong>${escapeHtml(
                      s.playerName
                    )}</strong></a>`
                  : `<span>${escapeHtml(s.playerName)}</span> <span class="badge badge-muted">${escapeHtml(t("duelDetail.unregisteredBadge"))}</span>`;
              return `
                <tr>
                  <td>${escapeHtml(fmtDate(s.scoreDate))}</td>
                  <td>${playerCell}</td>
                  <td><strong>${escapeHtml(fmtNum(s.totalScore))}</strong></td>
                  <td>${escapeHtml(fmtNum(s.activeDailyMinScore))}</td>
                  <td>${renderLimitBadge(s)}</td>
                  <td>${escapeHtml(s.entryCount)}</td>
                </tr>
              `;
            })
            .join("");

    const rawScoreRowsHtml =
      scores.length === 0
        ? `<tr><td colspan="6" class="empty-cell">${escapeHtml(t("duelDetail.emptyRawScores"))}</td></tr>`
        : scores
            .map((s) => {
              const nameText = s.player_name || s.extracted_name;
              const nameCell =
                s.player_id !== null && s.player_id !== undefined
                  ? `<a href="/players/${s.player_id}" data-link class="text-link">${escapeHtml(
                      nameText
                    )}</a>`
                  : escapeHtml(nameText);

              const scoreCell =
                editingScoreId === s.id
                  ? `
                      <form class="inline-score-edit" data-edit-score-form="${s.id}">
                        <input
                          type="number"
                          min="0"
                          step="1"
                          required
                          name="score"
                          value="${escapeHtml(s.score)}"
                          class="table-input table-input-num"
                        >
                        <button type="submit" class="btn btn-primary btn-sm">${escapeHtml(t("common.save"))}</button>
                        <button type="button" class="btn btn-secondary btn-sm" data-cancel-edit-score="${s.id}">${escapeHtml(t("common.cancel"))}</button>
                      </form>
                    `
                  : `<strong>${escapeHtml(fmtNum(s.score))}</strong>`;

              const sourceBadge =
                s.source === "ocr"
                  ? `<span class="badge badge-info">${escapeHtml(t("duelDetail.sourceOcr"))}</span>`
                  : `<span class="badge badge-muted">${escapeHtml(t("duelDetail.sourceManual"))}</span>`;

              const deleteControls =
                confirmDeleteScoreId === s.id
                  ? `
                      <button type="button" class="btn btn-danger-outline btn-sm" data-confirm-delete-score="${s.id}">${escapeHtml(t("common.confirm"))}</button>
                      <button type="button" class="btn btn-secondary btn-sm" data-cancel-delete-score="${s.id}">${escapeHtml(t("common.discard"))}</button>
                    `
                  : `<button type="button" class="btn btn-danger-outline btn-sm" data-ask-delete-score="${s.id}">${escapeHtml(t("common.delete"))}</button>`;

              return `
                <tr data-score-id="${s.id}">
                  <td>${escapeHtml(fmtDate(s.score_date))}</td>
                  <td>${nameCell}</td>
                  <td>${scoreCell}</td>
                  <td>${sourceBadge}</td>
                  <td>${renderLimitBadge(s)}</td>
                  <td>
                    <div class="action-row">
                      <button type="button" class="btn btn-secondary btn-sm" data-edit-score="${s.id}">${escapeHtml(t("common.edit"))}</button>
                      ${deleteControls}
                    </div>
                  </td>
                </tr>
              `;
            })
            .join("");

    const screenshotsHtml =
      screenshots.length === 0
        ? `<div class="empty-state">${escapeHtml(t("duelDetail.emptyScreenshots"))}</div>`
        : `
          <div class="screenshot-grid">
            ${screenshots
              .map((shot) => {
                const shotStatus =
                  shot.status === "committed"
                    ? `<span class="badge badge-success">${escapeHtml(t("duelDetail.shotCommitted"))}</span>`
                    : `<span class="badge badge-gold">${escapeHtml(t("duelDetail.shotPending"))}</span>`;
                return `
                  <div class="screenshot-card">
                    <a href="${escapeHtml(shot.imageUrl)}" target="_blank" rel="noopener">
                      <img
                        src="${escapeHtml(shot.imageUrl)}"
                        alt="${escapeHtml(shot.original_filename)}"
                        class="screenshot-thumb"
                      >
                    </a>
                    <div class="screenshot-meta">
                      <div><strong>${escapeHtml(fmtDate(shot.score_date))}</strong></div>
                      <div class="muted-text" style="font-size: 0.8rem;">${escapeHtml(
                        shot.original_filename
                      )}</div>
                      <div style="margin-top: 0.35rem; display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap;">
                        ${shotStatus}
                        <span class="badge badge-muted">${escapeHtml(t("duelDetail.shotRowCount", { count: shot.row_count }))}</span>
                      </div>
                    </div>
                  </div>
                `;
              })
              .join("")}
          </div>
        `;

    const playerOptionsHtml = [
      `<option value="">${escapeHtml(t("duelDetail.unregisteredPlayerOption"))}</option>`,
      ...players.map(
        (p) => `<option value="${p.id}">${escapeHtml(p.display_name)}</option>`
      ),
    ].join("");

    const deleteDuelBtns = confirmDeleteDuel
      ? `
          <button type="button" class="btn btn-danger-outline btn-sm" data-testid="confirm-delete-duel-btn">
            ${escapeHtml(t("duelDetail.confirmDeleteDuel"))}
          </button>
          <button type="button" class="btn btn-secondary btn-sm" data-testid="cancel-delete-duel-btn">
            ${escapeHtml(t("common.discard"))}
          </button>
        `
      : `
          <button type="button" class="btn btn-danger-outline btn-sm" data-testid="ask-delete-duel-btn">
            ${escapeHtml(t("duelDetail.deleteDuel"))}
          </button>
        `;

    container.innerHTML = `
      <div class="page-header">
        <div>
          <a href="/duels" data-link class="text-link" style="display: inline-block; margin-bottom: 0.35rem;">
            ${escapeHtml(t("duelDetail.backToDuels"))}
          </a>
          <div style="display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap;">
            <h1 style="margin: 0;">${escapeHtml(duel.opponent_clan_name)}${
              duel.title ? ` — ${escapeHtml(duel.title)}` : ""
            }</h1>
            <span class="badge ${st.cls}">${escapeHtml(st.label)}</span>
          </div>
          <p class="muted-text" style="margin: 0.25rem 0 0;">${escapeHtml(t("duelDetail.datePrefix"))} ${escapeHtml(dateRange)}</p>
        </div>
        <div class="action-row">
          <button type="button" class="btn btn-secondary btn-sm" data-testid="toggle-edit-duel-btn">
            ${escapeHtml(t("duelDetail.toggleEditDuel"))}
          </button>
          ${deleteDuelBtns}
        </div>
      </div>

      ${feedbackHtml}

      <section class="card section-card ${showEditDuel ? "" : "hidden"}" data-testid="edit-duel-section">
        <h2 style="margin-top: 0;">${escapeHtml(t("duelDetail.editDuelTitle"))}</h2>
        <form data-testid="edit-duel-form" class="form-stack">
          <div class="form-grid">
            <div class="form-field">
              <label for="edit-duel-opp">${escapeHtml(t("duels.opponentNameRequired"))}</label>
              <input id="edit-duel-opp" name="opponent_clan_name" type="text" required value="${escapeHtml(
                duel.opponent_clan_name
              )}">
            </div>
            <div class="form-field">
              <label for="edit-duel-title">${escapeHtml(t("duels.colTitle"))}</label>
              <input id="edit-duel-title" name="title" type="text" value="${escapeHtml(
                duel.title || ""
              )}">
            </div>
            <div class="form-field">
              <label for="edit-duel-start">${escapeHtml(t("duels.startDateRequired"))}</label>
              <input id="edit-duel-start" name="start_date" type="date" required value="${escapeHtml(
                duel.start_date
              )}">
            </div>
            <div class="form-field">
              <label for="edit-duel-end">${escapeHtml(t("duels.endDateLabel"))}</label>
              <input id="edit-duel-end" name="end_date" type="date" value="${escapeHtml(
                duel.end_date || ""
              )}">
            </div>
            <div class="form-field">
              <label for="edit-duel-status">${escapeHtml(t("dashboard.colStatus"))}</label>
              <select id="edit-duel-status" name="status">
                <option value="ongoing" ${duel.status === "ongoing" ? "selected" : ""}>${escapeHtml(t("duels.status.ongoing"))}</option>
                <option value="completed" ${duel.status === "completed" ? "selected" : ""}>${escapeHtml(t("duels.status.completed"))}</option>
                <option value="cancelled" ${duel.status === "cancelled" ? "selected" : ""}>${escapeHtml(t("duels.status.cancelled"))}</option>
              </select>
            </div>
          </div>
          <div class="form-field">
            <label for="edit-duel-notes">${escapeHtml(t("duels.notesLabel"))}</label>
            <textarea id="edit-duel-notes" name="notes" rows="2">${escapeHtml(
              duel.notes || ""
            )}</textarea>
          </div>
          <div class="form-actions">
            <button type="submit" class="btn btn-primary btn-sm">${escapeHtml(t("duelDetail.saveChangesBtn"))}</button>
            <button type="button" class="btn btn-secondary btn-sm" data-testid="cancel-edit-duel-btn">${escapeHtml(t("common.cancel"))}</button>
          </div>
        </form>
      </section>

      <section class="card section-card">
        <div class="section-head">
          <div>
            <h2>${escapeHtml(t("duelDetail.dynamicLimitTitle"))}</h2>
            <p class="muted-text">
              ${escapeHtml(t("duelDetail.dynamicLimitActivePrefix"))}
              <strong style="color: var(--gold);" data-testid="duel-active-limit">${escapeHtml(
                fmtNum(activeLimit)
              )}</strong>
              ${escapeHtml(t("duelDetail.dynamicLimitActiveSuffix"))}
            </p>
          </div>
          <div data-testid="duel-compliance-summary">${renderComplianceSummary(compliance)}</div>
        </div>
        <form data-testid="duel-limit-form" class="form-inline" style="margin-top: 0.75rem;">
          <div class="form-field">
            <label for="duel-min-score">${escapeHtml(t("dashboard.minDailyLimitLabel"))}</label>
            <input
              id="duel-min-score"
              name="minScore"
              type="number"
              min="0"
              step="1"
              required
              value="${escapeHtml(activeLimit)}"
            >
          </div>
          <div class="form-field" style="flex: 1; min-width: 200px;">
            <label for="duel-limit-note">${escapeHtml(t("duelDetail.changeNoteLabel"))}</label>
            <input
              id="duel-limit-note"
              name="note"
              type="text"
              placeholder="${escapeHtml(t("duelDetail.limitNotePlaceholder"))}"
            >
          </div>
          <div style="align-self: flex-end;">
            <button type="submit" class="btn btn-primary" data-testid="duel-limit-submit">
              ${escapeHtml(t("dashboard.updateLimitBtn"))}
            </button>
          </div>
        </form>
      </section>

      <section class="card section-card" data-testid="screenshot-upload-section">
        <h2 style="margin-top: 0;">${escapeHtml(t("duelDetail.ocrCardTitle"))}</h2>
        <p class="muted-text">
          ${escapeHtml(t("duelDetail.ocrCardDesc"))}
        </p>
        <form data-testid="screenshot-upload-form" class="form-inline" style="margin-top: 0.75rem;">
          <div class="form-field" style="flex: 1; min-width: 240px;">
            <label for="screenshot-file">${escapeHtml(t("duelDetail.screenshotFileLabel"))}</label>
            <input
              id="screenshot-file"
              name="file"
              type="file"
              accept="image/png,image/jpeg,image/webp"
              required
              data-testid="screenshot-file-input"
            >
          </div>
          <div class="form-field">
            <label for="screenshot-date">${escapeHtml(t("ocr.scoreDateLabel"))}</label>
            <input
              id="screenshot-date"
              name="score_date"
              type="date"
              required
              value="${todayIso()}"
              data-testid="screenshot-date-input"
            >
          </div>
          <div style="align-self: flex-end;">
            <button type="submit" class="btn btn-primary" data-testid="screenshot-extract-btn">
              ${escapeHtml(t("duelDetail.scanScreenshotBtn"))}
            </button>
          </div>
        </form>
        <div class="muted-text hidden" data-testid="ocr-loading-msg" style="margin-top: 0.75rem;">
          ${escapeHtml(t("duelDetail.ocrLoading"))}
        </div>
        <div class="alert alert-error hidden" role="alert" data-testid="ocr-upload-error" style="margin-top: 0.75rem;"></div>
      </section>

      <div data-testid="ocr-review-mount"></div>

      <section class="card section-card">
        <div class="section-head">
          <h2>${escapeHtml(t("duelDetail.dailySummaryTitle"))}</h2>
          <div class="form-field" style="min-width: 180px;">
            <label for="summary-date-filter" style="font-size: 0.78rem;">${escapeHtml(t("duelDetail.dateFilterLabel"))}</label>
            <select id="summary-date-filter" data-testid="summary-date-filter">
              <option value="">${escapeHtml(t("duelDetail.allDaysOption"))}</option>
              ${distinctDates
                .map(
                  (d) =>
                    `<option value="${escapeHtml(d)}" ${
                      selectedDateFilter === d ? "selected" : ""
                    }>${escapeHtml(fmtDate(d))}</option>`
                )
                .join("")}
            </select>
          </div>
        </div>
        <div class="table-wrap" style="margin-top: 0.85rem;">
          <table data-testid="duel-summaries-table">
            <thead>
              <tr>
                <th>${escapeHtml(t("dashboard.colDate"))}</th>
                <th>${escapeHtml(t("dashboard.colPlayer"))}</th>
                <th>${escapeHtml(t("duelDetail.colDailyTotalScore"))}</th>
                <th>${escapeHtml(t("dashboard.colActiveLimit"))}</th>
                <th>${escapeHtml(t("dashboard.colLimitStatus"))}</th>
                <th>${escapeHtml(t("duelDetail.colEntryCount"))}</th>
              </tr>
            </thead>
            <tbody>${summaryRowsHtml}</tbody>
          </table>
        </div>
      </section>

      <section class="card section-card" data-testid="manual-score-section">
        <h2 style="margin-top: 0;">${escapeHtml(t("duelDetail.manualScoresTitle"))}</h2>
        <form data-testid="manual-score-form" class="form-inline" style="margin-bottom: 1rem;">
          <div class="form-field">
            <label for="manual-player-id">${escapeHtml(t("duelDetail.registeredPlayerLabel"))}</label>
            <select id="manual-player-id" name="player_id">${playerOptionsHtml}</select>
          </div>
          <div class="form-field">
            <label for="manual-extracted-name">${escapeHtml(t("duelDetail.customNameLabel"))}</label>
            <input
              id="manual-extracted-name"
              name="extracted_name"
              type="text"
              placeholder="${escapeHtml(t("duelDetail.customNamePlaceholder"))}"
            >
          </div>
          <div class="form-field">
            <label for="manual-score">${escapeHtml(t("duelDetail.scoreRequiredLabel"))}</label>
            <input id="manual-score" name="score" type="number" min="0" step="1" required>
          </div>
          <div class="form-field">
            <label for="manual-date">${escapeHtml(t("duelDetail.scoreDateRequiredLabel"))}</label>
            <input id="manual-date" name="score_date" type="date" required value="${todayIso()}">
          </div>
          <div style="align-self: flex-end;">
            <button type="submit" class="btn btn-secondary" data-testid="manual-score-submit">
              ${escapeHtml(t("duelDetail.manualScoreSubmitBtn"))}
            </button>
          </div>
        </form>

        <div class="table-wrap">
          <table data-testid="duel-raw-scores-table">
            <thead>
              <tr>
                <th>${escapeHtml(t("dashboard.colDate"))}</th>
                <th>${escapeHtml(t("dashboard.colPlayer"))}</th>
                <th>${escapeHtml(t("ocr.colScore"))}</th>
                <th>${escapeHtml(t("duelDetail.colSource"))}</th>
                <th>${escapeHtml(t("dashboard.colLimitStatus"))}</th>
                <th>${escapeHtml(t("playerDetail.colActions"))}</th>
              </tr>
            </thead>
            <tbody>${rawScoreRowsHtml}</tbody>
          </table>
        </div>
      </section>

      <section class="card section-card" data-testid="duel-screenshots-list">
        <h2 style="margin-top: 0;">${escapeHtml(t("duelDetail.uploadedScreenshotsTitle"))}</h2>
        ${screenshotsHtml}
      </section>
    `;

    wireLinks();

    // Mount pending OCR review if active
    const reviewMount = container.querySelector('[data-testid="ocr-review-mount"]');
    if (activeExtraction && reviewMount) {
      mountOcrReview(reviewMount, {
        duelId,
        extraction: activeExtraction,
        players,
        onCommitted: async (res) => {
          activeExtraction = null;
          const count = Array.isArray(res.savedScores) ? res.savedScores.length : 0;
          const warns =
            Array.isArray(res.warnings) && res.warnings.length > 0
              ? t("duelDetail.msgScoresWarnings", {
                  warnings: res.warnings.map((w) => translateApiMessage(w)).join("; "),
                })
              : "";
          feedback = { error: false, text: `${t("duelDetail.msgScoresCommitted", { count })}${warns}` };
          await load();
        },
        onCancel: () => {
          activeExtraction = null;
          reviewMount.innerHTML = "";
        },
      });
    }

    // Duel edit / delete
    const toggleEditBtn = container.querySelector('[data-testid="toggle-edit-duel-btn"]');
    const cancelEditBtn = container.querySelector('[data-testid="cancel-edit-duel-btn"]');
    const editSection = container.querySelector('[data-testid="edit-duel-section"]');
    toggleEditBtn.addEventListener("click", () => {
      showEditDuel = !showEditDuel;
      editSection.classList.toggle("hidden", !showEditDuel);
    });
    cancelEditBtn.addEventListener("click", () => {
      showEditDuel = false;
      editSection.classList.add("hidden");
    });

    const editDuelForm = container.querySelector('[data-testid="edit-duel-form"]');
    editDuelForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      feedback = { error: false, text: "" };
      try {
        await updateDuel(duelId, {
          opponent_clan_name: editDuelForm.querySelector('[name="opponent_clan_name"]').value.trim(),
          title: editDuelForm.querySelector('[name="title"]').value.trim() || null,
          start_date: editDuelForm.querySelector('[name="start_date"]').value.trim(),
          end_date: editDuelForm.querySelector('[name="end_date"]').value.trim() || null,
          status: editDuelForm.querySelector('[name="status"]').value,
          notes: editDuelForm.querySelector('[name="notes"]').value.trim() || null,
        });
        showEditDuel = false;
        feedback = { error: false, text: t("duelDetail.msgDuelUpdated") };
        await load();
      } catch (err) {
        feedback = { error: true, text: err.message || t("duelDetail.errDuelUpdateFailed") };
        renderContent(detail, players);
      }
    });

    const askDelDuel = container.querySelector('[data-testid="ask-delete-duel-btn"]');
    if (askDelDuel) {
      askDelDuel.addEventListener("click", () => {
        confirmDeleteDuel = true;
        renderContent(detail, players);
      });
    }
    const cancelDelDuel = container.querySelector('[data-testid="cancel-delete-duel-btn"]');
    if (cancelDelDuel) {
      cancelDelDuel.addEventListener("click", () => {
        confirmDeleteDuel = false;
        renderContent(detail, players);
      });
    }
    const confirmDelDuel = container.querySelector('[data-testid="confirm-delete-duel-btn"]');
    if (confirmDelDuel) {
      confirmDelDuel.addEventListener("click", async () => {
        confirmDelDuel.disabled = true;
        try {
          await deleteDuel(duelId);
          onNavigate("/duels");
        } catch (err) {
          confirmDeleteDuel = false;
          feedback = { error: true, text: err.message || t("duelDetail.errDuelDeleteFailed") };
          renderContent(detail, players);
        }
      });
    }

    // Inline daily limit update
    const limitForm = container.querySelector('[data-testid="duel-limit-form"]');
    limitForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      feedback = { error: false, text: "" };
      const minVal = Number(limitForm.querySelector('[name="minScore"]').value);
      const note = limitForm.querySelector('[name="note"]').value.trim();
      const btn = limitForm.querySelector('[data-testid="duel-limit-submit"]');

      if (!Number.isInteger(minVal) || minVal < 0) {
        feedback = { error: true, text: t("dashboard.errLimitInvalid") };
        renderContent(detail, players);
        return;
      }

      btn.disabled = true;
      try {
        await setDailyLimit(minVal, note);
        feedback = {
          error: false,
          text: t("duelDetail.msgLimitUpdated", { limit: fmtNum(minVal) }),
        };
        await load();
      } catch (err) {
        feedback = { error: true, text: err.message || t("dashboard.errLimitUpdateFailed") };
        renderContent(detail, players);
      } finally {
        btn.disabled = false;
      }
    });

    // OCR screenshot upload
    const uploadForm = container.querySelector('[data-testid="screenshot-upload-form"]');
    const ocrLoading = container.querySelector('[data-testid="ocr-loading-msg"]');
    const ocrError = container.querySelector('[data-testid="ocr-upload-error"]');
    uploadForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      ocrError.classList.add("hidden");
      ocrError.textContent = "";

      const fileInput = uploadForm.querySelector('[name="file"]');
      const dateInput = uploadForm.querySelector('[name="score_date"]');
      const btn = uploadForm.querySelector('[data-testid="screenshot-extract-btn"]');
      const file = fileInput.files?.[0];
      if (!file) {
        ocrError.textContent = t("duelDetail.errNoImageSelected");
        ocrError.classList.remove("hidden");
        return;
      }

      btn.disabled = true;
      ocrLoading.classList.remove("hidden");
      try {
        activeExtraction = await extractScreenshot(duelId, file, dateInput.value.trim());
        await load();
      } catch (err) {
        ocrError.textContent = err.message || t("duelDetail.errScreenshotProcessFailed");
        ocrError.classList.remove("hidden");
      } finally {
        btn.disabled = false;
        ocrLoading.classList.add("hidden");
      }
    });

    // Date filter
    const dateFilter = container.querySelector('[data-testid="summary-date-filter"]');
    if (dateFilter) {
      dateFilter.addEventListener("change", () => {
        selectedDateFilter = dateFilter.value;
        renderContent(detail, players);
      });
    }

    // Manual score add
    const manualForm = container.querySelector('[data-testid="manual-score-form"]');
    manualForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      feedback = { error: false, text: "" };
      const pid = manualForm.querySelector('[name="player_id"]').value;
      const customName = manualForm.querySelector('[name="extracted_name"]').value.trim();
      const scoreVal = Number(manualForm.querySelector('[name="score"]').value);
      const scoreDate = manualForm.querySelector('[name="score_date"]').value.trim();
      const btn = manualForm.querySelector('[data-testid="manual-score-submit"]');

      if (!pid && !customName) {
        feedback = { error: true, text: t("duelDetail.errPlayerOrNameRequired") };
        renderContent(detail, players);
        return;
      }

      btn.disabled = true;
      try {
        await addScore(duelId, {
          player_id: pid ? Number(pid) : null,
          extracted_name: customName || null,
          score: scoreVal,
          score_date: scoreDate,
        });
        feedback = { error: false, text: t("duelDetail.msgScoreAdded") };
        await load();
      } catch (err) {
        feedback = { error: true, text: err.message || t("duelDetail.errScoreAddFailed") };
        renderContent(detail, players);
      } finally {
        btn.disabled = false;
      }
    });

    // Raw score inline edit & delete
    container.querySelectorAll("[data-edit-score]").forEach((btn) => {
      btn.addEventListener("click", () => {
        editingScoreId = Number(btn.getAttribute("data-edit-score"));
        confirmDeleteScoreId = null;
        renderContent(detail, players);
      });
    });
    container.querySelectorAll("[data-cancel-edit-score]").forEach((btn) => {
      btn.addEventListener("click", () => {
        editingScoreId = null;
        renderContent(detail, players);
      });
    });
    container.querySelectorAll("[data-edit-score-form]").forEach((form) => {
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const sid = Number(form.getAttribute("data-edit-score-form"));
        const scoreVal = Number(form.querySelector('[name="score"]').value);
        try {
          await updateScore(sid, { score: scoreVal });
          editingScoreId = null;
          feedback = { error: false, text: t("duelDetail.msgScoreUpdated") };
          await load();
        } catch (err) {
          feedback = { error: true, text: err.message || t("duelDetail.errScoreUpdateFailed") };
          renderContent(detail, players);
        }
      });
    });

    container.querySelectorAll("[data-ask-delete-score]").forEach((btn) => {
      btn.addEventListener("click", () => {
        confirmDeleteScoreId = Number(btn.getAttribute("data-ask-delete-score"));
        renderContent(detail, players);
      });
    });
    container.querySelectorAll("[data-cancel-delete-score]").forEach((btn) => {
      btn.addEventListener("click", () => {
        confirmDeleteScoreId = null;
        renderContent(detail, players);
      });
    });
    container.querySelectorAll("[data-confirm-delete-score]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const sid = Number(btn.getAttribute("data-confirm-delete-score"));
        btn.disabled = true;
        try {
          await deleteScore(sid);
          confirmDeleteScoreId = null;
          feedback = { error: false, text: t("duelDetail.msgScoreDeleted") };
          await load();
        } catch (err) {
          feedback = { error: true, text: err.message || t("duelDetail.errScoreDeleteFailed") };
          renderContent(detail, players);
        }
      });
    });
  }

  load();
}
