import {
  CLAN_RANKS,
  TOWER_LEVELS,
  addAlias,
  createProgression,
  deleteAlias,
  deletePlayer,
  deleteProgression,
  escapeHtml,
  fmtDate,
  fmtNum,
  getPlayer,
  listFields,
  renderSelectOptions,
  todayIso,
  updatePlayer,
  updateProgression,
} from "../api.js";
import { t } from "../i18n/index.js";
import {
  collectDynamicFieldValues,
  formatFieldValue,
  renderDynamicFieldInputs,
} from "../components/dynamicFields.js";
import { renderLimitBadge } from "../components/limitBadge.js";
import { renderTrendChart } from "../components/trendChart.js";

const PLAYER_STATUS_CLASSES = {
  active: "badge-success",
  inactive: "badge-gold",
  left: "badge-muted",
};

function getPlayerStatusMeta(status) {
  const cls = PLAYER_STATUS_CLASSES[status];
  return cls
    ? { label: t(`common.status.${status}`), cls }
    : { label: status, cls: "badge-muted" };
}

function renderDeltaPill(deltaVal) {
  if (deltaVal === null || deltaVal === undefined || !Number.isFinite(Number(deltaVal))) {
    return "";
  }
  const num = Number(deltaVal);
  const cls = num > 0 ? "delta-pos" : num < 0 ? "delta-neg" : "delta-zero";
  const prefix = num > 0 ? "+" : "";
  return `<span class="delta-pill ${cls}">(${escapeHtml(prefix + fmtNum(num))})</span>`;
}

export function renderPlayerDetailPage(container, { playerId, onNavigate }) {
  let feedback = { error: false, text: "" };
  let confirmDeletePlayer = false;
  let confirmDeleteEntryId = null;
  let editingEntryId = null;

  function wireLinks() {
    container.querySelectorAll("[data-link]").forEach((anchor) => {
      anchor.addEventListener("click", (event) => {
        event.preventDefault();
        onNavigate(anchor.getAttribute("href") || "/players");
      });
    });
  }

  async function load() {
    container.setAttribute("aria-busy", "true");
    try {
      const [detail, fieldsRes] = await Promise.all([
        getPlayer(playerId),
        listFields({ activeOnly: false }),
      ]);
      renderContent(detail, fieldsRes.fields || []);
    } catch (err) {
      container.innerHTML = `
        <div class="page-header">
          <h1>${escapeHtml(t("playerDetail.title"))}</h1>
          <a href="/players" data-link class="btn btn-secondary">${escapeHtml(t("playerDetail.backToPlayers"))}</a>
        </div>
        <div class="alert alert-error" role="alert">
          ${escapeHtml(err.message || t("playerDetail.errLoadFailed"))}
        </div>
      `;
      wireLinks();
    } finally {
      container.removeAttribute("aria-busy");
    }
  }

  function renderContent(detail, allFields) {
    const player = detail.player;
    const aliases = detail.aliases || [];
    const entries = detail.progressionEntries || [];
    const recentScores = detail.recentDuelScores || [];

    const activeProfileFields = allFields.filter(
      (f) => f.scope === "profile" && f.is_active !== false
    );
    const activeProgFields = allFields.filter(
      (f) => f.scope === "progression" && f.is_active !== false
    );
    const allProgFields = allFields.filter((f) => f.scope === "progression");
    const numericProgFields = allProgFields.filter((f) => f.field_type === "number");

    const st = getPlayerStatusMeta(player.status);

    const feedbackHtml = feedback.text
      ? `<div class="alert ${feedback.error ? "alert-error" : "alert-success"}" role="${
          feedback.error ? "alert" : "status"
        }" style="margin-bottom: 1rem;">${escapeHtml(feedback.text)}</div>`
      : "";

    const aliasChipsHtml =
      aliases.length === 0
        ? `<span class="muted-text">${escapeHtml(t("playerDetail.emptyAliases"))}</span>`
        : aliases
            .map(
              (a) => `
                <span class="chip">
                  <span>${escapeHtml(a.alias_name)}</span>
                  <button
                    type="button"
                    class="chip-remove"
                    aria-label="${escapeHtml(t("playerDetail.removeAliasAria", { name: a.alias_name }))}"
                    data-delete-alias="${a.id}"
                  >×</button>
                </span>
              `
            )
            .join("");

    // Determine progression metric columns to display (active fields + any historical keys present in entries)
    const progFieldByKey = new Map(allProgFields.map((f) => [f.field_key, f]));
    const displayProgCols = [...activeProgFields];
    const seenKeys = new Set(displayProgCols.map((f) => f.field_key));
    for (const entry of entries) {
      for (const key of Object.keys(entry.metrics || {})) {
        if (!seenKeys.has(key)) {
          seenKeys.add(key);
          displayProgCols.push(
            progFieldByKey.get(key) || {
              field_key: key,
              label: key,
              field_type: "text",
              unit: null,
            }
          );
        }
      }
    }

    const progTableHtml =
      entries.length === 0
        ? `<div class="empty-state">${escapeHtml(t("playerDetail.emptyProgression"))}</div>`
        : `
          <div class="table-wrap">
            <table data-testid="progression-history-table">
              <thead>
                <tr>
                  <th>${escapeHtml(t("playerDetail.colRecordedAt"))}</th>
                  ${displayProgCols
                    .map(
                      (f) =>
                        `<th>${escapeHtml(f.label)}${f.unit ? ` (${escapeHtml(f.unit)})` : ""}</th>`
                    )
                    .join("")}
                  <th>${escapeHtml(t("playerDetail.colNote"))}</th>
                  <th>${escapeHtml(t("playerDetail.colActions"))}</th>
                </tr>
              </thead>
              <tbody>
                ${entries
                  .map((entry) => {
                    if (editingEntryId === entry.id) {
                      return `
                        <tr data-entry-id="${entry.id}" class="editing-row">
                          <td colspan="${displayProgCols.length + 3}">
                            <form data-testid="edit-progression-form-${entry.id}" class="form-stack">
                              <div class="form-grid">
                                <div class="form-field">
                                  <label for="edit-prog-date-${entry.id}">${escapeHtml(t("playerDetail.colRecordedAt"))}</label>
                                  <input
                                    id="edit-prog-date-${entry.id}"
                                    name="recorded_at"
                                    type="date"
                                    required
                                    value="${escapeHtml(String(entry.recorded_at || "").slice(0, 10))}"
                                  >
                                </div>
                                <div class="form-field">
                                  <label for="edit-prog-note-${entry.id}">${escapeHtml(t("playerDetail.colNote"))}</label>
                                  <input
                                    id="edit-prog-note-${entry.id}"
                                    name="note"
                                    type="text"
                                    value="${escapeHtml(entry.note || "")}"
                                  >
                                </div>
                              </div>
                              <div data-edit-prog-fields="${entry.id}">
                                ${renderDynamicFieldInputs(activeProgFields, entry.metrics || {}, {
                                  idPrefix: `edit-prog-${entry.id}`,
                                })}
                              </div>
                              <div class="form-actions">
                                <button type="submit" class="btn btn-primary btn-sm">${escapeHtml(t("common.save"))}</button>
                                <button
                                  type="button"
                                  class="btn btn-secondary btn-sm"
                                  data-cancel-edit-entry="${entry.id}"
                                >${escapeHtml(t("common.discard"))}</button>
                              </div>
                            </form>
                          </td>
                        </tr>
                      `;
                    }

                    const metricCells = displayProgCols
                      .map((f) => {
                        const valHtml = formatFieldValue(f, entry.metrics?.[f.field_key]);
                        const deltaHtml =
                          f.field_type === "number"
                            ? renderDeltaPill(entry.deltas?.[f.field_key])
                            : "";
                        return `<td>${valHtml} ${deltaHtml}</td>`;
                      })
                      .join("");

                    const deleteBtns =
                      confirmDeleteEntryId === entry.id
                        ? `
                            <button type="button" class="btn btn-danger-outline btn-sm" data-confirm-delete-entry="${entry.id}">${escapeHtml(t("common.confirm"))}</button>
                            <button type="button" class="btn btn-secondary btn-sm" data-cancel-delete-entry="${entry.id}">${escapeHtml(t("common.discard"))}</button>
                          `
                        : `<button type="button" class="btn btn-danger-outline btn-sm" data-ask-delete-entry="${entry.id}">${escapeHtml(t("common.delete"))}</button>`;

                    return `
                      <tr data-entry-id="${entry.id}">
                        <td>${escapeHtml(fmtDate(entry.recorded_at))}</td>
                        ${metricCells}
                        <td>${entry.note ? escapeHtml(entry.note) : '<span class="muted-text">—</span>'}</td>
                        <td>
                          <div class="action-row">
                            <button type="button" class="btn btn-secondary btn-sm" data-edit-entry="${entry.id}">${escapeHtml(t("common.edit"))}</button>
                            ${deleteBtns}
                          </div>
                        </td>
                      </tr>
                    `;
                  })
                  .join("")}
              </tbody>
            </table>
          </div>
        `;

    const duelScoresHtml =
      recentScores.length === 0
        ? `<div class="empty-state">${escapeHtml(t("playerDetail.emptyDuelScores"))}</div>`
        : `
          <div class="table-wrap">
            <table data-testid="player-duel-scores-table">
              <thead>
                <tr>
                  <th>${escapeHtml(t("dashboard.colDate"))}</th>
                  <th>${escapeHtml(t("dashboard.colOpponentClan"))}</th>
                  <th>${escapeHtml(t("ocr.colScore"))}</th>
                  <th>${escapeHtml(t("dashboard.colLimitStatus"))}</th>
                </tr>
              </thead>
              <tbody>
                ${recentScores
                  .map((s) => {
                    const duelLabel = s.duel_title
                      ? `${s.opponent_clan_name} — ${s.duel_title}`
                      : s.opponent_clan_name;
                    return `
                      <tr>
                        <td>${escapeHtml(fmtDate(s.score_date))}</td>
                        <td>
                          <a href="/duels/${s.duel_id}" data-link class="text-link">
                            ${escapeHtml(duelLabel)}
                          </a>
                        </td>
                        <td><strong>${escapeHtml(fmtNum(s.score))}</strong></td>
                        <td>${renderLimitBadge(s)}</td>
                      </tr>
                    `;
                  })
                  .join("")}
              </tbody>
            </table>
          </div>
        `;

    const deletePlayerControls = confirmDeletePlayer
      ? `
          <button type="button" class="btn btn-danger-outline btn-sm" data-testid="confirm-delete-player-btn">
            ${escapeHtml(t("playerDetail.confirmDeletePlayer"))}
          </button>
          <button type="button" class="btn btn-secondary btn-sm" data-testid="cancel-delete-player-btn">
            ${escapeHtml(t("common.discard"))}
          </button>
        `
      : `
          <button type="button" class="btn btn-danger-outline btn-sm" data-testid="ask-delete-player-btn">
            ${escapeHtml(t("playerDetail.deletePlayer"))}
          </button>
        `;

    const rankBadgeHtml = player.clan_rank
      ? `<span class="badge ${
          player.clan_rank === "R5" || player.clan_rank === "R4" ? "badge-gold" : "badge-info"
        }" data-testid="player-detail-rank">${escapeHtml(player.clan_rank)}</span>`
      : "";
    const towerBadgeHtml = player.tower_level
      ? `<span class="badge badge-tower" data-testid="player-detail-tower">${escapeHtml(
          player.tower_level
        )}</span>`
      : "";

    container.innerHTML = `
      <div class="page-header">
        <div>
          <a href="/players" data-link class="text-link" style="display: inline-block; margin-bottom: 0.35rem;">
            ${escapeHtml(t("playerDetail.backToPlayers"))}
          </a>
          <div style="display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap;">
            <h1 style="margin: 0;" data-testid="player-detail-name">${escapeHtml(player.display_name)}</h1>
            <span class="badge ${st.cls}">${escapeHtml(st.label)}</span>
            ${rankBadgeHtml}
            ${towerBadgeHtml}
          </div>
        </div>
        <div class="action-row">${deletePlayerControls}</div>
      </div>

      ${feedbackHtml}

      <div class="two-col-grid">
        <section class="card section-card">
          <h2 style="margin-top: 0;">${escapeHtml(t("playerDetail.profileCardTitle"))}</h2>
          <form data-testid="player-edit-form" class="form-stack">
            <div class="form-grid">
              <div class="form-field">
                <label for="edit-player-name">${escapeHtml(t("players.nameLabelRequired"))}</label>
                <input
                  id="edit-player-name"
                  name="display_name"
                  type="text"
                  required
                  value="${escapeHtml(player.display_name)}"
                >
              </div>
              <div class="form-field">
                <label for="edit-player-status">${escapeHtml(t("players.statusLabel"))}</label>
                <select id="edit-player-status" name="status">
                  <option value="active" ${player.status === "active" ? "selected" : ""}>${escapeHtml(t("common.status.active"))}</option>
                  <option value="inactive" ${player.status === "inactive" ? "selected" : ""}>${escapeHtml(t("common.status.inactive"))}</option>
                  <option value="left" ${player.status === "left" ? "selected" : ""}>${escapeHtml(t("common.status.left"))}</option>
                </select>
              </div>
              <div class="form-field">
                <label for="edit-player-rank">${escapeHtml(t("players.rankLabel"))}</label>
                <select id="edit-player-rank" name="clan_rank">
                  ${renderSelectOptions(CLAN_RANKS, player.clan_rank || "", t("common.notSelected"))}
                </select>
              </div>
              <div class="form-field">
                <label for="edit-player-tower">${escapeHtml(t("players.towerLabel"))}</label>
                <select id="edit-player-tower" name="tower_level">
                  ${renderSelectOptions(TOWER_LEVELS, player.tower_level || "", t("common.notSelected"))}
                </select>
              </div>
              <div class="form-field">
                <label for="edit-player-joined">${escapeHtml(t("players.joinedAtLabel"))}</label>
                <input
                  id="edit-player-joined"
                  name="joined_at"
                  type="date"
                  value="${escapeHtml(player.joined_at ? String(player.joined_at).slice(0, 10) : "")}"
                >
              </div>
            </div>
            <div data-testid="edit-player-dynamic-fields">
              ${renderDynamicFieldInputs(activeProfileFields, player.profile_values || {}, {
                idPrefix: "edit-pf",
              })}
            </div>
            <div class="form-field">
              <label for="edit-player-notes">${escapeHtml(t("players.notesLabel"))}</label>
              <textarea id="edit-player-notes" name="notes" rows="2">${escapeHtml(
                player.notes || ""
              )}</textarea>
            </div>
            <div>
              <button type="submit" class="btn btn-primary" data-testid="save-player-btn">
                ${escapeHtml(t("playerDetail.saveProfileBtn"))}
              </button>
            </div>
          </form>
        </section>

        <section class="card section-card" data-testid="aliases-section">
          <h2 style="margin-top: 0;">${escapeHtml(t("playerDetail.aliasesTitle"))}</h2>
          <p class="muted-text">
            ${escapeHtml(t("playerDetail.aliasesDesc"))}
          </p>
          <div class="chip-list" style="margin: 0.75rem 0 1rem;">${aliasChipsHtml}</div>
          <form data-testid="add-alias-form" class="form-inline">
            <div class="form-field" style="flex: 1;">
              <label for="new-alias-input">${escapeHtml(t("playerDetail.newAliasLabel"))}</label>
              <input
                id="new-alias-input"
                name="alias_name"
                type="text"
                required
                placeholder="${escapeHtml(t("playerDetail.newAliasPlaceholder"))}"
              >
            </div>
            <div style="align-self: flex-end;">
              <button type="submit" class="btn btn-secondary">${escapeHtml(t("playerDetail.addAliasBtn"))}</button>
            </div>
          </form>
        </section>
      </div>

      <section class="card section-card" data-testid="progression-section">
        <div class="section-head">
          <div>
            <h2>${escapeHtml(t("playerDetail.progressionTitle"))}</h2>
            <p class="muted-text">${escapeHtml(t("playerDetail.progressionDesc"))}</p>
          </div>
          ${
            activeProgFields.length === 0
              ? `<a href="/settings" data-link class="text-link">${escapeHtml(t("playerDetail.addProgFieldsLink"))}</a>`
              : ""
          }
        </div>

        ${
          activeProgFields.length === 0
            ? `<div class="empty-state" style="margin-top: 0.75rem;">
                 ${escapeHtml(t("playerDetail.noActiveProgMetricsPrefix"))}
                 <a href="/settings" data-link class="text-link">${escapeHtml(t("playerDetail.noActiveProgMetricsLink"))}</a>
                 ${escapeHtml(t("playerDetail.noActiveProgMetricsSuffix"))}
               </div>`
            : `
              <form data-testid="add-progression-form" class="form-stack" style="margin-top: 0.85rem;">
                <div class="form-grid">
                  <div class="form-field">
                    <label for="prog-date">${escapeHtml(t("playerDetail.recordedAtRequired"))}</label>
                    <input id="prog-date" name="recorded_at" type="date" required value="${todayIso()}">
                  </div>
                  <div class="form-field">
                    <label for="prog-note">${escapeHtml(t("playerDetail.colNote"))}</label>
                    <input id="prog-note" name="note" type="text" placeholder="${escapeHtml(t("playerDetail.progNotePlaceholder"))}">
                  </div>
                </div>
                <div data-testid="add-prog-dynamic-fields">
                  ${renderDynamicFieldInputs(activeProgFields, {}, { idPrefix: "add-prog" })}
                </div>
                <div>
                  <button type="submit" class="btn btn-primary" data-testid="add-prog-submit">
                    ${escapeHtml(t("playerDetail.addProgSubmit"))}
                  </button>
                </div>
              </form>
            `
        }

        <div data-testid="progression-trend-chart" style="margin-top: 1.25rem;"></div>
        <div style="margin-top: 1.25rem;">${progTableHtml}</div>
      </section>

      <section class="card section-card" data-testid="player-duel-scores">
        <h2 style="margin-top: 0;">${escapeHtml(t("playerDetail.recentScoresTitle"))}</h2>
        ${duelScoresHtml}
      </section>
    `;

    wireLinks();

    // Render SVG trend chart
    const chartBox = container.querySelector('[data-testid="progression-trend-chart"]');
    if (chartBox) {
      renderTrendChart(chartBox, { entries, numericFields: numericProgFields });
    }

    // Delete player flow
    const askDelPlayer = container.querySelector('[data-testid="ask-delete-player-btn"]');
    if (askDelPlayer) {
      askDelPlayer.addEventListener("click", () => {
        confirmDeletePlayer = true;
        renderContent(detail, allFields);
      });
    }
    const cancelDelPlayer = container.querySelector('[data-testid="cancel-delete-player-btn"]');
    if (cancelDelPlayer) {
      cancelDelPlayer.addEventListener("click", () => {
        confirmDeletePlayer = false;
        renderContent(detail, allFields);
      });
    }
    const confirmDelPlayer = container.querySelector('[data-testid="confirm-delete-player-btn"]');
    if (confirmDelPlayer) {
      confirmDelPlayer.addEventListener("click", async () => {
        confirmDelPlayer.disabled = true;
        try {
          await deletePlayer(playerId);
          onNavigate("/players");
        } catch (err) {
          feedback = { error: true, text: err.message || t("playerDetail.errDeleteFailed") };
          confirmDeletePlayer = false;
          renderContent(detail, allFields);
        }
      });
    }

    // Profile edit form
    const editForm = container.querySelector('[data-testid="player-edit-form"]');
    editForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      feedback = { error: false, text: "" };
      const btn = editForm.querySelector('[data-testid="save-player-btn"]');
      const dynamicWrap = editForm.querySelector('[data-testid="edit-player-dynamic-fields"]');
      const payload = {
        display_name: editForm.querySelector('[name="display_name"]').value.trim(),
        status: editForm.querySelector('[name="status"]').value,
        clan_rank: editForm.querySelector('[name="clan_rank"]').value || null,
        tower_level: editForm.querySelector('[name="tower_level"]').value || null,
        joined_at: editForm.querySelector('[name="joined_at"]').value.trim() || null,
        notes: editForm.querySelector('[name="notes"]').value.trim() || null,
        profile_values: collectDynamicFieldValues(dynamicWrap, activeProfileFields, {
          includeEmptyAsNull: true,
        }),
      };

      btn.disabled = true;
      try {
        await updatePlayer(playerId, payload);
        feedback = { error: false, text: t("playerDetail.msgProfileUpdated") };
        await load();
      } catch (err) {
        feedback = { error: true, text: err.message || t("playerDetail.errProfileUpdateFailed") };
        renderContent(detail, allFields);
      } finally {
        btn.disabled = false;
      }
    });

    // Aliases
    const aliasForm = container.querySelector('[data-testid="add-alias-form"]');
    aliasForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      feedback = { error: false, text: "" };
      const aliasName = aliasForm.querySelector('[name="alias_name"]').value.trim();
      if (!aliasName) return;
      try {
        await addAlias(playerId, aliasName);
        feedback = { error: false, text: t("playerDetail.msgAliasAdded", { alias: aliasName }) };
        await load();
      } catch (err) {
        feedback = { error: true, text: err.message || t("playerDetail.errAliasAddFailed") };
        renderContent(detail, allFields);
      }
    });

    container.querySelectorAll("[data-delete-alias]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const aliasId = Number(btn.getAttribute("data-delete-alias"));
        btn.disabled = true;
        try {
          await deleteAlias(playerId, aliasId);
          feedback = { error: false, text: t("playerDetail.msgAliasRemoved") };
          await load();
        } catch (err) {
          feedback = { error: true, text: err.message || t("playerDetail.errAliasRemoveFailed") };
          renderContent(detail, allFields);
        }
      });
    });

    // Add progression entry
    const addProgForm = container.querySelector('[data-testid="add-progression-form"]');
    if (addProgForm) {
      addProgForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        feedback = { error: false, text: "" };
        const btn = addProgForm.querySelector('[data-testid="add-prog-submit"]');
        const dynamicWrap = addProgForm.querySelector('[data-testid="add-prog-dynamic-fields"]');
        const recordedAt = addProgForm.querySelector('[name="recorded_at"]').value.trim();
        const note = addProgForm.querySelector('[name="note"]').value.trim();
        const metrics = collectDynamicFieldValues(dynamicWrap, activeProgFields);

        if (Object.keys(metrics).length === 0) {
          feedback = { error: true, text: t("playerDetail.errMinOneMetric") };
          renderContent(detail, allFields);
          return;
        }

        btn.disabled = true;
        try {
          await createProgression(playerId, {
            recorded_at: recordedAt,
            metrics,
            note: note || null,
          });
          feedback = { error: false, text: t("playerDetail.msgProgAdded") };
          await load();
        } catch (err) {
          feedback = { error: true, text: err.message || t("playerDetail.errProgAddFailed") };
          renderContent(detail, allFields);
        } finally {
          btn.disabled = false;
        }
      });
    }

    // Progression row edit / delete
    container.querySelectorAll("[data-edit-entry]").forEach((btn) => {
      btn.addEventListener("click", () => {
        editingEntryId = Number(btn.getAttribute("data-edit-entry"));
        confirmDeleteEntryId = null;
        renderContent(detail, allFields);
      });
    });
    container.querySelectorAll("[data-cancel-edit-entry]").forEach((btn) => {
      btn.addEventListener("click", () => {
        editingEntryId = null;
        renderContent(detail, allFields);
      });
    });
    container.querySelectorAll('[data-testid^="edit-progression-form-"]').forEach((form) => {
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const entryId = Number(form.getAttribute("data-testid").replace("edit-progression-form-", ""));
        const fieldsWrap = form.querySelector(`[data-edit-prog-fields="${entryId}"]`);
        const recordedAt = form.querySelector('[name="recorded_at"]').value.trim();
        const note = form.querySelector('[name="note"]').value.trim();
        const metrics = collectDynamicFieldValues(fieldsWrap, activeProgFields, {
          includeEmptyAsNull: true,
        });

        try {
          await updateProgression(entryId, {
            recorded_at: recordedAt,
            metrics,
            note: note || null,
          });
          editingEntryId = null;
          feedback = { error: false, text: t("playerDetail.msgProgUpdated") };
          await load();
        } catch (err) {
          feedback = { error: true, text: err.message || t("playerDetail.errProgUpdateFailed") };
          renderContent(detail, allFields);
        }
      });
    });

    container.querySelectorAll("[data-ask-delete-entry]").forEach((btn) => {
      btn.addEventListener("click", () => {
        confirmDeleteEntryId = Number(btn.getAttribute("data-ask-delete-entry"));
        renderContent(detail, allFields);
      });
    });
    container.querySelectorAll("[data-cancel-delete-entry]").forEach((btn) => {
      btn.addEventListener("click", () => {
        confirmDeleteEntryId = null;
        renderContent(detail, allFields);
      });
    });
    container.querySelectorAll("[data-confirm-delete-entry]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const entryId = Number(btn.getAttribute("data-confirm-delete-entry"));
        btn.disabled = true;
        try {
          await deleteProgression(entryId);
          confirmDeleteEntryId = null;
          feedback = { error: false, text: t("playerDetail.msgProgDeleted") };
          await load();
        } catch (err) {
          feedback = { error: true, text: err.message || t("playerDetail.errProgDeleteFailed") };
          renderContent(detail, allFields);
        }
      });
    });
  }

  load();
}
