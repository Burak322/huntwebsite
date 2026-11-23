import {
  CLAN_RANKS,
  TOWER_LEVELS,
  createPlayer,
  escapeHtml,
  listFields,
  listPlayers,
  renderSelectOptions,
  todayIso,
} from "../api.js";
import { t } from "../i18n/index.js";
import {
  collectDynamicFieldValues,
  formatFieldValue,
  renderDynamicFieldInputs,
} from "../components/dynamicFields.js";
import { mountPlayerPhotoImport } from "../components/playerPhotoImport.js";

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

const SORT_STORAGE_KEY = "clan_players_sort";
const VALID_PLAYER_SORTS = new Set([
  "rank_desc",
  "rank_asc",
  "tower_desc",
  "tower_asc",
  "name_asc",
  "name_desc",
]);

export function renderPlayersPage(container, { onNavigate }) {
  let profileFields = [];
  let progFields = [];
  let searchFilter = "";
  let statusFilter = "";
  let rankFilter = "";
  let towerFilter = "";
  let savedSort = "";
  try {
    savedSort = window.localStorage.getItem(SORT_STORAGE_KEY) || "";
  } catch {
    savedSort = "";
  }
  let sortOrder = VALID_PLAYER_SORTS.has(savedSort) ? savedSort : "rank_desc";
  let showAddForm = false;
  let showPhotoImport = false;
  let searchTimer = null;

  container.innerHTML = `
    <div class="page-header">
      <div>
        <h1>${escapeHtml(t("players.title"))}</h1>
        <p class="muted-text" style="margin: 0.25rem 0 0;">
          ${escapeHtml(t("players.subtitle"))}
        </p>
      </div>
      <div class="header-actions">
        <button type="button" class="btn btn-secondary" data-testid="toggle-photo-import-btn">
          ${escapeHtml(t("players.photoImportBtn"))}
        </button>
        <button type="button" class="btn btn-primary" data-testid="toggle-add-player-btn">
          ${escapeHtml(t("players.newPlayerBtn"))}
        </button>
      </div>
    </div>

    <div class="alert alert-success hidden" role="status" data-testid="players-success"></div>
    <div class="alert alert-error hidden" role="alert" data-testid="players-error"></div>

    <section class="card section-card hidden" data-testid="player-photo-import-section"></section>

    <section class="card section-card hidden" data-testid="add-player-section">
      <h2 style="margin-top: 0;">${escapeHtml(t("players.addCardTitle"))}</h2>
      <form data-testid="add-player-form" class="form-stack">
        <div class="form-grid">
          <div class="form-field">
            <label for="add-player-name">${escapeHtml(t("players.nameLabelRequired"))}</label>
            <input
              id="add-player-name"
              name="display_name"
              type="text"
              required
              placeholder="${escapeHtml(t("players.namePlaceholder"))}"
            >
          </div>
          <div class="form-field">
            <label for="add-player-status">${escapeHtml(t("players.statusLabel"))}</label>
            <select id="add-player-status" name="status">
              <option value="active">${escapeHtml(t("common.status.active"))}</option>
              <option value="inactive">${escapeHtml(t("common.status.inactive"))}</option>
              <option value="left">${escapeHtml(t("common.status.left"))}</option>
            </select>
          </div>
          <div class="form-field">
            <label for="add-player-rank">${escapeHtml(t("players.rankLabel"))}</label>
            <select id="add-player-rank" name="clan_rank">
              ${renderSelectOptions(CLAN_RANKS, "", t("common.notSelected"))}
            </select>
          </div>
          <div class="form-field">
            <label for="add-player-tower">${escapeHtml(t("players.towerLabel"))}</label>
            <select id="add-player-tower" name="tower_level">
              ${renderSelectOptions(TOWER_LEVELS, "", t("common.notSelected"))}
            </select>
          </div>
          <div class="form-field">
            <label for="add-player-joined">${escapeHtml(t("players.joinedAtLabel"))}</label>
            <input id="add-player-joined" name="joined_at" type="date" value="${todayIso()}">
          </div>
          <div class="form-field">
            <label for="add-player-aliases">${escapeHtml(t("players.aliasesLabel"))}</label>
            <input
              id="add-player-aliases"
              name="aliases"
              type="text"
              placeholder="${escapeHtml(t("players.aliasesPlaceholder"))}"
            >
          </div>
        </div>
        <div data-testid="add-player-dynamic-fields"></div>
        <div class="form-field">
          <label for="add-player-notes">${escapeHtml(t("players.notesLabel"))}</label>
          <textarea id="add-player-notes" name="notes" rows="2" placeholder="${escapeHtml(t("players.notesPlaceholder"))}"></textarea>
        </div>
        <div class="form-actions">
          <button type="submit" class="btn btn-primary" data-testid="create-player-submit">
            ${escapeHtml(t("players.addSubmitBtn"))}
          </button>
          <button type="button" class="btn btn-secondary" data-testid="cancel-add-player-btn">
            ${escapeHtml(t("common.cancel"))}
          </button>
        </div>
      </form>
    </section>

    <section class="card section-card">
      <div class="toolbar">
        <div class="form-field" style="flex: 1; min-width: 220px;">
          <label for="players-search-input">${escapeHtml(t("players.searchLabel"))}</label>
          <input
            id="players-search-input"
            name="search"
            type="search"
            placeholder="${escapeHtml(t("players.searchPlaceholder"))}"
          >
        </div>
        <div class="form-field" style="min-width: 150px;">
          <label for="players-status-filter">${escapeHtml(t("players.statusFilterLabel"))}</label>
          <select id="players-status-filter" name="status">
            <option value="">${escapeHtml(t("players.allStatuses"))}</option>
            <option value="active">${escapeHtml(t("common.status.active"))}</option>
            <option value="inactive">${escapeHtml(t("common.status.inactive"))}</option>
            <option value="left">${escapeHtml(t("common.status.left"))}</option>
          </select>
        </div>
        <div class="form-field" style="min-width: 140px;">
          <label for="players-rank-filter">${escapeHtml(t("players.rankFilterLabel"))}</label>
          <select id="players-rank-filter" name="clan_rank" data-testid="players-rank-filter">
            ${renderSelectOptions([...CLAN_RANKS].reverse(), "", t("players.allRanks"))}
          </select>
        </div>
        <div class="form-field" style="min-width: 150px;">
          <label for="players-tower-filter">${escapeHtml(t("players.towerFilterLabel"))}</label>
          <select id="players-tower-filter" name="tower_level" data-testid="players-tower-filter">
            ${renderSelectOptions(TOWER_LEVELS, "", t("players.allTowers"))}
          </select>
        </div>
        <div class="form-field" style="min-width: 195px;">
          <label for="players-sort-select">${escapeHtml(t("players.sortLabel"))}</label>
          <select id="players-sort-select" name="sort" data-testid="players-sort-select">
            <option value="rank_desc" ${sortOrder === "rank_desc" ? "selected" : ""}>${escapeHtml(t("players.sort.rank_desc"))}</option>
            <option value="rank_asc" ${sortOrder === "rank_asc" ? "selected" : ""}>${escapeHtml(t("players.sort.rank_asc"))}</option>
            <option value="tower_desc" ${sortOrder === "tower_desc" ? "selected" : ""}>${escapeHtml(t("players.sort.tower_desc"))}</option>
            <option value="tower_asc" ${sortOrder === "tower_asc" ? "selected" : ""}>${escapeHtml(t("players.sort.tower_asc"))}</option>
            <option value="name_asc" ${sortOrder === "name_asc" ? "selected" : ""}>${escapeHtml(t("players.sort.name_asc"))}</option>
            <option value="name_desc" ${sortOrder === "name_desc" ? "selected" : ""}>${escapeHtml(t("players.sort.name_desc"))}</option>
          </select>
        </div>
      </div>

      <div class="table-wrap" style="margin-top: 1rem;" data-testid="players-table-container">
        <div class="empty-state">${escapeHtml(t("players.loading"))}</div>
      </div>
    </section>
  `;

  const togglePhotoBtn = container.querySelector('[data-testid="toggle-photo-import-btn"]');
  const photoSection = container.querySelector('[data-testid="player-photo-import-section"]');
  const toggleBtn = container.querySelector('[data-testid="toggle-add-player-btn"]');
  const cancelAddBtn = container.querySelector('[data-testid="cancel-add-player-btn"]');
  const addSection = container.querySelector('[data-testid="add-player-section"]');
  const addForm = container.querySelector('[data-testid="add-player-form"]');
  const dynamicContainer = container.querySelector('[data-testid="add-player-dynamic-fields"]');
  const searchInput = container.querySelector("#players-search-input");
  const statusSelect = container.querySelector("#players-status-filter");
  const rankSelect = container.querySelector("#players-rank-filter");
  const towerSelect = container.querySelector("#players-tower-filter");
  const sortSelect = container.querySelector("#players-sort-select");
  const tableContainer = container.querySelector('[data-testid="players-table-container"]');
  const successBox = container.querySelector('[data-testid="players-success"]');
  const errorBox = container.querySelector('[data-testid="players-error"]');

  function setMessage(box, msg) {
    successBox.classList.add("hidden");
    errorBox.classList.add("hidden");
    if (msg) {
      box.textContent = msg;
      box.classList.remove("hidden");
    }
  }

  function renderAddDynamicFields() {
    dynamicContainer.innerHTML = renderDynamicFieldInputs(profileFields, {}, { idPrefix: "add-pf" });
  }

  function saveSortPreference(val) {
    sortOrder = val;
    sortSelect.value = val;
    try {
      window.localStorage.setItem(SORT_STORAGE_KEY, val);
    } catch {
      // Ignore storage errors in restricted contexts
    }
  }

  function renderSortTh(colKey, label, defaultDir) {
    const isAsc = sortOrder === `${colKey}_asc`;
    const isDesc = sortOrder === `${colKey}_desc`;
    const arrow = isAsc ? " ▲" : isDesc ? " ▼" : "";
    const activeCls = isAsc || isDesc ? " active" : "";
    return `
      <th>
        <button
          type="button"
          class="th-sort-btn${activeCls}"
          data-sort-col="${colKey}"
          data-default-dir="${defaultDir}"
        >${escapeHtml(label)}${arrow}</button>
      </th>
    `;
  }

  function renderPlayersTable(players) {
    const visibleProfileCols = profileFields.slice(0, 3);
    const visibleProgCols = progFields.slice(0, 3);

    if (!players || players.length === 0) {
      tableContainer.innerHTML = `
        <div class="empty-state">
          ${escapeHtml(t("players.emptyList"))}
        </div>
      `;
      return;
    }

    const headCols = [
      renderSortTh("name", t("players.colName"), "asc"),
      `<th>${escapeHtml(t("players.colStatus"))}</th>`,
      renderSortTh("rank", t("players.colRank"), "desc"),
      renderSortTh("tower", t("players.colTower"), "desc"),
      `<th>${escapeHtml(t("players.colAliases"))}</th>`,
      ...visibleProfileCols.map((f) => `<th>${escapeHtml(f.label)}</th>`),
      ...visibleProgCols.map(
        (f) => `<th>${escapeHtml(f.label)}${f.unit ? ` (${escapeHtml(f.unit)})` : ""}</th>`
      ),
      "<th></th>",
    ].join("");

    const bodyRows = players
      .map((p) => {
        const st = getPlayerStatusMeta(p.status);
        const rankHtml = p.clan_rank
          ? `<span class="badge ${
              p.clan_rank === "R5" || p.clan_rank === "R4" ? "badge-gold" : "badge-info"
            }">${escapeHtml(p.clan_rank)}</span>`
          : '<span class="muted-text">—</span>';
        const towerHtml = p.tower_level
          ? `<span class="badge badge-tower">${escapeHtml(p.tower_level)}</span>`
          : '<span class="muted-text">—</span>';
        const aliasesHtml =
          p.aliases && p.aliases.length > 0
            ? p.aliases.map((a) => `<span class="chip">${escapeHtml(a.alias_name)}</span>`).join(" ")
            : '<span class="muted-text">—</span>';

        const profCells = visibleProfileCols
          .map((f) => `<td>${formatFieldValue(f, p.profile_values?.[f.field_key])}</td>`)
          .join("");
        const progCells = visibleProgCols
          .map((f) => `<td>${formatFieldValue(f, p.latestProgression?.metrics?.[f.field_key])}</td>`)
          .join("");

        return `
          <tr data-player-id="${p.id}">
            <td>
              <a href="/players/${p.id}" data-link class="text-link">
                <strong>${escapeHtml(p.display_name)}</strong>
              </a>
            </td>
            <td><span class="badge ${st.cls}">${escapeHtml(st.label)}</span></td>
            <td>${rankHtml}</td>
            <td>${towerHtml}</td>
            <td><div class="chip-list">${aliasesHtml}</div></td>
            ${profCells}
            ${progCells}
            <td>
              <a href="/players/${p.id}" data-link class="btn btn-secondary btn-sm">${escapeHtml(t("common.detail"))}</a>
            </td>
          </tr>
        `;
      })
      .join("");

    tableContainer.innerHTML = `
      <table data-testid="players-table">
        <thead><tr>${headCols}</tr></thead>
        <tbody>${bodyRows}</tbody>
      </table>
    `;

    tableContainer.querySelectorAll("[data-link]").forEach((anchor) => {
      anchor.addEventListener("click", (event) => {
        event.preventDefault();
        onNavigate(anchor.getAttribute("href") || "/players");
      });
    });

    tableContainer.querySelectorAll("[data-sort-col]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const col = btn.getAttribute("data-sort-col");
        const defDir = btn.getAttribute("data-default-dir") || "asc";
        let nextSort = `${col}_${defDir}`;
        if (sortOrder === `${col}_desc`) {
          nextSort = `${col}_asc`;
        } else if (sortOrder === `${col}_asc`) {
          nextSort = `${col}_desc`;
        }
        saveSortPreference(nextSort);
        refreshPlayersOnly();
      });
    });
  }

  async function refreshPlayersOnly() {
    container.setAttribute("aria-busy", "true");
    try {
      const res = await listPlayers({
        search: searchFilter,
        status: statusFilter,
        clan_rank: rankFilter,
        tower_level: towerFilter,
        sort: sortOrder,
      });
      renderPlayersTable(res.players || []);
    } catch (err) {
      setMessage(errorBox, err.message || t("players.errListLoadFailed"));
    } finally {
      container.removeAttribute("aria-busy");
    }
  }

  async function initLoad() {
    container.setAttribute("aria-busy", "true");
    try {
      const [fieldsRes, playersRes] = await Promise.all([
        listFields({ activeOnly: true }),
        listPlayers({
          search: searchFilter,
          status: statusFilter,
          clan_rank: rankFilter,
          tower_level: towerFilter,
          sort: sortOrder,
        }),
      ]);
      const allFields = fieldsRes.fields || [];
      profileFields = allFields.filter((f) => f.scope === "profile");
      progFields = allFields.filter((f) => f.scope === "progression");
      renderAddDynamicFields();
      renderPlayersTable(playersRes.players || []);
    } catch (err) {
      setMessage(errorBox, err.message || t("players.errPageLoadFailed"));
    } finally {
      container.removeAttribute("aria-busy");
    }
  }

  function closePhotoImport() {
    showPhotoImport = false;
    photoSection.classList.add("hidden");
    photoSection.innerHTML = "";
  }

  togglePhotoBtn.addEventListener("click", () => {
    if (showPhotoImport) {
      closePhotoImport();
      return;
    }
    showAddForm = false;
    addSection.classList.add("hidden");
    showPhotoImport = true;
    photoSection.classList.remove("hidden");
    mountPlayerPhotoImport(photoSection, {
      profileFields,
      progFields,
      onImported: async (res) => {
        closePhotoImport();
        const createdCnt = Number(res.createdCount || 0);
        const skippedCnt = Number(res.skippedCount || 0);
        const skipText =
          skippedCnt > 0 ? t("players.msgImportedSkipped", { skipped: skippedCnt }) : "";
        setMessage(successBox, `${t("players.msgImported", { created: createdCnt })}${skipText}`);
        await refreshPlayersOnly();
      },
      onCancel: closePhotoImport,
    });
  });

  toggleBtn.addEventListener("click", () => {
    showAddForm = !showAddForm;
    if (showAddForm) {
      closePhotoImport();
    }
    addSection.classList.toggle("hidden", !showAddForm);
  });

  cancelAddBtn.addEventListener("click", () => {
    showAddForm = false;
    addSection.classList.add("hidden");
  });

  searchInput.addEventListener("input", () => {
    searchFilter = searchInput.value.trim();
    clearTimeout(searchTimer);
    searchTimer = setTimeout(refreshPlayersOnly, 200);
  });

  statusSelect.addEventListener("change", () => {
    statusFilter = statusSelect.value;
    refreshPlayersOnly();
  });

  rankSelect.addEventListener("change", () => {
    rankFilter = rankSelect.value;
    refreshPlayersOnly();
  });

  towerSelect.addEventListener("change", () => {
    towerFilter = towerSelect.value;
    refreshPlayersOnly();
  });

  sortSelect.addEventListener("change", () => {
    if (VALID_PLAYER_SORTS.has(sortSelect.value)) {
      saveSortPreference(sortSelect.value);
      refreshPlayersOnly();
    }
  });

  addForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    setMessage(errorBox, "");

    const submitBtn = addForm.querySelector('[data-testid="create-player-submit"]');
    const displayName = addForm.querySelector('[name="display_name"]').value.trim();
    const status = addForm.querySelector('[name="status"]').value;
    const clanRank = addForm.querySelector('[name="clan_rank"]').value || null;
    const towerLevel = addForm.querySelector('[name="tower_level"]').value || null;
    const joinedAt = addForm.querySelector('[name="joined_at"]').value.trim();
    const notes = addForm.querySelector('[name="notes"]').value.trim();
    const aliasesRaw = addForm.querySelector('[name="aliases"]').value;
    const aliases = aliasesRaw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const profileValues = collectDynamicFieldValues(dynamicContainer, profileFields);

    submitBtn.disabled = true;
    try {
      const res = await createPlayer({
        display_name: displayName,
        status,
        clan_rank: clanRank,
        tower_level: towerLevel,
        joined_at: joinedAt || null,
        notes: notes || null,
        profile_values: profileValues,
        aliases,
      });
      addForm.reset();
      addForm.querySelector('[name="joined_at"]').value = todayIso();
      renderAddDynamicFields();
      showAddForm = false;
      addSection.classList.add("hidden");
      setMessage(successBox, t("players.msgPlayerAdded", { name: res.player.display_name }));
      await refreshPlayersOnly();
    } catch (err) {
      setMessage(errorBox, err.message || t("players.errPlayerAddFailed"));
    } finally {
      submitBtn.disabled = false;
    }
  });

  initLoad();
}
