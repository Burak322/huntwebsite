import {
  CLAN_RANKS,
  TOWER_LEVELS,
  bulkImportPlayers,
  escapeHtml,
  extractPlayersFromPhoto,
  renderSelectOptions,
  todayIso,
} from "../api.js";
import { t } from "../i18n/index.js";
import {
  collectDynamicFieldValues,
  renderDynamicFieldInputs,
} from "./dynamicFields.js";

function foldNameTr(name) {
  return String(name || "")
    .trim()
    .replaceAll("İ", "i")
    .replaceAll("I", "ı")
    .toLowerCase();
}

export function mountPlayerPhotoImport(
  container,
  { profileFields = [], progFields = [], onImported, onCancel }
) {
  let previewObjectUrl = null;
  let currentExtraction = null;

  function revokePreview() {
    if (previewObjectUrl) {
      URL.revokeObjectURL(previewObjectUrl);
      previewObjectUrl = null;
    }
  }

  function closePanel() {
    revokePreview();
    currentExtraction = null;
    if (typeof onCancel === "function") {
      onCancel();
    }
  }

  container.innerHTML = `
    <div class="section-head" style="margin-bottom: 0.75rem;">
      <div>
        <h2 style="margin: 0;">${escapeHtml(t("photoImport.title"))}</h2>
        <p class="muted-text" style="margin: 0.25rem 0 0;">
          ${escapeHtml(t("photoImport.subtitle"))}
        </p>
      </div>
      <button type="button" class="btn btn-secondary btn-sm" data-testid="player-photo-cancel-btn">
        ${escapeHtml(t("common.close"))}
      </button>
    </div>

    <form data-testid="player-photo-upload-form" class="form-inline">
      <div class="form-field" style="flex: 1; min-width: 240px;">
        <label for="player-photo-file">${escapeHtml(t("photoImport.fileLabel"))}</label>
        <input
          id="player-photo-file"
          name="file"
          type="file"
          accept="image/png,image/jpeg,image/webp"
          required
          data-testid="player-photo-file-input"
        >
      </div>
      <div style="align-self: flex-end;">
        <button type="submit" class="btn btn-primary" data-testid="player-photo-extract-btn">
          ${escapeHtml(t("photoImport.scanBtn"))}
        </button>
      </div>
    </form>

    <div class="muted-text hidden" data-testid="player-photo-loading" style="margin-top: 0.75rem;">
      ${escapeHtml(t("photoImport.loading"))}
    </div>
    <div class="alert alert-error hidden" role="alert" data-testid="player-photo-error" style="margin-top: 0.75rem;"></div>

    <div data-testid="player-import-review-area" style="margin-top: 1rem;"></div>
  `;

  const uploadForm = container.querySelector('[data-testid="player-photo-upload-form"]');
  const cancelBtn = container.querySelector('[data-testid="player-photo-cancel-btn"]');
  const loadingMsg = container.querySelector('[data-testid="player-photo-loading"]');
  const uploadError = container.querySelector('[data-testid="player-photo-error"]');
  const extractBtn = container.querySelector('[data-testid="player-photo-extract-btn"]');
  const reviewArea = container.querySelector('[data-testid="player-import-review-area"]');

  cancelBtn.addEventListener("click", closePanel);

  function renderReviewPanel() {
    if (!currentExtraction) {
      reviewArea.innerHTML = "";
      return;
    }

    const rawCandidates = Array.isArray(currentExtraction.candidates)
      ? currentExtraction.candidates
      : [];
    const emptyExtraction = rawCandidates.length === 0;
    const rowsData = emptyExtraction
      ? [
          {
            extractedName: "",
            cleanName: "",
            suggestedAlias: "",
            detectedNumber: null,
            alreadyExists: false,
            matchedPlayerName: null,
            matchStatus: "unmatched",
            needsReview: false,
            warnings: [],
          },
        ]
      : rawCandidates;

    const numericProgFields = (progFields || []).filter((f) => f.field_type === "number");
    const metricSelectHtml =
      numericProgFields.length > 0
        ? `
          <div class="form-field">
            <label for="imp-metric-select">${escapeHtml(t("photoImport.saveMetricLabel"))}</label>
            <select
              id="imp-metric-select"
              name="metric_field_key"
              data-testid="player-import-metric-select"
            >
              <option value="">${escapeHtml(t("photoImport.saveMetricNone"))}</option>
              ${numericProgFields
                .map(
                  (f) =>
                    `<option value="${escapeHtml(f.field_key)}">${escapeHtml(f.label)}${
                      f.unit ? ` (${escapeHtml(f.unit)})` : ""
                    }</option>`
                )
                .join("")}
            </select>
          </div>
        `
        : "";

    const hasRequiredProfile = (profileFields || []).some((f) => Boolean(f.is_required));
    const profileDefaultsHtml =
      (profileFields || []).length > 0
        ? `
          <details class="import-profile-details" ${hasRequiredProfile ? "open" : ""}>
            <summary class="muted-text" style="cursor: pointer;">
              ${escapeHtml(t("photoImport.defaultProfileTitle"))}${escapeHtml(
                hasRequiredProfile
                  ? t("photoImport.requiredSuffix")
                  : t("photoImport.optionalSuffix")
              )}
            </summary>
            <div data-testid="player-import-default-profile" style="margin-top: 0.75rem;">
              ${renderDynamicFieldInputs(profileFields, {}, { idPrefix: "imp-pf" })}
            </div>
          </details>
        `
        : "";

    const emptyNoticeHtml = emptyExtraction
      ? `<div class="alert alert-error" style="margin-bottom: 0.75rem;">
           ${escapeHtml(t("photoImport.emptyNotice"))}
         </div>`
      : "";

    reviewArea.innerHTML = `
      <div class="ocr-review-grid">
        <div class="ocr-preview-col">
          <div class="ocr-preview-box">
            <img
              src="${escapeHtml(previewObjectUrl || "")}"
              alt="${escapeHtml(t("photoImport.previewAlt"))}"
              class="ocr-preview-img"
              data-testid="player-import-preview-image"
            >
          </div>
          <details style="margin-top: 0.75rem;">
            <summary class="muted-text" style="cursor: pointer;">${escapeHtml(
              t("ocr.showRawText")
            )}</summary>
            <pre class="raw-ocr-pre">${escapeHtml(currentExtraction.rawText || t("common.empty"))}</pre>
          </details>
        </div>

        <form class="ocr-form-col" data-testid="player-import-review-form">
          ${emptyNoticeHtml}

          <div class="import-defaults-box">
            <div class="form-grid">
              <div class="form-field">
                <label for="imp-joined-at">${escapeHtml(t("photoImport.joinedAtLabel"))}</label>
                <input id="imp-joined-at" name="joined_at" type="date" value="${todayIso()}">
              </div>
              ${metricSelectHtml}
            </div>
            ${profileDefaultsHtml}
          </div>

          <div class="form-inline" style="margin: 0.85rem 0; justify-content: space-between;">
            <div class="action-row">
              <button type="button" class="btn btn-secondary btn-sm" data-testid="import-select-new-btn">
                ${escapeHtml(t("photoImport.selectAllNewBtn"))}
              </button>
              <button type="button" class="btn btn-secondary btn-sm" data-testid="import-clear-sel-btn">
                ${escapeHtml(t("photoImport.clearSelectionBtn"))}
              </button>
              <button type="button" class="btn btn-secondary btn-sm" data-testid="import-add-row-btn">
                ${escapeHtml(t("ocr.addRowBtn"))}
              </button>
            </div>
            <span class="badge badge-info" data-testid="import-selected-count">${escapeHtml(
              t("photoImport.selectedCount", { count: 0 })
            )}</span>
          </div>

          <div class="alert alert-error hidden" role="alert" data-testid="player-import-commit-error" style="margin-bottom: 0.75rem;"></div>

          <div class="table-wrap">
            <table data-testid="player-import-table">
              <thead>
                <tr>
                  <th>${escapeHtml(t("photoImport.colSelect"))}</th>
                  <th>${escapeHtml(t("photoImport.colPlayerNameRequired"))}</th>
                  <th>${escapeHtml(t("photoImport.colAlias"))}</th>
                  <th>${escapeHtml(t("photoImport.colStatus"))}</th>
                  <th>${escapeHtml(t("photoImport.colRank"))}</th>
                  <th>${escapeHtml(t("photoImport.colTower"))}</th>
                  <th>${escapeHtml(t("photoImport.colNumber"))}</th>
                  <th>${escapeHtml(t("photoImport.colMatch"))}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody data-testid="player-import-tbody"></tbody>
            </table>
          </div>

          <div class="form-actions" style="margin-top: 1rem;">
            <button type="submit" class="btn btn-primary" data-testid="player-import-commit-btn">
              ${escapeHtml(t("photoImport.commitBtn"))}
            </button>
          </div>
        </form>
      </div>
    `;

    const reviewForm = reviewArea.querySelector('[data-testid="player-import-review-form"]');
    const tbody = reviewArea.querySelector('[data-testid="player-import-tbody"]');
    const countBadge = reviewArea.querySelector('[data-testid="import-selected-count"]');
    const commitErr = reviewArea.querySelector('[data-testid="player-import-commit-error"]');
    const commitBtn = reviewArea.querySelector('[data-testid="player-import-commit-btn"]');
    const selectNewBtn = reviewArea.querySelector('[data-testid="import-select-new-btn"]');
    const clearSelBtn = reviewArea.querySelector('[data-testid="import-clear-sel-btn"]');
    const addRowBtn = reviewArea.querySelector('[data-testid="import-add-row-btn"]');
    const profileWrap = reviewArea.querySelector('[data-testid="player-import-default-profile"]');

    function updateSelectedCount() {
      const checkedCount = tbody.querySelectorAll('input[data-col="selected"]:checked').length;
      countBadge.textContent = t("photoImport.selectedCount", { count: checkedCount });
    }

    function appendRow(cand) {
      const tr = document.createElement("tr");
      const alreadyExists = Boolean(cand.alreadyExists);
      tr.setAttribute("data-already-exists", alreadyExists ? "1" : "0");
      if (alreadyExists) {
        tr.classList.add("row-existing");
      } else if (cand.needsReview) {
        tr.classList.add("row-needs-review");
      }

      let matchBadgeHtml = `<span class="badge badge-success">${escapeHtml(
        t("photoImport.badgeNewPlayer")
      )}</span>`;
      if (alreadyExists) {
        matchBadgeHtml = `<span class="badge badge-muted">${escapeHtml(
          t("photoImport.badgeAlreadyExists", {
            name: cand.matchedPlayerName || cand.cleanName || "",
          })
        )}</span>`;
      } else if (cand.matchStatus === "fuzzy_review") {
        matchBadgeHtml = `<span class="badge badge-gold">${escapeHtml(
          t("photoImport.badgeSimilar", { name: cand.matchedPlayerName || "" })
        )}</span>`;
      }

      const lowConfBadge = (cand.warnings || []).includes("low_ocr_confidence")
        ? `<span class="badge badge-muted">${escapeHtml(
            t("ocr.warnings.low_ocr_confidence")
          )}</span>`
        : "";

      const nameVal = cand.cleanName || cand.extractedName || "";
      const aliasVal = cand.suggestedAlias || "";
      const numVal =
        cand.detectedNumber !== null && cand.detectedNumber !== undefined
          ? String(cand.detectedNumber)
          : "";

      tr.innerHTML = `
        <td>
          <input
            type="checkbox"
            class="table-input-check"
            data-col="selected"
            aria-label="${escapeHtml(t("photoImport.ariaSelectPlayer"))}"
            ${alreadyExists ? "" : "checked"}
          >
        </td>
        <td>
          <input
            type="text"
            class="table-input"
            data-col="display_name"
            aria-label="${escapeHtml(t("ocr.ariaPlayerName"))}"
            value="${escapeHtml(nameVal)}"
          >
        </td>
        <td>
          <input
            type="text"
            class="table-input"
            data-col="alias"
            aria-label="${escapeHtml(t("photoImport.ariaAlias"))}"
            placeholder="${escapeHtml(t("common.optional"))}"
            value="${escapeHtml(aliasVal)}"
          >
        </td>
        <td>
          <select class="table-input" data-col="status" aria-label="${escapeHtml(t("ocr.colStatus"))}">
            <option value="active" selected>${escapeHtml(t("common.status.active"))}</option>
            <option value="inactive">${escapeHtml(t("common.status.inactive"))}</option>
            <option value="left">${escapeHtml(t("common.status.left"))}</option>
          </select>
        </td>
        <td>
          <select class="table-input" data-col="clan_rank" aria-label="${escapeHtml(
            t("photoImport.colRank")
          )}">
            ${renderSelectOptions(CLAN_RANKS, cand.detectedRank || "", "—")}
          </select>
        </td>
        <td>
          <select class="table-input" data-col="tower_level" aria-label="${escapeHtml(
            t("players.colTower")
          )}">
            ${renderSelectOptions(TOWER_LEVELS, cand.detectedTowerLevel || "", "—")}
          </select>
        </td>
        <td>
          <input
            type="number"
            class="table-input table-input-num"
            data-col="detectedNumber"
            aria-label="${escapeHtml(t("photoImport.ariaDetectedNumber"))}"
            step="any"
            value="${escapeHtml(numVal)}"
          >
        </td>
        <td>
          <div class="status-stack">
            ${matchBadgeHtml}
            ${lowConfBadge}
          </div>
        </td>
        <td>
          <button type="button" class="btn btn-danger-outline btn-sm" data-action="remove-import-row">
            ${escapeHtml(t("common.delete"))}
          </button>
        </td>
      `;

      tr.querySelector('[data-col="selected"]').addEventListener("change", updateSelectedCount);
      tr.querySelector('[data-action="remove-import-row"]').addEventListener("click", () => {
        tr.remove();
        updateSelectedCount();
      });

      tbody.appendChild(tr);
      updateSelectedCount();
    }

    for (const c of rowsData) {
      appendRow(c);
    }

    selectNewBtn.addEventListener("click", () => {
      tbody.querySelectorAll("tr").forEach((tr) => {
        const isExisting = tr.getAttribute("data-already-exists") === "1";
        tr.querySelector('[data-col="selected"]').checked = !isExisting;
      });
      updateSelectedCount();
    });

    clearSelBtn.addEventListener("click", () => {
      tbody.querySelectorAll('[data-col="selected"]').forEach((cb) => {
        cb.checked = false;
      });
      updateSelectedCount();
    });

    addRowBtn.addEventListener("click", () => {
      appendRow({
        extractedName: "",
        cleanName: "",
        suggestedAlias: "",
        detectedNumber: null,
        alreadyExists: false,
        matchStatus: "unmatched",
        needsReview: false,
        warnings: [],
      });
    });

    reviewForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      commitErr.classList.add("hidden");
      commitErr.textContent = "";

      const joinedAt = reviewForm.querySelector('[name="joined_at"]').value.trim() || null;
      const metricSelect = reviewForm.querySelector('[data-testid="player-import-metric-select"]');
      const metricKey = metricSelect ? metricSelect.value : "";
      const defaultProfile = profileWrap
        ? collectDynamicFieldValues(profileWrap, profileFields)
        : {};

      const selectedRows = [...tbody.querySelectorAll("tr")].filter(
        (tr) => tr.querySelector('[data-col="selected"]').checked
      );

      if (selectedRows.length === 0) {
        commitErr.textContent = t("photoImport.errMinOneSelected");
        commitErr.classList.remove("hidden");
        return;
      }

      const playersPayload = [];
      const seenNames = new Set();

      for (let i = 0; i < selectedRows.length; i += 1) {
        const tr = selectedRows[i];
        const displayName = tr.querySelector('[data-col="display_name"]').value.trim();
        const aliasVal = tr.querySelector('[data-col="alias"]').value.trim();
        const statusVal = tr.querySelector('[data-col="status"]').value;
        const rankVal = tr.querySelector('[data-col="clan_rank"]').value || null;
        const towerVal = tr.querySelector('[data-col="tower_level"]').value || null;
        const rawNum = tr.querySelector('[data-col="detectedNumber"]').value.trim();

        if (!displayName) {
          commitErr.textContent = t("photoImport.errSelectedRowEmpty", { row: i + 1 });
          commitErr.classList.remove("hidden");
          return;
        }

        const folded = foldNameTr(displayName);
        if (seenNames.has(folded)) {
          commitErr.textContent = t("photoImport.errDuplicateSelectedName", { name: displayName });
          commitErr.classList.remove("hidden");
          return;
        }
        seenNames.add(folded);

        let initialMetrics = null;
        if (metricKey && rawNum !== "") {
          const parsedNum = Number(rawNum);
          if (!Number.isFinite(parsedNum)) {
            commitErr.textContent = t("photoImport.errInvalidNumber", { name: displayName });
            commitErr.classList.remove("hidden");
            return;
          }
          initialMetrics = { [metricKey]: parsedNum };
        }

        const aliases =
          aliasVal && foldNameTr(aliasVal) !== folded ? [aliasVal] : [];

        playersPayload.push({
          display_name: displayName,
          status: statusVal,
          clan_rank: rankVal,
          tower_level: towerVal,
          joined_at: joinedAt,
          profile_values: defaultProfile,
          aliases,
          initial_metrics: initialMetrics,
        });
      }

      commitBtn.disabled = true;
      commitBtn.textContent = t("photoImport.addingBtn");
      try {
        const res = await bulkImportPlayers({
          players: playersPayload,
          skip_existing: true,
          recorded_at: joinedAt,
        });
        revokePreview();
        currentExtraction = null;
        if (typeof onImported === "function") {
          await onImported(res);
        }
      } catch (err) {
        commitErr.textContent = err.message || t("photoImport.errCommitFailed");
        commitErr.classList.remove("hidden");
      } finally {
        commitBtn.disabled = false;
        commitBtn.textContent = t("photoImport.commitBtn");
      }
    });
  }

  uploadForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    uploadError.classList.add("hidden");
    uploadError.textContent = "";

    const fileInput = uploadForm.querySelector('[name="file"]');
    const file = fileInput.files?.[0];
    if (!file) {
      uploadError.textContent = t("photoImport.errNoPhotoSelected");
      uploadError.classList.remove("hidden");
      return;
    }

    extractBtn.disabled = true;
    loadingMsg.classList.remove("hidden");
    try {
      const result = await extractPlayersFromPhoto(file);
      revokePreview();
      previewObjectUrl = URL.createObjectURL(file);
      currentExtraction = result;
      renderReviewPanel();
    } catch (err) {
      uploadError.textContent = err.message || t("photoImport.errScanFailed");
      uploadError.classList.remove("hidden");
    } finally {
      extractBtn.disabled = false;
      loadingMsg.classList.add("hidden");
    }
  });
}
