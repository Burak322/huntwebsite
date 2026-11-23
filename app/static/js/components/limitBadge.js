import { escapeHtml, fmtNum } from "../api.js";
import { t } from "../i18n/index.js";

export function renderLimitBadge({ meetsLimit, delta, completionPct, activeDailyMinScore }) {
  const met = Boolean(meetsLimit);
  const safeDelta = Number(delta || 0);
  const safePct = Number.isFinite(Number(completionPct)) ? Math.max(0, Number(completionPct)) : 0;
  const barWidth = Math.min(100, safePct);

  const badgeHtml = met
    ? `<span class="badge badge-success" data-limit-status="met">${escapeHtml(t("limit.metBadge"))}</span>`
    : `<span class="badge badge-danger" data-limit-status="missed">${escapeHtml(t("limit.missedBadge"))}</span>`;

  const deltaPrefix = safeDelta > 0 ? "+" : "";
  const deltaClass = safeDelta > 0 ? "delta-pos" : safeDelta < 0 ? "delta-neg" : "delta-zero";
  const deltaTitle =
    activeDailyMinScore !== undefined && activeDailyMinScore !== null
      ? t("limit.activeLimitTooltip", { limit: fmtNum(activeDailyMinScore) })
      : "";

  return `
    <div class="limit-cell" title="${escapeHtml(deltaTitle)}">
      <div class="limit-cell-top">
        ${badgeHtml}
        <span class="${deltaClass} limit-delta">${escapeHtml(deltaPrefix + fmtNum(safeDelta))}</span>
        <span class="limit-pct">${escapeHtml(t("limit.pct", { pct: safePct }))}</span>
      </div>
      <div class="progress-track" aria-hidden="true">
        <div class="progress-fill ${met ? "met" : "missed"}" style="width: ${barWidth}%;"></div>
      </div>
    </div>
  `;
}

export function renderComplianceSummary(compliance) {
  const total = Number(compliance?.total || 0);
  const met = Number(compliance?.met || 0);
  const missed = Number(compliance?.missed || 0);

  if (total === 0) {
    return `<span class="badge badge-muted">${escapeHtml(t("limit.noRecords"))}</span>`;
  }

  return `
    <div class="compliance-pills">
      <span class="badge badge-success">${escapeHtml(t("limit.metCount", { count: met }))}</span>
      <span class="badge badge-danger">${escapeHtml(t("limit.missedCount", { count: missed }))}</span>
      <span class="badge badge-muted">${escapeHtml(t("limit.totalCount", { count: total }))}</span>
    </div>
  `;
}
