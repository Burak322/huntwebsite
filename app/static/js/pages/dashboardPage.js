import {
  escapeHtml,
  fmtDate,
  fmtNum,
  getDashboard,
  setDailyLimit,
} from "../api.js";
import { t } from "../i18n/index.js";
import { renderComplianceSummary, renderLimitBadge } from "../components/limitBadge.js";

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

export function renderDashboardPage(container, { authState, onNavigate }) {
  const safeClanName = escapeHtml(authState.clanName || t("common.defaultClanName"));
  const safeUsername = escapeHtml(authState.admin?.username || t("common.defaultAdminName"));
  let feedbackMsg = "";
  let feedbackIsError = false;

  function wireLinks() {
    container.querySelectorAll("[data-link]").forEach((anchor) => {
      anchor.addEventListener("click", (event) => {
        event.preventDefault();
        onNavigate(anchor.getAttribute("href") || "/");
      });
    });
  }

  async function load() {
    container.setAttribute("aria-busy", "true");
    try {
      const data = await getDashboard();
      renderContent(data);
    } catch (err) {
      container.innerHTML = `
        <div class="page-header"><h1>${escapeHtml(t("dashboard.title"))}</h1></div>
        <div class="alert alert-error" role="alert">
          ${escapeHtml(err.message || t("dashboard.errLoadFailed"))}
        </div>
      `;
    } finally {
      container.removeAttribute("aria-busy");
    }
  }

  function renderContent(data) {
    const activeLimit = Number(data.activeDailyMinScore ?? 0);
    const pCounts = data.playerCounts || { active: 0, total: 0 };
    const dCounts = data.duelCounts || { ongoing: 0, total: 0 };
    const comp = data.latestDayCompliance || { total: 0, met: 0, missed: 0 };
    const evaluations = Array.isArray(data.latestDayEvaluations) ? data.latestDayEvaluations : [];
    const recentDuels = Array.isArray(data.recentDuels) ? data.recentDuels : [];

    const feedbackHtml = feedbackMsg
      ? `<div class="alert ${feedbackIsError ? "alert-error" : "alert-success"}" role="${
          feedbackIsError ? "alert" : "status"
        }" style="margin-bottom: 1rem;">${escapeHtml(feedbackMsg)}</div>`
      : "";

    const evalRowsHtml =
      evaluations.length === 0
        ? `<tr><td colspan="4" class="empty-cell">${escapeHtml(t("dashboard.emptyEvaluations"))}</td></tr>`
        : evaluations
            .map((ev) => {
              const nameCell =
                ev.playerId !== null && ev.playerId !== undefined
                  ? `<a href="/players/${ev.playerId}" data-link class="text-link">${escapeHtml(
                      ev.playerName
                    )}</a>`
                  : escapeHtml(ev.playerName);
              return `
                <tr>
                  <td>${nameCell}</td>
                  <td><strong>${escapeHtml(fmtNum(ev.totalScore))}</strong></td>
                  <td>${escapeHtml(fmtNum(ev.activeDailyMinScore))}</td>
                  <td>${renderLimitBadge(ev)}</td>
                </tr>
              `;
            })
            .join("");

    const duelsHtml =
      recentDuels.length === 0
        ? `<div class="empty-state">${escapeHtml(t("dashboard.emptyDuelsBeforeLink"))}<a href="/duels" data-link class="text-link">${escapeHtml(t("dashboard.emptyDuelsLink"))}</a>.</div>`
        : `
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>${escapeHtml(t("dashboard.colOpponentClan"))}</th>
                  <th>${escapeHtml(t("dashboard.colDate"))}</th>
                  <th>${escapeHtml(t("dashboard.colStatus"))}</th>
                  <th>${escapeHtml(t("dashboard.colTotalScore"))}</th>
                  <th>${escapeHtml(t("dashboard.colLatestCompliance"))}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                ${recentDuels
                  .map((d) => {
                    const st = getDuelStatusMeta(d.status);
                    const titleText = d.title
                      ? `${escapeHtml(d.opponent_clan_name)} — ${escapeHtml(d.title)}`
                      : escapeHtml(d.opponent_clan_name);
                    return `
                      <tr>
                        <td>
                          <a href="/duels/${d.id}" data-link class="text-link">
                            <strong>${titleText}</strong>
                          </a>
                        </td>
                        <td>${escapeHtml(fmtDate(d.start_date))}</td>
                        <td><span class="badge ${st.cls}">${escapeHtml(st.label)}</span></td>
                        <td>${escapeHtml(fmtNum(d.totalScore))}</td>
                        <td>${renderComplianceSummary(d.latestDayCompliance)}</td>
                        <td>
                          <a href="/duels/${d.id}" data-link class="btn btn-secondary btn-sm">${escapeHtml(t("common.detail"))}</a>
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
          <h1>${escapeHtml(t("dashboard.title"))}</h1>
          <p class="muted-text" style="margin: 0.25rem 0 0;">
            ${escapeHtml(t("dashboard.welcomePrefix"))} <strong>${safeUsername}</strong> · ${escapeHtml(t("dashboard.activeClanLabel"))}
            <strong style="color: var(--gold);">${safeClanName}</strong>
          </p>
        </div>
        <span class="badge badge-success">${escapeHtml(t("dashboard.sessionActiveBadge"))}</span>
      </div>

      ${feedbackHtml}

      <div class="stats-grid">
        <div class="stat-card card">
          <div class="stat-label">${escapeHtml(t("dashboard.statActivePlayers"))}</div>
          <div class="stat-value">${escapeHtml(fmtNum(pCounts.active))}</div>
          <div class="stat-sub">${escapeHtml(t("dashboard.statTotalRegistered", { count: fmtNum(pCounts.total) }))}</div>
        </div>
        <div class="stat-card card">
          <div class="stat-label">${escapeHtml(t("dashboard.statOngoingDuels"))}</div>
          <div class="stat-value">${escapeHtml(fmtNum(dCounts.ongoing))}</div>
          <div class="stat-sub">${escapeHtml(t("dashboard.statTotalDuels", { count: fmtNum(dCounts.total) }))}</div>
        </div>
        <div class="stat-card card">
          <div class="stat-label">${escapeHtml(t("dashboard.statActiveLimit"))}</div>
          <div class="stat-value" style="color: var(--gold);" data-testid="dashboard-active-limit">
            ${escapeHtml(fmtNum(activeLimit))}
          </div>
          <div class="stat-sub">${escapeHtml(t("dashboard.statInstantApply"))}</div>
        </div>
        <div class="stat-card card">
          <div class="stat-label">${escapeHtml(t("dashboard.statLatestCompliance"))}</div>
          <div class="stat-value">${escapeHtml(comp.met)} / ${escapeHtml(comp.total)}</div>
          <div class="stat-sub">${escapeHtml(t("dashboard.statBelowLimit", { count: comp.missed }))}</div>
        </div>
      </div>

      <section class="card section-card">
        <div class="section-head">
          <div>
            <h2>${escapeHtml(t("dashboard.quickLimitTitle"))}</h2>
            <p class="muted-text">${escapeHtml(t("dashboard.quickLimitSubtitle"))}</p>
          </div>
          <a href="/settings" data-link class="text-link">${escapeHtml(t("dashboard.limitHistoryLink"))}</a>
        </div>
        <form data-testid="dashboard-limit-form" class="form-inline" style="margin-top: 0.85rem;">
          <div class="form-field">
            <label for="dash-limit-input">${escapeHtml(t("dashboard.minDailyLimitLabel"))}</label>
            <input
              id="dash-limit-input"
              name="minScore"
              type="number"
              min="0"
              step="1"
              required
              value="${escapeHtml(activeLimit)}"
            >
          </div>
          <div class="form-field" style="flex: 1; min-width: 200px;">
            <label for="dash-limit-note">${escapeHtml(t("dashboard.noteOptionalLabel"))}</label>
            <input
              id="dash-limit-note"
              name="note"
              type="text"
              placeholder="${escapeHtml(t("dashboard.notePlaceholder"))}"
            >
          </div>
          <div style="align-self: flex-end;">
            <button type="submit" class="btn btn-primary" data-testid="dashboard-limit-submit">
              ${escapeHtml(t("dashboard.updateLimitBtn"))}
            </button>
          </div>
        </form>
      </section>

      <section class="card section-card">
        <div class="section-head">
          <h2>${escapeHtml(t("dashboard.latestEvalTitle"))} ${
            data.latestScoreDate ? `(${escapeHtml(fmtDate(data.latestScoreDate))})` : ""
          }</h2>
          ${renderComplianceSummary(comp)}
        </div>
        <div class="table-wrap" style="margin-top: 0.85rem;">
          <table data-testid="dashboard-compliance-table">
            <thead>
              <tr>
                <th>${escapeHtml(t("dashboard.colPlayer"))}</th>
                <th>${escapeHtml(t("dashboard.colDailyScore"))}</th>
                <th>${escapeHtml(t("dashboard.colActiveLimit"))}</th>
                <th>${escapeHtml(t("dashboard.colLimitStatus"))}</th>
              </tr>
            </thead>
            <tbody>${evalRowsHtml}</tbody>
          </table>
        </div>
      </section>

      <section class="card section-card">
        <div class="section-head">
          <h2>${escapeHtml(t("dashboard.recentDuelsTitle"))}</h2>
          <a href="/duels" data-link class="btn btn-secondary btn-sm">${escapeHtml(t("dashboard.allDuelsBtn"))}</a>
        </div>
        <div style="margin-top: 0.85rem;">${duelsHtml}</div>
      </section>
    `;

    wireLinks();

    const limitForm = container.querySelector('[data-testid="dashboard-limit-form"]');
    if (limitForm) {
      limitForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const minInput = limitForm.querySelector('[name="minScore"]');
        const noteInput = limitForm.querySelector('[name="note"]');
        const submitBtn = limitForm.querySelector('button[type="submit"]');
        const minVal = Number(minInput.value);

        if (!Number.isInteger(minVal) || minVal < 0) {
          feedbackIsError = true;
          feedbackMsg = t("dashboard.errLimitInvalid");
          renderContent(data);
          return;
        }

        submitBtn.disabled = true;
        try {
          await setDailyLimit(minVal, noteInput.value.trim());
          feedbackIsError = false;
          feedbackMsg = t("dashboard.msgLimitUpdated", { limit: fmtNum(minVal) });
          await load();
        } catch (err) {
          feedbackIsError = true;
          feedbackMsg = err.message || t("dashboard.errLimitUpdateFailed");
          renderContent(data);
        } finally {
          submitBtn.disabled = false;
        }
      });
    }
  }

  load();
}
