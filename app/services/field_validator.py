from __future__ import annotations

import json
import math
import re
import sqlite3
import unicodedata
from datetime import datetime
from typing import Any

from app.repositories import fields_repo
from app.services.auth_service import utc_now_iso

VALID_SCOPES = frozenset({"profile", "progression"})
VALID_FIELD_TYPES = frozenset({"text", "number", "boolean", "select", "date"})

_FIELD_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
_NUMBER_STR_PATTERN = re.compile(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$")
_DATE_STR_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_TR_MAP = str.maketrans(
    {
        "Ç": "c",
        "ç": "c",
        "Ğ": "g",
        "ğ": "g",
        "İ": "i",
        "I": "i",
        "ı": "i",
        "Ö": "o",
        "ö": "o",
        "Ş": "s",
        "ş": "s",
        "Ü": "u",
        "ü": "u",
    }
)


class FieldError(Exception):
    """Base error for tracking fields domain."""


class FieldValidationError(FieldError):
    """Raised on invalid tracking field definition or dynamic value."""


class FieldNotFoundError(FieldError):
    """Raised when a tracking field is not found."""


class FieldConflictError(FieldError):
    """Raised when a tracking field key collides with an existing field."""


def _has_control_chars(value: str) -> bool:
    return any(ord(ch) < 32 for ch in value)


def slugify_field_key(label: str) -> str:
    if not isinstance(label, str):
        raise FieldValidationError("Alan etiketi metin olmalıdır.")
    mapped = label.translate(_TR_MAP)
    ascii_str = (
        unicodedata.normalize("NFKD", mapped)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_str).strip("_")
    slug = slug[:64].rstrip("_")
    if not slug:
        raise FieldValidationError(
            "Alan etiketinden geçerli bir alan anahtarı üretilemedi; lütfen harf veya rakam kullanın."
        )
    return slug


def validate_field_key(field_key: str) -> str:
    if not isinstance(field_key, str):
        raise FieldValidationError("Alan anahtarı metin olmalıdır.")
    cleaned = field_key.strip()
    if not _FIELD_KEY_PATTERN.fullmatch(cleaned):
        raise FieldValidationError(
            "Alan anahtarı yalnızca küçük harf, rakam ve alt çizgi (_) içerebilir ve 1-64 karakter olmalıdır."
        )
    return cleaned


def _validate_label(label: Any) -> str:
    if not isinstance(label, str):
        raise FieldValidationError("Alan etiketi metin olmalıdır.")
    cleaned = label.strip()
    if not (1 <= len(cleaned) <= 80):
        raise FieldValidationError("Alan etiketi 1 ile 80 karakter arasında olmalıdır.")
    if _has_control_chars(cleaned):
        raise FieldValidationError("Alan etiketi kontrol karakterleri içeremez.")
    return cleaned


def _validate_unit(unit: Any) -> str | None:
    if unit is None:
        return None
    if not isinstance(unit, str):
        raise FieldValidationError("Birim metin olmalıdır.")
    cleaned = unit.strip()
    if not cleaned:
        return None
    if len(cleaned) > 32:
        raise FieldValidationError("Birim en fazla 32 karakter olabilir.")
    if _has_control_chars(cleaned):
        raise FieldValidationError("Birim kontrol karakterleri içeremez.")
    return cleaned


def _validate_options(field_type: str, options: Any) -> list[str] | None:
    if field_type == "select":
        if not isinstance(options, list) or len(options) == 0:
            raise FieldValidationError("Seçim (select) alanı için en az bir seçenek belirtilmelidir.")
        cleaned_options: list[str] = []
        seen: set[str] = set()
        for item in options:
            if not isinstance(item, str):
                raise FieldValidationError("Tüm seçenekler metin olmalıdır.")
            cleaned = item.strip()
            if not cleaned:
                raise FieldValidationError("Seçenek değerleri boş olamaz.")
            if len(cleaned) > 100:
                raise FieldValidationError("Her seçenek en fazla 100 karakter olabilir.")
            if _has_control_chars(cleaned):
                raise FieldValidationError("Seçenekler kontrol karakterleri içeremez.")
            if cleaned not in seen:
                seen.add(cleaned)
                cleaned_options.append(cleaned)
        return cleaned_options

    if options is not None:
        if not isinstance(options, list):
            raise FieldValidationError("Seçenekler yalnızca 'select' tipindeki alanlarda kullanılabilir.")
        if len(options) > 0:
            raise FieldValidationError("Seçenekler yalnızca 'select' tipindeki alanlarda kullanılabilir.")
    return None


def _validate_bool_flag(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise FieldValidationError(f"{field_name} değeri boolean (true/false) olmalıdır.")
    return value


def _validate_sort_order(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FieldValidationError("Sıra numarası (sort_order) tam sayı olmalıdır.")
    if value < -10000 or value > 100000:
        raise FieldValidationError("Sıra numarası geçerli aralıkta olmalıdır.")
    return value


def validate_field_definition(
    *,
    label: Any,
    field_key: Any = None,
    scope: Any,
    field_type: Any,
    unit: Any = None,
    options: Any = None,
    is_required: Any = False,
    is_active: Any = True,
    sort_order: Any = 0,
) -> dict[str, Any]:
    clean_label = _validate_label(label)
    if not isinstance(scope, str) or scope not in VALID_SCOPES:
        raise FieldValidationError("Alan kapsamı 'profile' veya 'progression' olmalıdır.")
    if not isinstance(field_type, str) or field_type not in VALID_FIELD_TYPES:
        raise FieldValidationError(
            "Alan tipi 'text', 'number', 'boolean', 'select' veya 'date' olmalıdır."
        )

    explicit_key: str | None = None
    if field_key is not None:
        if not isinstance(field_key, str):
            raise FieldValidationError("Alan anahtarı metin olmalıdır.")
        if field_key.strip() != "":
            explicit_key = validate_field_key(field_key)

    resolved_key = explicit_key if explicit_key is not None else slugify_field_key(clean_label)
    clean_unit = _validate_unit(unit)
    clean_options = _validate_options(field_type, options)
    clean_required = _validate_bool_flag(is_required, "is_required")
    clean_active = _validate_bool_flag(is_active, "is_active")
    clean_sort_order = _validate_sort_order(sort_order)

    return {
        "field_key": resolved_key,
        "explicit_key": explicit_key is not None,
        "label": clean_label,
        "scope": scope,
        "field_type": field_type,
        "unit": clean_unit,
        "options": clean_options,
        "is_required": clean_required,
        "is_active": clean_active,
        "sort_order": clean_sort_order,
    }


def list_tracking_fields(
    conn: sqlite3.Connection,
    *,
    scope: str | None = None,
    active_only: bool = False,
) -> list[dict[str, Any]]:
    if scope is not None and scope not in VALID_SCOPES:
        raise FieldValidationError("Alan kapsamı 'profile' veya 'progression' olmalıdır.")
    rows = fields_repo.list_fields(conn, scope=scope, active_only=active_only)
    return [fields_repo.row_to_field_dict(row) for row in rows]


def create_tracking_field(
    conn: sqlite3.Connection,
    *,
    label: Any,
    field_key: Any = None,
    scope: Any,
    field_type: Any,
    unit: Any = None,
    options: Any = None,
    is_required: Any = False,
    is_active: Any = True,
    sort_order: Any = 0,
) -> dict[str, Any]:
    validated = validate_field_definition(
        label=label,
        field_key=field_key,
        scope=scope,
        field_type=field_type,
        unit=unit,
        options=options,
        is_required=is_required,
        is_active=is_active,
        sort_order=sort_order,
    )
    now_iso = utc_now_iso()
    options_json = (
        json.dumps(validated["options"], ensure_ascii=False)
        if validated["options"] is not None
        else None
    )

    try:
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")

        if validated["explicit_key"]:
            final_key = validated["field_key"]
            if fields_repo.get_field_by_key(conn, final_key) is not None:
                conn.rollback()
                raise FieldConflictError("Bu alan anahtarı zaten kullanılıyor.")
        else:
            existing_keys = fields_repo.list_all_field_keys(conn)
            base_key = validated["field_key"]
            if base_key not in existing_keys:
                final_key = base_key
            else:
                suffix_num = 2
                while True:
                    suffix = f"_{suffix_num}"
                    prefix = base_key[: 64 - len(suffix)].rstrip("_")
                    candidate = f"{prefix}{suffix}" if prefix else f"alan{suffix}"
                    if candidate not in existing_keys:
                        final_key = candidate
                        break
                    suffix_num += 1

        row = fields_repo.create_field(
            conn,
            field_key=final_key,
            label=validated["label"],
            scope=validated["scope"],
            field_type=validated["field_type"],
            unit=validated["unit"],
            options_json=options_json,
            is_required=1 if validated["is_required"] else 0,
            is_active=1 if validated["is_active"] else 0,
            sort_order=validated["sort_order"],
            created_at=now_iso,
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise FieldConflictError("Bu alan anahtarı zaten kullanılıyor.") from exc

    return fields_repo.row_to_field_dict(row)


def update_tracking_field(
    conn: sqlite3.Connection,
    field_id: int,
    fields_set: set[str],
    **updates: Any,
) -> dict[str, Any]:
    existing_row = fields_repo.get_field_by_id(conn, field_id)
    if existing_row is None:
        raise FieldNotFoundError("Takip alanı bulunamadı.")

    existing = fields_repo.row_to_field_dict(existing_row)

    for immutable_col in ("field_key", "scope", "field_type"):
        if immutable_col in fields_set:
            incoming_val = updates.get(immutable_col)
            if incoming_val is None or incoming_val != existing[immutable_col]:
                raise FieldValidationError(
                    "field_key, scope ve field_type oluşturulduktan sonra değiştirilemez."
                )

    db_updates: dict[str, Any] = {}
    if "label" in fields_set:
        db_updates["label"] = _validate_label(updates.get("label"))
    if "unit" in fields_set:
        db_updates["unit"] = _validate_unit(updates.get("unit"))
    if "options" in fields_set:
        clean_opts = _validate_options(existing["field_type"], updates.get("options"))
        db_updates["options_json"] = (
            json.dumps(clean_opts, ensure_ascii=False) if clean_opts is not None else None
        )
    if "is_required" in fields_set:
        db_updates["is_required"] = 1 if _validate_bool_flag(updates.get("is_required"), "is_required") else 0
    if "is_active" in fields_set:
        db_updates["is_active"] = 1 if _validate_bool_flag(updates.get("is_active"), "is_active") else 0
    if "sort_order" in fields_set:
        db_updates["sort_order"] = _validate_sort_order(updates.get("sort_order"))

    updated_row = fields_repo.update_field(conn, field_id, db_updates)
    conn.commit()
    assert updated_row is not None
    return fields_repo.row_to_field_dict(updated_row)


def delete_tracking_field(conn: sqlite3.Connection, field_id: int) -> dict[str, bool]:
    existing_row = fields_repo.get_field_by_id(conn, field_id)
    if existing_row is None:
        raise FieldNotFoundError("Takip alanı bulunamadı.")

    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")

    try:
        if fields_repo.is_field_referenced(conn, str(existing_row["field_key"])):
            fields_repo.archive_field(conn, field_id)
            conn.commit()
            return {"deleted": True, "archived": True}

        fields_repo.delete_field(conn, field_id)
        conn.commit()
        return {"deleted": True, "archived": False}
    except BaseException:
        conn.rollback()
        raise


def _is_empty_value(val: Any) -> bool:
    if val is None:
        return True
    if isinstance(val, str) and val.strip() == "":
        return True
    return False


def _field_options(field: dict[str, Any]) -> list[str]:
    if "options" in field and field["options"] is not None:
        return [str(x) for x in field["options"]]
    raw_json = field.get("options_json")
    if isinstance(raw_json, str) and raw_json:
        parsed = json.loads(raw_json)
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
    return []


def _coerce_and_validate_single_value(field: dict[str, Any], val: Any) -> Any:
    field_type = str(field["field_type"])
    label = str(field["label"])

    if field_type == "text":
        if not isinstance(val, str):
            raise FieldValidationError(f"'{label}' alanı metin olmalıdır.")
        cleaned = val.strip()
        if _has_control_chars(cleaned):
            raise FieldValidationError(f"'{label}' alanı kontrol karakterleri içeremez.")
        if len(cleaned) > 500:
            raise FieldValidationError(f"'{label}' alanı en fazla 500 karakter olabilir.")
        return cleaned

    if field_type == "number":
        # Check bool FIRST because bool is a subclass of int in Python.
        if isinstance(val, bool):
            raise FieldValidationError(f"'{label}' alanı sayısal bir değer olmalıdır.")
        if isinstance(val, int):
            return val
        if isinstance(val, float):
            if not math.isfinite(val):
                raise FieldValidationError(f"'{label}' alanı geçerli bir sonlu sayı olmalıdır.")
            return val
        if isinstance(val, str):
            stripped = val.strip()
            if not _NUMBER_STR_PATTERN.fullmatch(stripped):
                raise FieldValidationError(f"'{label}' alanı geçerli bir sayı olmalıdır.")
            num: int | float = float(stripped) if "." in stripped else int(stripped)
            if isinstance(num, float) and not math.isfinite(num):
                raise FieldValidationError(f"'{label}' alanı geçerli bir sonlu sayı olmalıdır.")
            return num
        raise FieldValidationError(f"'{label}' alanı sayısal bir değer olmalıdır.")

    if field_type == "boolean":
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            lowered = val.strip().lower()
            if lowered == "true":
                return True
            if lowered == "false":
                return False
        raise FieldValidationError(f"'{label}' alanı mantıksal (true/false) değer olmalıdır.")

    if field_type == "select":
        if not isinstance(val, str):
            raise FieldValidationError(f"'{label}' alanı geçerli bir seçenek metni olmalıdır.")
        cleaned = val.strip()
        allowed_options = _field_options(field)
        if cleaned not in allowed_options:
            raise FieldValidationError(f"'{label}' alanı için geçersiz seçenek: {cleaned}")
        return cleaned

    if field_type == "date":
        if not isinstance(val, str):
            raise FieldValidationError(f"'{label}' alanı YYYY-AA-GG biçiminde tarih olmalıdır.")
        cleaned = val.strip()
        if not _DATE_STR_PATTERN.fullmatch(cleaned):
            raise FieldValidationError(f"'{label}' alanı YYYY-AA-GG biçiminde tarih olmalıdır.")
        try:
            datetime.strptime(cleaned, "%Y-%m-%d")
        except ValueError as exc:
            raise FieldValidationError(f"'{label}' alanı geçerli bir takvim tarihi olmalıdır.") from exc
        return cleaned

    raise FieldValidationError(f"Desteklenmeyen alan tipi: {field_type}")


def validate_field_values(
    fields: list[dict[str, Any]],
    raw_values: Any,
    *,
    partial: bool = False,
    existing_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(raw_values, dict):
        raise FieldValidationError("Alan değerleri bir nesne (dict) olmalıdır.")

    all_by_key: dict[str, dict[str, Any]] = {str(f["field_key"]): f for f in fields}
    active_by_key: dict[str, dict[str, Any]] = {
        str(f["field_key"]): f for f in fields if bool(f.get("is_active", True))
    }

    for key in raw_values.keys():
        if not isinstance(key, str) or key not in all_by_key:
            raise FieldValidationError(f"Tanımsız alan anahtarı: {key}")
        if key not in active_by_key:
            raise FieldValidationError(f"Arşivlenmiş (pasif) alan anahtarı güncellenemez: {key}")

    if partial:
        result: dict[str, Any] = dict(existing_values) if isinstance(existing_values, dict) else {}
        for key, raw_val in raw_values.items():
            field = active_by_key[key]
            if _is_empty_value(raw_val):
                if bool(field.get("is_required", False)):
                    raise FieldValidationError(f"'{field['label']}' alanı zorunludur.")
                result.pop(key, None)
            else:
                result[key] = _coerce_and_validate_single_value(field, raw_val)
        return result

    result = {}
    for key, field in active_by_key.items():
        if key not in raw_values or _is_empty_value(raw_values[key]):
            if bool(field.get("is_required", False)):
                raise FieldValidationError(f"'{field['label']}' alanı zorunludur.")
            continue
        result[key] = _coerce_and_validate_single_value(field, raw_values[key])
    return result
