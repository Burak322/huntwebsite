import {
  commitWeeklyDiff,
  escapeHtml,
  fmtDate,
  fmtNum,
  previewWeeklyDiff,
  todayIso,
} from "../api.js";
import { t, translateApiMessage } from "../i18n/index.js";

function yesterdayIso() {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  const pad = (x) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function foldNameTr(name) {
  return String(name || "")
    .trim()
    .toLocaleLowerCase("tr-TR");
}

const KNOWN_WD_WARNINGS = new Set([
  "negative_derived_score",
  "missing_today_score",
  "missing_from_weekly",
  "conflicting_duplicate_in_batch",
]);

const KNOWN_OCR_WARNINGS = new Set([
  "digit_repaired",
  "duplicate_matched_player",
  "low_ocr_confidence",
  "fuzzy_match_needs_review",
  "unmatched_player",
  "ambiguous_match",
]);

function getWarningText(w) {
  if (KNOWN_WD_WARNINGS.has(w)) return t(`weeklyDiff.warn.${w}`);
  if (KNOWN_OCR_WARNINGS.has(w)) return t(`ocr.warnings.${w}`);
  return translateApiMessage(w);
}

export function mountWeeklyDiffPanel(
  container,
  { duelId, duel, players = [], recordedDates = [], onCommitted, onCancel }
) {
  const playerList = players || [];
  const playerMap = new Map(playerList.map((p) => [String(p.id), p]));

  let targetDate = yesterdayIso();
  if (duel?.start_date && targetDate < duel.start_date) {
    targetDate = todayIso();
  }
  const todayDate = todayIso();
  let currentPreview = null;
  let prevSumsMap = new Map();

  function renderPrevCheckboxes(dateStr) {
    if (!recordedDates || recordedDates.length === 0) {
      return `<div class="muted-text" style="font-size: 0.85rem;">${escapeHtml(
        t("weeklyDiff.noPreviousDates")
      )}</div>`;
    }
    return `
      <div class="action-row" style="flex-wrap: wrap; gap: 0.65rem;">
        ${recordedDates
          .map((d) => {
            const checked = d.scoreDate < dateStr ? "checked" : "";
            return `
              <label class="checkbox-inline">
                <input type="checkbox" name="prev_date" value="${escapeHtml(d.scoreDate)}" ${checked}>
                <span>${escapeHtml(fmtDate(d.scoreDate))} (${escapeHtml(d.entryCount)})</span>
              </label>
            `;
          })
          .join("")}
      </div>
    `;
  }

  container.innerHTML = `
    <div class="ocr-review-panel card" data-testid="weekly-diff-panel">
      <div class="page-header" style="margin-bottom: 1rem;">
        <div>
          <h3 style="margin: 0;">${escapeHtml(t("weeklyDiff.title"))}</h3>
          <p class="muted-text" style="margin: 0.25rem 0 0;">
            ${escapeHtml(t("weeklyDiff.subtitle"))}
          </p>
        </div>
        <button type="button" class="btn btn-secondary btn-sm" data-testid="wd-cancel-btn">
          ${escapeHtml(t("common.close"))}
        </button>
      </div>

      <form data-testid="weekly-diff-setup-form" class="form-stack">
        <div class="form-grid">
          <div class="form-field">
            <label for="wd-target-date">${escapeHtml(t("weeklyDiff.targetDateLabel"))}</label>
            <input id="wd-target-date" name="target_date" type="date" required value="${escapeHtml(targetDate)}">
          </div>
          <div class="form-field">
            <label for="wd-today-date">${escapeHtml(t("weeklyDiff.todayDateLabel"))}</label>
            <input id="wd-today-date" name="today_date" type="date" value="${escapeHtml(todayDate)}">
          </div>
          <div class="form-field">
            <label for="wd-weekly-files">${escapeHtml(t("weeklyDiff.weeklyFilesLabel"))}</label>
            <input
              id="wd-weekly-files"
              name="weekly_files"
              type="file"
              multiple
              accept="image/png,image/jpeg,image/webp"
              data-testid="wd-weekly-files"
            >
          </div>
          <div class="form-field">
            <label for="wd-today-files">${escapeHtml(t("weeklyDiff.todayFilesLabel"))}</label>
            <input
              id="wd-today-files"
              name="today_files"
              type="file"
              multiple
              accept="image/png,image/jpeg,image/webp"
              data-testid="wd-today-files"
            >
          </div>
        </div>

        <div class="form-field">
          <label>${escapeHtml(t("weeklyDiff.previousDatesLabel"))}</label>
          <div data-testid="wd-prev-dates">${renderPrevCheckboxes(targetDate)}</div>
        </div>

        <div class="form-actions">
          <button type="submit" class="btn btn-primary" data-testid="wd-preview-ocr-btn">
            ${escapeHtml(t("weeklyDiff.previewOcrBtn"))}
          </button>
          <button type="button" class="btn btn-secondary" data-testid="wd-preview-manual-btn">
            ${escapeHtml(t("weeklyDiff.previewManualBtn"))}
          </button>
        </div>
      </form>

      <div class="muted-text hidden" data-testid="wd-loading" style="margin-top: 0.75rem;">
        ${escapeHtml(t("weeklyDiff.loading"))}
      </div>
      <div class="alert alert-error hidden" role="alert" data-testid="wd-error" style="margin-top: 0.75rem;"></div>

      <div data-testid="weekly-diff-review-area" style="margin-top: 1rem;"></div>
    </div>
  `;

  const setupForm = container.querySelector('[data-testid="weekly-diff-setup-form"]');
  const targetInput = setupForm.querySelector("#wd-target-date");
  const todayInput = setupForm.querySelector("#wd-today-date");
  const prevDatesBox = setupForm.querySelector('[data-testid="wd-prev-dates"]');
  const weeklyFilesInput = setupForm.querySelector('[data-testid="wd-weekly-files"]');
  const todayFilesInput = setupForm.querySelector('[data-testid="wd-today-files"]');
  const ocrBtn = setupForm.querySelector('[data-testid="wd-preview-ocr-btn"]');
  const manualBtn = setupForm.querySelector('[data-testid="wd-preview-manual-btn"]');
  const loadingMsg = container.querySelector('[data-testid="wd-loading"]');
  const errorBox = container.querySelector('[data-testid="wd-error"]');
  const reviewArea = container.querySelector('[data-testid="weekly-diff-review-area"]');
  const cancelBtn = container.querySelector('[data-testid="wd-cancel-btn"]');

  cancelBtn.addEventListener("click", () => {
    if (typeof onCancel === "function") onCancel();
  });

  targetInput.addEventListener("change", () => {
    prevDatesBox.innerHTML = renderPrevCheckboxes(targetInput.value);
  });

  function getSelectedPrevDates() {
    return [...prevDatesBox.querySelectorAll('input[name="prev_date"]:checked')].map(
      (cb) => cb.value
    );
  }

  async function runPreview({ includeFiles }) {
    errorBox.classList.add("hidden");
    errorBox.textContent = "";

    const tDate = String(targetInput.value || "").trim();
    if (!tDate) {
      errorBox.textContent = t("weeklyDiff.errTargetDateRequired");
      errorBox.classList.remove("hidden");
      return;
    }

    const fd = new FormData();
    fd.append("target_date", tDate);
    if (todayInput.value.trim()) {
      fd.append("today_date", todayInput.value.trim());
    }
    fd.append("included_previous_dates", JSON.stringify(getSelectedPrevDates()));

    if (includeFiles) {
      for (const f of weeklyFilesInput.files || []) {
        fd.append("weekly_files", f);
      }
      for (const f of todayFilesInput.files || []) {
        fd.append("today_files", f);
      }
    }

    ocrBtn.disabled = true;
    manualBtn.disabled = true;
    loadingMsg.classList.remove("hidden");
    try {
      const res = await previewWeeklyDiff(duelId, fd);
      currentPreview = res;
      prevSumsMap = new Map(
        Object.entries(res.previousSumsByPlayer || {}).map(([k, v]) => [String(k), Number(v || 0)])
      );
      renderReviewTable(res);
    } catch (err) {
      errorBox.textContent = err.message || t("weeklyDiff.errPreviewFailed");
      errorBox.classList.remove("hidden");
    } finally {
      ocrBtn.disabled = false;
      manualBtn.disabled = false;
      loadingMsg.classList.add("hidden");
    }
  }

  setupForm.addEventListener("submit", (event) => {
    event.preventDefault();
    runPreview({ includeFiles: true });
  });

  manualBtn.addEventListener("click", () => {
    runPreview({ includeFiles: false });
  });

  function buildPlayerOptions(selectedId) {
    const opts = [`<option value="">${escapeHtml(t("ocr.unmatchedOption"))}</option>`];
    for (const p of playerList) {
      const sel =
        selectedId !== null && selectedId !== undefined && Number(selectedId) === Number(p.id)
          ? "selected"
          : "";
      opts.push(`<option value="${p.id}" ${sel}>${escapeHtml(p.display_name)}</option>`);
    }
    return opts.join("");
  }

  function renderReviewTable(preview) {
    const missingDates = Array.isArray(preview.missingCalendarDates)
      ? preview.missingCalendarDates
      : [];
    const missingHtml =
      missingDates.length > 0
        ? `<div class="alert alert-error" data-testid="wd-missing-dates-alert" style="margin-bottom: 0.75rem;">
             ${escapeHtml(
               t("weeklyDiff.missingDatesWarning", {
                 dates: missingDates.map((d) => fmtDate(d)).join(", "),
               })
             )}
           </div>`
        : "";

    const initialRows =
      Array.isArray(preview.rows) && preview.rows.length > 0
        ? preview.rows
        : [
            {
              tempId: "wd-manual-1",
              extractedName: "",
              matchedPlayerId: null,
              matchStatus: "unmatched",
              weeklyTotal: 0,
              todayLiveScore: 0,
              previousDaysSum: 0,
              derivedScore: 0,
              needsReview: false,
              warnings: [],
            },
          ];

    const rawDetailsHtml =
      preview.weeklyRawText || preview.todayRawText
        ? `
          <details style="margin-bottom: 0.75rem;">
            <summary class="muted-text" style="cursor: pointer;">${escapeHtml(
              t("ocr.showRawText")
            )}</summary>
            <pre class="raw-ocr-pre">${escapeHtml(
              [preview.weeklyRawText, preview.todayRawText].filter(Boolean).join("\n\n---\n\n")
            )}</pre>
          </details>
        `
        : "";

    reviewArea.innerHTML = `
      ${missingHtml}
      ${rawDetailsHtml}

      <form data-testid="wd-review-form" class="form-stack">
        <div class="form-inline" style="justify-content: space-between;">
          <button type="button" class="btn btn-secondary btn-sm" data-testid="wd-add-row-btn">
            ${escapeHtml(t("ocr.addRowBtn"))}
          </button>
          <label class="checkbox-inline">
            <input type="checkbox" data-testid="wd-save-today-cb">
            <span>${escapeHtml(t("weeklyDiff.saveTodayCheckbox"))}</span>
          </label>
        </div>

        <div class="alert alert-error hidden" role="alert" data-testid="wd-commit-error"></div>

        <div class="table-wrap">
          <table data-testid="wd-review-table">
            <thead>
              <tr>
                <th>${escapeHtml(t("weeklyDiff.colPlayer"))}</th>
                <th>${escapeHtml(t("weeklyDiff.colMatchedPlayer"))}</th>
                <th>${escapeHtml(t("weeklyDiff.colWeeklyTotal"))}</th>
                <th>${escapeHtml(t("weeklyDiff.colTodayLive"))}</th>
                <th>${escapeHtml(t("weeklyDiff.colPreviousSum"))}</th>
                <th>${escapeHtml(t("weeklyDiff.colDerivedScore"))}</th>
                <th>${escapeHtml(t("weeklyDiff.colStatus"))}</th>
                <th>${escapeHtml(t("weeklyDiff.colOptions"))}</th>
                <th></th>
              </tr>
            </thead>
            <tbody data-testid="wd-review-tbody"></tbody>
          </table>
        </div>

        <div class="form-actions">
          <button type="submit" class="btn btn-primary" data-testid="wd-commit-btn">
            ${escapeHtml(t("weeklyDiff.commitBtn"))}
          </button>
        </div>
      </form>
    `;

    const reviewForm = reviewArea.querySelector('[data-testid="wd-review-form"]');
    const tbody = reviewArea.querySelector('[data-testid="wd-review-tbody"]');
    const commitErr = reviewArea.querySelector('[data-testid="wd-commit-error"]');
    const commitBtn = reviewArea.querySelector('[data-testid="wd-commit-btn"]');
    const addRowBtn = reviewArea.querySelector('[data-testid="wd-add-row-btn"]');
    const saveTodayCb = reviewArea.querySelector('[data-testid="wd-save-today-cb"]');

    function updateRowState(tr, { recalc = false } = {}) {
      const wInput = tr.querySelector('[data-col="weeklyTotal"]');
      const tInput = tr.querySelector('[data-col="todayLiveScore"]');
      const pInput = tr.querySelector('[data-col="previousDaysSum"]');
      const dInput = tr.querySelector('[data-col="derivedScore"]');
      const setZeroBtn = tr.querySelector('[data-action="set-zero"]');
      const negBadge = tr.querySelector('[data-neg-badge]');

      if (recalc) {
        const w = Number(wInput.value || 0);
        const tVal = Number(tInput.value || 0);
        const prev = Number(pInput.value || 0);
        dInput.value = String(Math.trunc(w - tVal - prev));
      }

      const derived = Number(dInput.value || 0);
      const isNeg = derived < 0;
      tr.classList.toggle("row-needs-review", isNeg);
      if (setZeroBtn) setZeroBtn.classList.toggle("hidden", !isNeg);
      if (negBadge) negBadge.classList.toggle("hidden", !isNeg);
    }

    function syncAliasCreateFlags(tr) {
      const playerSel = tr.querySelector('[data-col="playerId"]');
      const nameInput = tr.querySelector('[data-col="extractedName"]');
      const saveAliasCb = tr.querySelector('[data-col="saveAlias"]');
      const createCb = tr.querySelector('[data-col="createPlayer"]');
      const pid = playerSel.value;

      if (pid) {
        createCb.checked = false;
        const p = playerMap.get(pid);
        if (p && !nameInput.value.trim()) {
          nameInput.value = p.display_name;
        }
        const sameName = p && foldNameTr(nameInput.value) === foldNameTr(p.display_name);
        saveAliasCb.disabled = sameName;
        if (sameName) saveAliasCb.checked = false;
      } else {
        saveAliasCb.checked = false;
        saveAliasCb.disabled = true;
      }
    }

    function appendRow(row) {
      const tr = document.createElement("tr");
      const warnBadges = (row.warnings || [])
        .filter((w) => w !== "negative_derived_score")
        .map((w) => `<span class="badge badge-muted">${escapeHtml(getWarningText(w))}</span>`)
        .join(" ");

      const pid = row.matchedPlayerId;
      const isNeg = Number(row.derivedScore || 0) < 0;

      tr.innerHTML = `
        <td>
          <input
            type="text"
            class="table-input"
            data-col="extractedName"
            required
            value="${escapeHtml(row.extractedName || "")}"
          >
        </td>
        <td>
          <select class="table-input" data-col="playerId">
            ${buildPlayerOptions(pid)}
          </select>
        </td>
        <td>
          <input
            type="number"
            class="table-input table-input-num"
            data-col="weeklyTotal"
            min="0"
            step="1"
            value="${escapeHtml(row.weeklyTotal ?? 0)}"
          >
        </td>
        <td>
          <input
            type="number"
            class="table-input table-input-num"
            data-col="todayLiveScore"
            min="0"
            step="1"
            value="${escapeHtml(row.todayLiveScore ?? 0)}"
          >
        </td>
        <td>
          <input
            type="number"
            class="table-input table-input-num"
            data-col="previousDaysSum"
            min="0"
            step="1"
            value="${escapeHtml(row.previousDaysSum ?? 0)}"
          >
        </td>
        <td>
          <div class="action-row">
            <input
              type="number"
              class="table-input table-input-num"
              data-col="derivedScore"
              step="1"
              required
              value="${escapeHtml(row.derivedScore ?? 0)}"
            >
            <button
              type="button"
              class="btn btn-secondary btn-sm ${isNeg ? "" : "hidden"}"
              data-action="set-zero"
            >${escapeHtml(t("weeklyDiff.setZeroBtn"))}</button>
          </div>
        </td>
        <td>
          <div class="status-stack">
            <span class="badge badge-danger ${isNeg ? "" : "hidden"}" data-neg-badge>${escapeHtml(
              t("weeklyDiff.warn.negative_derived_score")
            )}</span>
            ${warnBadges}
          </div>
        </td>
        <td>
          <div class="checkbox-stack">
            <label class="checkbox-inline">
              <input type="checkbox" data-col="saveAlias">
              <span>${escapeHtml(t("ocr.saveAlias"))}</span>
            </label>
            <label class="checkbox-inline">
              <input type="checkbox" data-col="createPlayer">
              <span>${escapeHtml(t("ocr.createPlayer"))}</span>
            </label>
          </div>
        </td>
        <td>
          <button type="button" class="btn btn-danger-outline btn-sm" data-action="remove-row">
            ${escapeHtml(t("common.delete"))}
          </button>
        </td>
      `;

      const playerSel = tr.querySelector('[data-col="playerId"]');
      const nameInput = tr.querySelector('[data-col="extractedName"]');
      const wInput = tr.querySelector('[data-col="weeklyTotal"]');
      const tInput = tr.querySelector('[data-col="todayLiveScore"]');
      const pInput = tr.querySelector('[data-col="previousDaysSum"]');
      const dInput = tr.querySelector('[data-col="derivedScore"]');
      const createCb = tr.querySelector('[data-col="createPlayer"]');
      const setZeroBtn = tr.querySelector('[data-action="set-zero"]');
      const removeBtn = tr.querySelector('[data-action="remove-row"]');

      playerSel.addEventListener("change", () => {
        const selectedPid = playerSel.value;
        if (selectedPid && prevSumsMap.has(selectedPid)) {
          pInput.value = String(prevSumsMap.get(selectedPid));
        } else if (!selectedPid) {
          pInput.value = "0";
        }
        syncAliasCreateFlags(tr);
        updateRowState(tr, { recalc: true });
      });

      nameInput.addEventListener("input", () => syncAliasCreateFlags(tr));
      wInput.addEventListener("input", () => updateRowState(tr, { recalc: true }));
      tInput.addEventListener("input", () => updateRowState(tr, { recalc: true }));
      pInput.addEventListener("input", () => updateRowState(tr, { recalc: true }));
      dInput.addEventListener("input", () => updateRowState(tr, { recalc: false }));

      setZeroBtn.addEventListener("click", () => {
        dInput.value = "0";
        updateRowState(tr, { recalc: false });
      });

      createCb.addEventListener("change", () => {
        if (createCb.checked) playerSel.value = "";
        syncAliasCreateFlags(tr);
      });

      removeBtn.addEventListener("click", () => tr.remove());

      syncAliasCreateFlags(tr);
      updateRowState(tr, { recalc: false });
      tbody.appendChild(tr);
    }

    for (const r of initialRows) {
      appendRow(r);
    }

    addRowBtn.addEventListener("click", () => {
      appendRow({
        extractedName: "",
        matchedPlayerId: null,
        weeklyTotal: 0,
        todayLiveScore: 0,
        previousDaysSum: 0,
        derivedScore: 0,
        warnings: [],
      });
    });

    reviewForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      commitErr.classList.add("hidden");
      commitErr.textContent = "";

      const trList = [...tbody.querySelectorAll("tr")];
      if (trList.length === 0) {
        commitErr.textContent = t("ocr.errMinOneRow");
        commitErr.classList.remove("hidden");
        return;
      }

      const rowsPayload = [];
      const seenPlayerIds = new Set();

      for (let i = 0; i < trList.length; i += 1) {
        const tr = trList[i];
        const extractedName = tr.querySelector('[data-col="extractedName"]').value.trim();
        const pidVal = tr.querySelector('[data-col="playerId"]').value;
        const weeklyTotal = Math.max(0, Math.trunc(Number(tr.querySelector('[data-col="weeklyTotal"]').value || 0)));
        const todayLiveScore = Math.max(0, Math.trunc(Number(tr.querySelector('[data-col="todayLiveScore"]').value || 0)));
        const previousDaysSum = Math.max(0, Math.trunc(Number(tr.querySelector('[data-col="previousDaysSum"]').value || 0)));
        const derivedScore = Number(tr.querySelector('[data-col="derivedScore"]').value);
        const createPlayer = tr.querySelector('[data-col="createPlayer"]').checked;
        const saveAlias = tr.querySelector('[data-col="saveAlias"]').checked;

        if (!extractedName) {
          commitErr.textContent = t("ocr.errRowNameEmpty", { row: i + 1 });
          commitErr.classList.remove("hidden");
          return;
        }
        if (!Number.isInteger(derivedScore) || derivedScore < 0) {
          commitErr.textContent = t("weeklyDiff.errNegativeDerived", {
            row: i + 1,
            score: fmtNum(derivedScore),
          });
          commitErr.classList.remove("hidden");
          return;
        }
        const playerId = pidVal ? Number(pidVal) : null;
        if (playerId !== null) {
          if (seenPlayerIds.has(playerId)) {
            commitErr.textContent = t("ocr.errRowDuplicatePlayer", { row: i + 1 });
            commitErr.classList.remove("hidden");
            return;
          }
          seenPlayerIds.add(playerId);
        }

        rowsPayload.push({
          extractedName,
          playerId,
          weeklyTotal,
          todayLiveScore,
          previousDaysSum,
          derivedScore,
          createPlayer: playerId === null ? createPlayer : false,
          saveAlias: playerId !== null ? saveAlias : false,
        });
      }

      commitBtn.disabled = true;
      commitBtn.textContent = t("weeklyDiff.savingBtn");
      try {
        const res = await commitWeeklyDiff(duelId, {
          target_date: currentPreview.targetDate,
          today_date: currentPreview.todayDate || null,
          save_today_scores: Boolean(saveTodayCb.checked),
          included_previous_dates: currentPreview.includedPreviousDates || [],
          rows: rowsPayload,
        });
        if (typeof onCommitted === "function") {
          await onCommitted(res);
        }
      } catch (err) {
        commitErr.textContent = err.message || t("weeklyDiff.errCommitFailed");
        commitErr.classList.remove("hidden");
      } finally {
        commitBtn.disabled = false;
        commitBtn.textContent = t("weeklyDiff.commitBtn");
      }
    });
  }
}
