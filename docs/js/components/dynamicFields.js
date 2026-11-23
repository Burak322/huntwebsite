import { escapeHtml, fmtDate, fmtNum } from "../api.js";
import { t } from "../i18n/index.js";

function sortFields(fields) {
  return [...(fields || [])].sort((a, b) => {
    const orderDiff = Number(a.sort_order ?? 0) - Number(b.sort_order ?? 0);
    if (orderDiff !== 0) return orderDiff;
    return Number(a.id ?? 0) - Number(b.id ?? 0);
  });
}

export function renderDynamicFieldInputs(
  fields,
  values = {},
  { idPrefix = "df", includeInactive = false } = {}
) {
  const filtered = sortFields(fields).filter((f) => includeInactive || f.is_active !== false);
  if (filtered.length === 0) {
    return "";
  }

  const parts = filtered.map((field) => {
    const key = String(field.field_key);
    const id = `${idPrefix}-${key}`;
    const safeId = escapeHtml(id);
    const safeKey = escapeHtml(key);
    const unitSuffix = field.unit ? ` (${escapeHtml(field.unit)})` : "";
    const reqMark = field.is_required ? " *" : "";
    const labelText = `${escapeHtml(field.label)}${unitSuffix}${reqMark}`;
    const current = values && Object.prototype.hasOwnProperty.call(values, key) ? values[key] : undefined;

    if (field.field_type === "boolean") {
      const checked = current === true || current === "true" || current === 1 ? "checked" : "";
      return `
        <div class="form-field form-field-checkbox">
          <label class="checkbox-label" for="${safeId}">
            <input
              id="${safeId}"
              type="checkbox"
              data-field-key="${safeKey}"
              data-field-type="boolean"
              ${checked}
            >
            <span>${labelText}</span>
          </label>
        </div>
      `;
    }

    if (field.field_type === "select") {
      const options = Array.isArray(field.options) ? field.options : [];
      const curStr = current !== undefined && current !== null ? String(current) : "";
      const optionsHtml = options
        .map((opt) => {
          const s = String(opt);
          const selected = curStr === s ? "selected" : "";
          return `<option value="${escapeHtml(s)}" ${selected}>${escapeHtml(s)}</option>`;
        })
        .join("");

      return `
        <div class="form-field">
          <label for="${safeId}">${labelText}</label>
          <select
            id="${safeId}"
            data-field-key="${safeKey}"
            data-field-type="select"
            ${field.is_required ? "required" : ""}
          >
            <option value="">${escapeHtml(t("dynamicFields.selectPlaceholder"))}</option>
            ${optionsHtml}
          </select>
        </div>
      `;
    }

    if (field.field_type === "number") {
      const valStr =
        current !== undefined && current !== null && current !== "" ? String(current) : "";
      return `
        <div class="form-field">
          <label for="${safeId}">${labelText}</label>
          <input
            id="${safeId}"
            type="number"
            step="any"
            value="${escapeHtml(valStr)}"
            data-field-key="${safeKey}"
            data-field-type="number"
            ${field.is_required ? "required" : ""}
          >
        </div>
      `;
    }

    if (field.field_type === "date") {
      const dateStr = current ? String(current).slice(0, 10) : "";
      return `
        <div class="form-field">
          <label for="${safeId}">${labelText}</label>
          <input
            id="${safeId}"
            type="date"
            value="${escapeHtml(dateStr)}"
            data-field-key="${safeKey}"
            data-field-type="date"
            ${field.is_required ? "required" : ""}
          >
        </div>
      `;
    }

    const textStr = current !== undefined && current !== null ? String(current) : "";
    return `
      <div class="form-field">
        <label for="${safeId}">${labelText}</label>
        <input
          id="${safeId}"
          type="text"
          value="${escapeHtml(textStr)}"
          data-field-key="${safeKey}"
          data-field-type="text"
          ${field.is_required ? "required" : ""}
        >
      </div>
    `;
  });

  return `<div class="form-grid">${parts.join("")}</div>`;
}

export function collectDynamicFieldValues(
  container,
  fields,
  { includeEmptyAsNull = false } = {}
) {
  const byKey = new Map((fields || []).map((f) => [String(f.field_key), f]));
  const result = {};
  container.querySelectorAll("[data-field-key]").forEach((el) => {
    const key = el.getAttribute("data-field-key");
    if (!key) return;
    const ftype = el.getAttribute("data-field-type") || byKey.get(key)?.field_type || "text";

    if (ftype === "boolean") {
      result[key] = Boolean(el.checked);
      return;
    }

    const raw = String(el.value ?? "").trim();
    if (raw === "") {
      if (includeEmptyAsNull) {
        result[key] = null;
      }
      return;
    }

    if (ftype === "number") {
      const num = Number(raw);
      if (Number.isFinite(num)) {
        result[key] = num;
      }
      return;
    }

    result[key] = raw;
  });
  return result;
}

export function formatFieldValue(field, value) {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  const ftype = field?.field_type;
  if (ftype === "boolean") {
    return escapeHtml(value === true || value === "true" || value === 1 ? t("common.yes") : t("common.no"));
  }
  if (ftype === "number") {
    const unit = field?.unit ? ` ${escapeHtml(field.unit)}` : "";
    return `${fmtNum(value)}${unit}`;
  }
  if (ftype === "date") {
    return escapeHtml(fmtDate(value));
  }
  return escapeHtml(String(value));
}
