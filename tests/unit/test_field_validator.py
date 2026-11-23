from __future__ import annotations

import pytest

from app.services.field_validator import (
    FieldValidationError,
    slugify_field_key,
    validate_field_definition,
    validate_field_key,
    validate_field_values,
)


def _field(
    key: str,
    field_type: str,
    *,
    label: str | None = None,
    scope: str = "profile",
    options: list[str] | None = None,
    is_required: bool = False,
    is_active: bool = True,
) -> dict:
    return {
        "field_key": key,
        "label": label or key,
        "scope": scope,
        "field_type": field_type,
        "options": options,
        "is_required": is_required,
        "is_active": is_active,
    }


def test_slugify_field_key_turkish_and_cleanup() -> None:
    assert slugify_field_key("Savaş Gücü (İttifak) - ÇÖÜĞŞİı") == "savas_gucu_ittifak_cougsii"
    assert slugify_field_key("İttifak Gücü — Şehir (Özel)") == "ittifak_gucu_sehir_ozel"
    assert slugify_field_key("  -- Güç 2 -- ") == "guc_2"


def test_slugify_field_key_punctuation_only_raises() -> None:
    with pytest.raises(FieldValidationError):
        slugify_field_key("--- !!! ---")
    with pytest.raises(FieldValidationError):
        slugify_field_key("   ")


def test_validate_field_key_accepts_valid_and_rejects_invalid() -> None:
    assert validate_field_key("valid_key_1") == "valid_key_1"
    for bad in ("", "   ", "Bad Key!", "BuyukHarf", "_leading", "a-b", "a" * 65):
        with pytest.raises(FieldValidationError):
            validate_field_key(bad)


def test_validate_field_definition_select_options_and_types() -> None:
    defn = validate_field_definition(
        label="Birlik Sınıfı",
        scope="profile",
        field_type="select",
        options=["Piyade", "Okçu", "Piyade"],
    )
    assert defn["field_key"] == "birlik_sinifi"
    assert defn["options"] == ["Piyade", "Okçu"]

    for bad_opts in (None, [], ["", "  "], ["A", "  "], [123]):
        with pytest.raises(FieldValidationError):
            validate_field_definition(
                label="Sınıf",
                scope="profile",
                field_type="select",
                options=bad_opts,
            )

    num_def = validate_field_definition(
        label="Güç",
        scope="progression",
        field_type="number",
        options=None,
    )
    assert num_def["options"] is None

    with pytest.raises(FieldValidationError):
        validate_field_definition(
            label="Güç",
            scope="progression",
            field_type="number",
            options=["A"],
        )

    with pytest.raises(FieldValidationError):
        validate_field_definition(label="X", scope="invalid", field_type="text")

    with pytest.raises(FieldValidationError):
        validate_field_definition(label="X", scope="profile", field_type="float")

    with pytest.raises(FieldValidationError):
        validate_field_definition(
            label="X", scope="profile", field_type="text", sort_order=True
        )


def test_text_field_validation() -> None:
    fields = [_field("not_alani", "text")]
    assert validate_field_values(fields, {"not_alani": "Savaşçı"}) == {"not_alani": "Savaşçı"}
    assert validate_field_values(fields, {"not_alani": "  metin  "}) == {"not_alani": "metin"}

    for bad in (123, True, ["a"], {"k": "v"}, "abc\x01def", "x" * 501):
        with pytest.raises(FieldValidationError):
            validate_field_values(fields, {"not_alani": bad})


def test_number_field_validation_and_bool_trap() -> None:
    fields = [_field("power", "number", scope="progression")]
    assert validate_field_values(fields, {"power": 0}) == {"power": 0}
    assert validate_field_values(fields, {"power": 0.0}) == {"power": 0.0}
    assert validate_field_values(fields, {"power": 1250000}) == {"power": 1250000}
    assert validate_field_values(fields, {"power": 3.14}) == {"power": 3.14}
    assert validate_field_values(fields, {"power": -10}) == {"power": -10}
    assert validate_field_values(fields, {"power": "42"}) == {"power": 42}
    assert validate_field_values(fields, {"power": "3.5"}) == {"power": 3.5}

    # Critical: bool is a subclass of int in Python and MUST be rejected
    for bad in (
        True,
        False,
        float("nan"),
        float("inf"),
        float("-inf"),
        "abc",
        "42abc",
        "True",
        ["1"],
        {},
    ):
        with pytest.raises(FieldValidationError):
            validate_field_values(fields, {"power": bad})


def test_boolean_field_validation() -> None:
    fields = [_field("vip", "boolean")]
    assert validate_field_values(fields, {"vip": True}) == {"vip": True}
    assert validate_field_values(fields, {"vip": False}) == {"vip": False}
    assert validate_field_values(fields, {"vip": "true"}) == {"vip": True}
    assert validate_field_values(fields, {"vip": "FALSE"}) == {"vip": False}

    for bad in ("maybe", "evet", "abc", "123", 0, 1, 2, -1, [], {}):
        with pytest.raises(FieldValidationError):
            validate_field_values(fields, {"vip": bad})


def test_select_field_validation() -> None:
    fields = [_field("birlik", "select", options=["Piyade", "Okçu", "Süvari"])]
    assert validate_field_values(fields, {"birlik": "Okçu"}) == {"birlik": "Okçu"}

    for bad in ("Büyücü", "okçu", 1, True, ["Okçu"]):
        with pytest.raises(FieldValidationError):
            validate_field_values(fields, {"birlik": bad})


def test_date_field_validation() -> None:
    fields = [_field("tarih", "date")]
    assert validate_field_values(fields, {"tarih": "2026-11-22"}) == {"tarih": "2026-11-22"}
    assert validate_field_values(fields, {"tarih": "2024-02-29"}) == {"tarih": "2024-02-29"}

    for bad in (
        "2025-02-29",
        "2026-02-30",
        "2026-13-01",
        "22-11-2026",
        "2026/11/22",
        "bugün",
        20261122,
    ):
        with pytest.raises(FieldValidationError):
            validate_field_values(fields, {"tarih": bad})


def test_is_required_and_falsy_values() -> None:
    req_num = _field("guc", "number", is_required=True)
    req_bool = _field("aktif", "boolean", is_required=True)
    req_text = _field("isim", "text", is_required=True)
    req_sel = _field("sinif", "select", options=["A", "B"], is_required=True)
    req_date = _field("dogum", "date", is_required=True)
    opt_text = _field("not", "text", is_required=False)

    # Falsy 0, 0.0, False MUST pass is_required=True
    res = validate_field_values(
        [req_num, req_bool, req_text, req_sel, req_date, opt_text],
        {
            "guc": 0,
            "aktif": False,
            "isim": "Ali",
            "sinif": "A",
            "dogum": "2026-11-22",
        },
    )
    assert res["guc"] == 0
    assert res["aktif"] is False

    res_float = validate_field_values([req_num], {"guc": 0.0})
    assert res_float == {"guc": 0.0}

    # Missing required field rejected
    with pytest.raises(FieldValidationError):
        validate_field_values([req_num], {})

    # None / "" / "   " rejected for required fields of all types
    for f_def in (req_num, req_bool, req_text, req_sel, req_date):
        for empty in (None, "", "   "):
            with pytest.raises(FieldValidationError):
                validate_field_values([f_def], {f_def["field_key"]: empty})

    # Optional empty values omitted cleanly
    assert validate_field_values([opt_text], {"not": None}) == {}
    assert validate_field_values([opt_text], {"not": "   "}) == {}
    assert validate_field_values([opt_text], {}) == {}


def test_inactive_unknown_and_cross_scope_keys() -> None:
    inactive_req = _field("eski_alan", "text", is_required=True, is_active=False)
    active_opt = _field("yeni_alan", "text", is_required=False, is_active=True)

    # Inactive required field does not block when omitted
    assert validate_field_values([inactive_req, active_opt], {"yeni_alan": "ok"}) == {
        "yeni_alan": "ok"
    }

    # Supplying an inactive key in payload is rejected
    with pytest.raises(FieldValidationError):
        validate_field_values([inactive_req, active_opt], {"eski_alan": "val"})

    # Unknown or cross-scope keys rejected
    with pytest.raises(FieldValidationError):
        validate_field_values([active_opt], {"nonexistent_key": "x"})

    with pytest.raises(FieldValidationError):
        validate_field_values([active_opt], "not-a-dict")


def test_partial_patch_validation_and_existing_merge() -> None:
    fields = [
        _field("req_key", "text", is_required=True, is_active=True),
        _field("opt_num", "number", is_required=False, is_active=True),
        _field("opt_txt", "text", is_required=False, is_active=True),
        _field("archived_key", "text", is_required=True, is_active=False),
    ]

    # Partial update omitting required field without existing_values
    assert validate_field_values(fields, {"opt_txt": "yeni"}, partial=True) == {
        "opt_txt": "yeni"
    }

    # Partial merge preserves untouched + archived keys, clears optional key on None/""
    merged = validate_field_values(
        fields,
        {"opt_txt": None, "opt_num": 50},
        partial=True,
        existing_values={
            "req_key": "mevcut",
            "opt_txt": "eski",
            "archived_key": "arsiv_degeri",
        },
    )
    assert merged == {
        "req_key": "mevcut",
        "opt_num": 50,
        "archived_key": "arsiv_degeri",
    }

    # Clearing active required key is rejected
    for empty in (None, "", "  "):
        with pytest.raises(FieldValidationError):
            validate_field_values(fields, {"req_key": empty}, partial=True)

    # Invalid type in partial update rejected
    with pytest.raises(FieldValidationError):
        validate_field_values(fields, {"opt_num": True}, partial=True)
