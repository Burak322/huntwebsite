import {
  createDuel,
  escapeHtml,
  fmtDate,
  fmtNum,
  listDuels,
  todayIso,
} from "../api.js";
import { t } from "../i18n/index.js";
import { renderComplianceSummary } from "../components/limitBadge.js";

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

export function renderDuelsPage(container, { onNavigate }) {
  let showCreate = false;
  let successMsg = "";
  let errorMsg = "";

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
      const data = await listDuels();
      renderContent(data);
    } catch (err) {
      container.innerHTML = `
        <div class="page-header"><h1>${escapeHtml(t("nav.duels"))}</h1></div>
        <div class="alert alert-error" role="alert">
          ${escapeHtml(err.message || t("duels.errLoadFailed"))}
        </div>
      `;
    } finally {
      container.removeAttribute("aria-busy");
    }
  }

  function renderContent(data) {
    const duels = Array.isArray(data.duels) ? data.duels : [];
    const activeLimit = Number(data.activeDailyMinScore ?? 0);

    const feedbackHtml = `
      ${
        successMsg
          ? `<div class="alert alert-success" role="status" style="margin-bottom: 1rem;">${escapeHtml(
              successMsg
            )}</div>`
          : ""
      }
      ${
        errorMsg
          ? `<div class="alert alert-error" role="alert" style="margin-bottom: 1rem;">${escapeHtml(
              errorMsg
            )}</div>`
          : ""
      }
    `;

    const listHtml =
      duels.length === 0
        ? `<div class="empty-state">${escapeHtml(t("duels.emptyList"))}</div>`
        : `
          <div class="table-wrap">
            <table data-testid="duels-table">
              <thead>
                <tr>
                  <th>${escapeHtml(t("dashboard.colOpponentClan"))}</th>
                  <th>${escapeHtml(t("duels.colTitle"))}</th>
                  <th>${escapeHtml(t("duels.colDateRange"))}</th>
                  <th>${escapeHtml(t("dashboard.colStatus"))}</th>
                  <th>${escapeHtml(t("duels.colParticipants"))}</th>
                  <th>${escapeHtml(t("dashboard.colTotalScore"))}</th>
                  <th>${escapeHtml(t("dashboard.colLatestCompliance"))}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                ${duels
                  .map((d) => {
                    const st = getDuelStatusMeta(d.status);
                    const dateRange = d.end_date
                      ? `${fmtDate(d.start_date)} – ${fmtDate(d.end_date)}`
                      : fmtDate(d.start_date);
                    return `
                      <tr data-duel-id="${d.id}">
                        <td>
                          <a href="/duels/${d.id}" data-link class="text-link">
                            <strong>${escapeHtml(d.opponent_clan_name)}</strong>
                          </a>
                        </td>
                        <td>${d.title ? escapeHtml(d.title) : '<span class="muted-text">—</span>'}</td>
                        <td>${escapeHtml(dateRange)}</td>
                        <td><span class="badge ${st.cls}">${escapeHtml(st.label)}</span></td>
                        <td>${escapeHtml(fmtNum(d.participantCount))}</td>
                        <td><strong>${escapeHtml(fmtNum(d.totalScore))}</strong></td>
                        <td>${renderComplianceSummary(d.latestDayCompliance)}</td>
                        <td>
                          <a href="/duels/${d.id}" data-link class="btn btn-secondary btn-sm">${escapeHtml(t("duels.openDetailBtn"))}</a>
                        </td>
                      </tr>
                    `;
                  })
                  .join("")}
              </tbody>
            </table>
          </div>
        `;

    container.innerHTML = `
      <div class="page-header">
        <div>
          <h1>${escapeHtml(t("nav.duels"))}</h1>
          <p class="muted-text" style="margin: 0.25rem 0 0;">
            ${escapeHtml(t("duels.activeLimitPrefix"))}
            <strong style="color: var(--gold);">${escapeHtml(fmtNum(activeLimit))}</strong>
          </p>
        </div>
        <button type="button" class="btn btn-primary" data-testid="toggle-create-duel-btn">
          ${escapeHtml(t("duels.newDuelBtn"))}
        </button>
      </div>

      ${feedbackHtml}

      <section class="card section-card ${showCreate ? "" : "hidden"}" data-testid="create-duel-section">
        <h2 style="margin-top: 0;">${escapeHtml(t("duels.createCardTitle"))}</h2>
        <form data-testid="create-duel-form" class="form-stack">
          <div class="form-grid">
            <div class="form-field">
              <label for="duel-opponent">${escapeHtml(t("duels.opponentNameRequired"))}</label>
              <input
                id="duel-opponent"
                name="opponent_clan_name"
                type="text"
                required
                placeholder="${escapeHtml(t("duels.opponentPlaceholder"))}"
              >
            </div>
            <div class="form-field">
              <label for="duel-title">${escapeHtml(t("duels.duelTitleLabel"))}</label>
              <input
                id="duel-title"
                name="title"
                type="text"
                placeholder="${escapeHtml(t("duels.titlePlaceholder"))}"
              >
            </div>
            <div class="form-field">
              <label for="duel-start">${escapeHtml(t("duels.startDateRequired"))}</label>
              <input
                id="duel-start"
                name="start_date"
                type="date"
                required
                value="${todayIso()}"
              >
            </div>
            <div class="form-field">
              <label for="duel-end">${escapeHtml(t("duels.endDateLabel"))}</label>
              <input id="duel-end" name="end_date" type="date">
            </div>
            <div class="form-field">
              <label for="duel-status">${escapeHtml(t("dashboard.colStatus"))}</label>
              <select id="duel-status" name="status">
                <option value="ongoing">${escapeHtml(t("duels.status.ongoing"))}</option>
                <option value="completed">${escapeHtml(t("duels.status.completed"))}</option>
                <option value="cancelled">${escapeHtml(t("duels.status.cancelled"))}</option>
              </select>
            </div>
          </div>
          <div class="form-field">
            <label for="duel-notes">${escapeHtml(t("duels.notesLabel"))}</label>
            <textarea id="duel-notes" name="notes" rows="2" placeholder="${escapeHtml(t("duels.notesPlaceholder"))}"></textarea>
          </div>
          <div class="form-actions">
            <button type="submit" class="btn btn-primary" data-testid="create-duel-submit">
              ${escapeHtml(t("duels.createSubmitBtn"))}
            </button>
            <button type="button" class="btn btn-secondary" data-testid="cancel-create-duel-btn">
              ${escapeHtml(t("common.cancel"))}
            </button>
          </div>
        </form>
      </section>

      <section class="card section-card" data-testid="duels-list">
        ${listHtml}
      </section>
    `;

    wireLinks();

    const toggleBtn = container.querySelector('[data-testid="toggle-create-duel-btn"]');
    const cancelBtn = container.querySelector('[data-testid="cancel-create-duel-btn"]');
    const createSection = container.querySelector('[data-testid="create-duel-section"]');
    const createForm = container.querySelector('[data-testid="create-duel-form"]');

    toggleBtn.addEventListener("click", () => {
      showCreate = !showCreate;
      createSection.classList.toggle("hidden", !showCreate);
    });

    cancelBtn.addEventListener("click", () => {
      showCreate = false;
      createSection.classList.add("hidden");
    });

    createForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      errorMsg = "";
      successMsg = "";

      const submitBtn = createForm.querySelector('[data-testid="create-duel-submit"]');
      const payload = {
        opponent_clan_name: createForm.querySelector('[name="opponent_clan_name"]').value.trim(),
        title: createForm.querySelector('[name="title"]').value.trim() || null,
        start_date: createForm.querySelector('[name="start_date"]').value.trim(),
        end_date: createForm.querySelector('[name="end_date"]').value.trim() || null,
        status: createForm.querySelector('[name="status"]').value,
        notes: createForm.querySelector('[name="notes"]').value.trim() || null,
      };

      submitBtn.disabled = true;
      try {
        const res = await createDuel(payload);
        showCreate = false;
        successMsg = t("duels.msgCreated", { name: res.duel.opponent_clan_name });
        await load();
      } catch (err) {
        errorMsg = err.message || t("duels.errCreateFailed");
        renderContent(data);
      } finally {
        submitBtn.disabled = false;
      }
    });
  }

  load();
}
