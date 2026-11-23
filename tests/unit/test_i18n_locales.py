"""Unit tests validating TR/EN/AR/IT i18n locale dictionaries and frontend key references."""

from __future__ import annotations

import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
JS_ROOT = PROJECT_ROOT / "app" / "static" / "js"
LOCALES_DIR = JS_ROOT / "i18n" / "locales"
EXPECTED_LOCALES = ("tr", "en", "ar", "it")


def _load_locale_dict(code: str) -> dict[str, str]:
    path = LOCALES_DIR / f"{code}.js"
    assert path.is_file(), f"Missing locale file: {path}"
    raw = path.read_text(encoding="utf-8").strip()
    assert raw.startswith("export default "), f"{path.name} must start with 'export default '"
    body = raw[len("export default ") :].rstrip()
    if body.endswith(";"):
        body = body[:-1].strip()
    parsed = json.loads(body)
    assert isinstance(parsed, dict), f"{path.name} must export a JSON object"
    return parsed


def test_all_locales_share_identical_keys_and_placeholders() -> None:
    dicts = {code: _load_locale_dict(code) for code in EXPECTED_LOCALES}
    base_keys = set(dicts["tr"].keys())
    assert len(base_keys) > 100

    for code, mapping in dicts.items():
        keys = set(mapping.keys())
        missing = base_keys - keys
        extra = keys - base_keys
        assert not missing, f"Locale '{code}' is missing keys: {sorted(missing)}"
        assert not extra, f"Locale '{code}' has extra keys: {sorted(extra)}"

        for key, value in mapping.items():
            assert isinstance(value, str) and value.strip(), (
                f"Locale '{code}' key '{key}' must be a non-empty string"
            )

            expected_placeholders = sorted(re.findall(r"\{(\w+)\}", dicts["tr"][key]))
            actual_placeholders = sorted(re.findall(r"\{(\w+)\}", value))
            assert actual_placeholders == expected_placeholders, (
                f"Placeholder mismatch in locale '{code}' key '{key}': "
                f"expected {expected_placeholders}, got {actual_placeholders}"
            )


def test_every_js_translation_key_exists_in_all_locales() -> None:
    dicts = {code: _load_locale_dict(code) for code in EXPECTED_LOCALES}
    referenced_keys: set[str] = set()

    for js_file in JS_ROOT.rglob("*.js"):
        if js_file.parent == LOCALES_DIR:
            continue
        content = js_file.read_text(encoding="utf-8")
        for match in re.finditer(r"""\bt\(\s*(["'])([a-zA-Z0-9_.-]+)\1""", content):
            referenced_keys.add(match.group(2))

        for match in re.finditer(r'"(apiErrors\.[a-zA-Z0-9_.-]+)"', content):
            referenced_keys.add(match.group(1))

    assert len(referenced_keys) > 80

    for key in sorted(referenced_keys):
        for code in EXPECTED_LOCALES:
            assert key in dicts[code], f"Referenced key '{key}' is missing in locale '{code}'"
