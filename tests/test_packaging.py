"""The files Home Assistant and HACS read: manifest, hacs.json, translations, changelog."""

from __future__ import annotations

import json
import re

import pytest
from conftest import COMPONENT_DIR, REPO_ROOT

LANGUAGES = ["en", "pt-BR"]


def _json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def test_manifest_requires_only_pymodbus():
    manifest = _json(COMPONENT_DIR / "manifest.json")
    assert manifest["domain"] == "must_inverter"  # same domain = same entities as before
    assert manifest["requirements"] == ["pymodbus>=3.10.0"]


def test_no_code_uses_the_removed_register_monitor():
    assert not (COMPONENT_DIR / "utils").exists()
    for path in COMPONENT_DIR.glob("*.py"):
        source = path.read_text()
        assert "aiofiles" not in source, path.name
        assert "register_monitor" not in source, path.name


def test_minimum_home_assistant_version_has_pymodbus_3_10():
    # pymodbus 3.10 (the device_id= argument) first shipped with Home Assistant 2025.9
    major, minor, _patch = (int(part) for part in _json(REPO_ROOT / "hacs.json")["homeassistant"].split("."))
    assert (major, minor) >= (2025, 9)


def test_changelog_starts_with_the_manifest_version():
    version = _json(COMPONENT_DIR / "manifest.json")["version"]
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text()
    first = re.search(r"^## \[([^\]]+)\]", changelog, re.MULTILINE)
    assert first is not None
    assert first.group(1) == version


@pytest.mark.parametrize("language", LANGUAGES)
def test_translation_file_is_valid_and_has_the_new_texts(language):
    texts = _json(COMPONENT_DIR / "translations" / f"{language}.json")
    assert texts["entity"]["binary_sensor"]["connected"]["name"]
    for flow in ("config", "options"):
        step = texts[flow]["step"]["modbus"]
        assert step["data"]["allow_calibration_writes"]
        assert step["data_description"]["allow_calibration_writes"]


def test_every_entity_has_an_english_name(const):
    texts = _json(COMPONENT_DIR / "translations" / "en.json")["entity"]
    for sensors in (const.SENSORS_ARRAY, const.PV1900_SENSORS, const.PH1100_SENSORS):
        for sensor in sensors:
            assert sensor.name.lower() in texts[sensor.platform], sensor.name


def test_every_option_of_a_select_or_state_sensor_has_an_english_name(const):
    texts = _json(COMPONENT_DIR / "translations" / "en.json")["entity"]
    for key, options in const.OPTIONS.items():
        entry = texts["select"].get(key.lower()) or texts["sensor"].get(key.lower())
        assert entry is not None, key
        for option in options:
            if option:
                assert option in entry["state"], (key, option)


def test_readme_does_not_promise_an_older_home_assistant():
    readme = (REPO_ROOT / "README.md").read_text()
    assert "Home Assistant 2025.9 or newer" in readme
    assert "(2025.1 or newer)" not in readme


@pytest.mark.parametrize("language", LANGUAGES)
def test_old_charging_state_name_is_still_translated(language):
    # "equalization_charge" is no longer produced, but history recorded before 1.1.0 holds it
    texts = _json(COMPONENT_DIR / "translations" / f"{language}.json")
    assert texts["entity"]["sensor"]["chargingstate"]["state"]["equalization_charge"]
