import { commitScreenshot, escapeHtml } from "../api.js";
import { t, translateApiMessage } from "../i18n/index.js";

const MATCH_STATUS_CLASSES = {
  exact: "badge-success",
  alias: "badge-info",
  case_insensitive: "badge-success",
  fuzzy: "badge-gold",
  unmatched: "badge-danger",
};

const KNOWN_WARNING_KEYS = new Set([
  "digit_repaired",
  "duplicate_matched_player",
  "low_ocr_confidence",
  "fuzzy_match_needs_review",
  "unmatched_player",
  "ambiguous_match",
]);

function getMatchStatusMeta(status) {
  const cls = MATCH_STATUS_CLASSES[status] || "badge-danger";
  const key = Object.prototype.hasOwnProperty.call(MATCH_STATUS_CLASSES, status)
    ? status
    : "unmatched";
  return { label: t(`ocr.matchStatus.${key}`), cls };
}

function getWarningLabel(warning) {
  if (KNOWN_WARNING_KEYS.has(warning)) {
    return t(`ocr.warnings.${warning}`);
  }
  return translateApiMessage(warning);
}

function foldNameTr(name) {
  return String(name || "")
    .trim()
    .toLocaleLowerCase("tr-TR");
}

export function mountOcrReview(container, { duelId, extraction, players, onCommitted, onCancel }) {
  const playerList = players || [];
  const playerMap = new Map(playerList.map((p) => [String(p.id), p]));

  const initialRows =
    Array.isArray(extraction.parsedRows) && extraction.parsedRows.length > 0
      ? extraction.parsedRows
      : [
          {
            tempId: "manual-1",
            extractedName: "",
            extractedScore: 0,
            matchedPlayerId: null,
            matchStatus: "unmatched",
            needsReview: true,
            warnings: [],
          },
        ];

  const extWarnings = Array.isArray(extraction.warnings) ? extraction.warnings : [];
  const warningHtml =
    extWarnings.length > 0
      ? `<div class="alert alert-error" style="margin-bottom: 0.75rem;">${extWarnings
          .map((w) => escapeHtml(translateApiMessage(w)))
          .join("<br>")}</div>`
      : "";

  container.innerHTML = `
    <div class="ocr-review-panel card" data-testid="ocr-review-panel">
      <div class="page-header" style="margin-bottom: 1rem;">
        <div>
          <h3 style="margin: 0;">${escapeHtml(t("ocr.title"))}</h3>
          <p class="muted-text" style="margin: 0.25rem 0 0;">
            ${escapeHtml(t("ocr.subtitle"))}
            ${extraction.passUsed ? escapeHtml(t("ocr.passUsed", { pass: extraction.passUsed })) : ""}
          </p>
        </div>
        <button type="button" class="btn btn-secondary btn-sm" data-testid="ocr-cancel-btn">${escapeHtml(
          t("common.discard")
        )}</button>
      </div>

      ${warningHtml}

      <div class="ocr-review-grid">
        <div class="ocr-preview-col">
          <div class="ocr-preview-box">
            <img
              src="${escapeHtml(extraction.imageUrl)}"
              alt="${escapeHtml(t("ocr.previewAlt"))}"
              class="ocr-preview-img"
              data-testid="ocr-preview-image"
            >
          </div>
          <div style="margin-top: 0.5rem; display: flex; justify-content: space-between; align-items: center;">
            <a href="${escapeHtml(extraction.imageUrl)}" target="_blank" rel="noopener" class="text-link">
              ${escapeHtml(t("ocr.openFullSize"))}
            </a>
          </div>
          <details style="margin-top: 0.75rem;">
            <summary class="muted-text" style="cursor: pointer;">${escapeHtml(
              t("ocr.showRawText")
            )}</summary>
            <pre class="raw-ocr-pre">${escapeHtml(extraction.rawText || t("common.empty"))}</pre>
          </details>
        </div>

        <form class="ocr-form-col" data-testid="ocr-review-form">
          <div class="form-inline" style="margin-bottom: 0.9rem;">
            <div class="form-field" style="max-width: 220px;">
              <label for="ocr-commit-date">${escapeHtml(t("ocr.scoreDateLabel"))}</label>
              <input
                id="ocr-commit-date"
                name="score_date"
                type="date"
                required
                value="${escapeHtml(extraction.scoreDate || "")}"
              >
            </div>
            <div style="align-self: flex-end;">
              <button type="button" class="btn btn-secondary btn-sm" data-testid="ocr-add-row-btn">
                ${escapeHtml(t("ocr.addRowBtn"))}
              </button>
            </div>
          </div>

          <div class="alert alert-error hidden" role="alert" data-testid="ocr-commit-error"></div>

          <div class="table-wrap">
            <table data-testid="ocr-review-table">
              <thead>
                <tr>
                  <th>${escapeHtml(t("ocr.colDetectedName"))}</th>
                  <th>${escapeHtml(t("ocr.colScore"))}</th>
                  <th>${escapeHtml(t("ocr.colPlayerMatch"))}</th>
                  <th>${escapeHtml(t("ocr.colStatus"))}</th>
                  <th>${escapeHtml(t("ocr.colOptions"))}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody data-testid="ocr-review-tbody"></tbody>
            </table>
          </div>

          <div class="form-actions" style="margin-top: 1rem;">
            <button type="submit" class="btn btn-primary" data-testid="ocr-commit-btn">
              ${escapeHtml(t("ocr.commitBtn"))}
            </button>
          </div>
        </form>
      </div>
    </div>
  `;

  const tbody = container.querySelector('[data-testid="ocr-review-tbody"]');
  const form = container.querySelector('[data-testid="ocr-review-form"]');
  const errorBox = container.querySelector('[data-testid="ocr-commit-error"]');
  const commitBtn = container.querySelector('[data-testid="ocr-commit-btn"]');
  const addRowBtn = container.querySelector('[data-testid="ocr-add-row-btn"]');
  const cancelBtn = container.querySelector('[data-testid="ocr-cancel-btn"]');

  function buildPlayerOptions(selectedId) {
    const opts = [`<option value="">${escapeHtml(t("ocr.unmatchedOption"))}</option>`];
    for (const p of playerList) {
      const sel = selectedId !== null && selectedId !== undefined && Number(selectedId) === Number(p.id)
        ? "selected"
        : "";
      opts.push(`<option value="${p.id}" ${sel}>${escapeHtml(p.display_name)}</option>`);
    }
    return opts.join("");
  }

  function syncRowFlags(tr) {
    const playerSel = tr.querySelector('[data-col="playerId"]');
    const nameInput = tr.querySelector('[data-col="extractedName"]');
    const saveAliasCb = tr.querySelector('[data-col="saveAlias"]');
    const createCb = tr.querySelector('[data-col="createPlayer"]');
    const pid = playerSel.value;

    if (pid) {
      createCb.checked = false;
      const player = playerMap.get(pid);
      const sameName =
        player && foldNameTr(nameInput.value) === foldNameTr(player.display_name);
      saveAliasCb.disabled = sameName;
      if (sameName) {
        saveAliasCb.checked = false;
      }
    } else {
      saveAliasCb.checked = false;
      saveAliasCb.disabled = true;
    }
  }

  function appendRow(rowData) {
    const tr = document.createElement("tr");
    if (rowData.needsReview) {
      tr.classList.add("row-needs-review");
    }

    const meta = getMatchStatusMeta(rowData.matchStatus);
    const warningBadges = (rowData.warnings || [])
      .map((w) => `<span class="badge badge-muted">${escapeHtml(getWarningLabel(w))}</span>`)
      .join(" ");

    const pid = rowData.matchedPlayerId;
    const matchedPlayer = pid != null ? playerMap.get(String(pid)) : null;
    const precheckAlias =
      matchedPlayer &&
      foldNameTr(rowData.extractedName) !== foldNameTr(matchedPlayer.display_name);

    tr.innerHTML = `
      <td>
        <input
          type="text"
          class="table-input"
          data-col="extractedName"
          aria-label="${escapeHtml(t("ocr.ariaPlayerName"))}"
          required
          value="${escapeHtml(rowData.extractedName || "")}"
        >
      </td>
      <td>
        <input
          type="number"
          class="table-input table-input-num"
          data-col="score"
          aria-label="${escapeHtml(t("ocr.ariaScore"))}"
          min="0"
          step="1"
          required
          value="${escapeHtml(rowData.extractedScore ?? 0)}"
        >
      </td>
      <td>
        <select class="table-input" data-col="playerId" aria-label="${escapeHtml(
          t("ocr.ariaMatchedPlayer")
        )}">
          ${buildPlayerOptions(pid)}
        </select>
      </td>
      <td>
        <div class="status-stack">
          <span class="badge ${meta.cls}">${escapeHtml(meta.label)}</span>
          ${warningBadges}
        </div>
      </td>
      <td>
        <div class="checkbox-stack">
          <label class="checkbox-inline">
            <input type="checkbox" data-col="saveAlias" ${precheckAlias ? "checked" : ""}>
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
    const createCb = tr.querySelector('[data-col="createPlayer"]');
    const removeBtn = tr.querySelector('[data-action="remove-row"]');

    playerSel.addEventListener("change", () => syncRowFlags(tr));
    nameInput.addEventListener("input", () => syncRowFlags(tr));
    createCb.addEventListener("change", () => {
      if (createCb.checked) {
        playerSel.value = "";
      }
      syncRowFlags(tr);
    });
    removeBtn.addEventListener("click", () => tr.remove());

    syncRowFlags(tr);
    tbody.appendChild(tr);
  }

  for (const row of initialRows) {
    appendRow(row);
  }

  addRowBtn.addEventListener("click", () => {
    appendRow({
      extractedName: "",
      extractedScore: 0,
      matchedPlayerId: null,
      matchStatus: "unmatched",
      needsReview: true,
      warnings: [],
    });
  });

  cancelBtn.addEventListener("click", () => {
    if (typeof onCancel === "function") onCancel();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorBox.classList.add("hidden");
    errorBox.textContent = "";

    const scoreDate = String(form.querySelector('[name="score_date"]').value || "").trim();
    if (!scoreDate) {
      errorBox.textContent = t("ocr.errScoreDateRequired");
      errorBox.classList.remove("hidden");
      return;
    }

    const trList = [...tbody.querySelectorAll("tr")];
    if (trList.length === 0) {
      errorBox.textContent = t("ocr.errMinOneRow");
      errorBox.classList.remove("hidden");
      return;
    }

    const rowsPayload = [];
    const seenPlayerIds = new Set();

    for (let i = 0; i < trList.length; i += 1) {
      const tr = trList[i];
      const extractedName = tr.querySelector('[data-col="extractedName"]').value.trim();
      const rawScore = tr.querySelector('[data-col="score"]').value.trim();
      const pidVal = tr.querySelector('[data-col="playerId"]').value;
      const createPlayer = tr.querySelector('[data-col="createPlayer"]').checked;
      const saveAlias = tr.querySelector('[data-col="saveAlias"]').checked;

      if (!extractedName) {
        errorBox.textContent = t("ocr.errRowNameEmpty", { row: i + 1 });
        errorBox.classList.remove("hidden");
        return;
      }

      const parsedScore = Number(rawScore);
      if (!rawScore || !Number.isInteger(parsedScore) || parsedScore < 0) {
        errorBox.textContent = t("ocr.errRowScoreInvalid", { row: i + 1 });
        errorBox.classList.remove("hidden");
        return;
      }

      const playerId = pidVal ? Number(pidVal) : null;
      if (playerId !== null) {
        if (seenPlayerIds.has(playerId)) {
          errorBox.textContent = t("ocr.errRowDuplicatePlayer", { row: i + 1 });
          errorBox.classList.remove("hidden");
          return;
        }
        seenPlayerIds.add(playerId);
      }

      rowsPayload.push({
        extractedName,
        score: parsedScore,
        playerId,
        createPlayer: playerId === null ? createPlayer : false,
        saveAlias: playerId !== null ? saveAlias : false,
      });
    }

    commitBtn.disabled = true;
    commitBtn.textContent = t("ocr.savingBtn");
    try {
      const result = await commitScreenshot(duelId, extraction.screenshotId, {
        score_date: scoreDate,
        rows: rowsPayload,
      });
      if (typeof onCommitted === "function") {
        await onCommitted(result);
      }
    } catch (err) {
      errorBox.textContent = err.message || t("ocr.errCommitFailed");
      errorBox.classList.remove("hidden");
    } finally {
      commitBtn.disabled = false;
      commitBtn.textContent = t("ocr.commitBtn");
    }
  });
}
