import { escapeHtml, fmtDate, fmtNum } from "../api.js";
import { t } from "../i18n/index.js";

export function renderTrendChart(container, { entries, numericFields }) {
  const fields = (numericFields || []).filter((f) => f.field_type === "number");
  if (fields.length === 0) {
    container.innerHTML = `<div class="empty-state">${escapeHtml(t("trend.noNumericFields"))}</div>`;
    return;
  }

  let selectedKey = fields[0].field_key;

  const sortedEntries = [...(entries || [])].sort((a, b) => {
    const cmp = String(a.recorded_at || "").localeCompare(String(b.recorded_at || ""));
    if (cmp !== 0) return cmp;
    return Number(a.id || 0) - Number(b.id || 0);
  });

  function draw() {
    const field = fields.find((f) => f.field_key === selectedKey) || fields[0];
    const unit = field.unit ? ` ${field.unit}` : "";

    const points = [];
    for (const entry of sortedEntries) {
      const val = entry.metrics?.[field.field_key];
      if (typeof val === "number" && Number.isFinite(val)) {
        points.push({ date: entry.recorded_at, value: val });
      }
    }

    const selectOptions = fields
      .map(
        (f) =>
          `<option value="${escapeHtml(f.field_key)}" ${
            f.field_key === field.field_key ? "selected" : ""
          }>${escapeHtml(f.label)}${f.unit ? ` (${escapeHtml(f.unit)})` : ""}</option>`
      )
      .join("");

    let chartBodyHtml = "";
    if (points.length < 2) {
      chartBodyHtml = `<div class="empty-state">${escapeHtml(t("trend.needTwoPoints"))}</div>`;
    } else {
      const W = 640;
      const H = 240;
      const padL = 72;
      const padR = 24;
      const padT = 20;
      const padB = 38;
      const plotW = W - padL - padR;
      const plotH = H - padT - padB;

      const vals = points.map((p) => p.value);
      let minVal = Math.min(...vals);
      let maxVal = Math.max(...vals);
      if (minVal === maxVal) {
        minVal -= 1;
        maxVal += 1;
      }
      const range = maxVal - minVal;

      const coords = points.map((p, idx) => {
        const x = padL + (idx / (points.length - 1)) * plotW;
        const y = padT + (1 - (p.value - minVal) / range) * plotH;
        return { x, y, ...p };
      });

      const gridValues = [minVal, minVal + range * 0.5, maxVal];
      const gridLines = gridValues
        .map((gv) => {
          const y = padT + (1 - (gv - minVal) / range) * plotH;
          const label = Number.isInteger(gv) ? fmtNum(gv) : fmtNum(Math.round(gv * 100) / 100);
          return `
            <line x1="${padL}" y1="${y.toFixed(1)}" x2="${W - padR}" y2="${y.toFixed(
              1
            )}" stroke="var(--border)" stroke-dasharray="4 4" stroke-width="1" />
            <text x="${padL - 8}" y="${(y + 4).toFixed(
              1
            )}" text-anchor="end" fill="var(--text-muted)" font-size="11">${escapeHtml(label)}</text>
          `;
        })
        .join("");

      const polylinePts = coords.map((c) => `${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(" ");
      const circles = coords
        .map(
          (c) => `
            <circle cx="${c.x.toFixed(1)}" cy="${c.y.toFixed(
              1
            )}" r="4.5" fill="var(--gold)" stroke="var(--bg)" stroke-width="1.5">
              <title>${escapeHtml(fmtDate(c.date))}: ${escapeHtml(fmtNum(c.value) + unit)}</title>
            </circle>
          `
        )
        .join("");

      const labelIndices =
        coords.length === 2 ? [0, 1] : [0, Math.floor((coords.length - 1) / 2), coords.length - 1];
      const xLabels = labelIndices
        .map((idx) => {
          const c = coords[idx];
          const anchor = idx === 0 ? "start" : idx === coords.length - 1 ? "end" : "middle";
          return `
            <text x="${c.x.toFixed(1)}" y="${H - 10}" text-anchor="${anchor}" fill="var(--text-muted)" font-size="11">
              ${escapeHtml(fmtDate(c.date))}
            </text>
          `;
        })
        .join("");

      chartBodyHtml = `
        <svg class="trend-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="${escapeHtml(
          t("trend.ariaLabel", { label: field.label })
        )}">
          ${gridLines}
          <polyline fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" points="${polylinePts}" />
          ${circles}
          ${xLabels}
        </svg>
      `;
    }

    container.innerHTML = `
      <div class="trend-chart-wrap">
        <div class="trend-chart-header">
          <strong>${escapeHtml(t("trend.title"))}</strong>
          <label class="trend-select-label">
            <span>${escapeHtml(t("trend.metricLabel"))}</span>
            <select data-testid="trend-metric-select">${selectOptions}</select>
          </label>
        </div>
        ${chartBodyHtml}
      </div>
    `;

    const sel = container.querySelector('[data-testid="trend-metric-select"]');
    if (sel) {
      sel.addEventListener("change", () => {
        selectedKey = sel.value;
        draw();
      });
    }
  }

  draw();
}
