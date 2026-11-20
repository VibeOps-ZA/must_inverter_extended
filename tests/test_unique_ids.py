"""Entity ids must never change: existing dashboards, automations and voice control use them.

Home Assistant finds an entity again by its unique id, "<serial number>_<key>". The golden
file lists the keys of all 156 entities of a real installation (PV18-4024PREM set up as
pv1800 with a lithium BMS, release 1.0.3). The integration must keep producing exactly
these - adding entities is fine once the golden file is extended on purpose, renaming or
dropping one is not.
"""

from __future__ import annotations

import ast
import asyncio

import pytest
from conftest import COMPONENT_DIR, TESTS_DIR

PLATFORM_FILES = ["sensor.py", "binary_sensor.py", "number.py", "select.py", "switch.py", "button.py", "time.py"]


def _golden() -> set:
    lines = (TESTS_DIR / "golden" / "pv1800_unique_id_suffixes.txt").read_text().splitlines()
    return {line.strip() for line in lines if line.strip()}


def _raw_registers() -> list:
    """Read RAW_REGISTERS out of sensor.py without importing it (it needs Home Assistant)."""
    tree = ast.parse((COMPONENT_DIR / "sensor.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and node.targets[0].id == "RAW_REGISTERS":
            return list(ast.literal_eval(node.value))
    raise AssertionError("RAW_REGISTERS not found in sensor.py")


def _settings_switches() -> list:
    """Read the names of the 'system setting' switches out of switch.py without importing it."""
    tree = ast.parse((COMPONENT_DIR / "switch.py").read_text())
    names = [
        node.args[1].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Setting" and len(node.args) == 4
    ]
    assert names, "no Setting(...) entries found in switch.py"
    return names


def test_golden_file_is_complete():
    assert len(_golden()) == 156


def test_pv1800_unique_id_keys_match_the_real_installation(const):
    produced = {sensor.name for sensor in const.SENSORS_ARRAY}
    produced |= {"StateOfCharge", "BatteryStateOfHealth"}  # battery SoC/SoH from the BMS
    produced |= {f"raw_{address}" for address in _raw_registers()}
    produced |= {"BatteryChargePower", "BatteryDischargePower"}
    produced |= set(_settings_switches())

    golden = _golden()
    assert golden - produced == set(), "entities of existing installations would lose their id"
    assert produced - golden == set(), "new entities: add them to the golden file on purpose"


def test_no_key_is_defined_twice(const):
    names = [sensor.name for sensor in const.SENSORS_ARRAY]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("filename", PLATFORM_FILES)
def test_unique_id_starts_with_the_serial_number(filename):
    source = (COMPONENT_DIR / filename).read_text()
    assert "self._attr_unique_id = f\"{self._inverter.data['InverterSerialNumber']}_" in source


def test_unique_id_formats_in_sensor_py():
    source = (COMPONENT_DIR / "sensor.py").read_text()
    assert "f\"{self._inverter.data['InverterSerialNumber']}_raw_{address}\"" in source
    assert "f\"{self._inverter.data['InverterSerialNumber']}_{key}\"" in source
    assert "f\"{self._inverter.data['InverterSerialNumber']}_{self._key}\"" in source


def test_device_identifier_is_the_serial_number_as_a_number(make_inverter, must):
    # the device registry of existing installations holds (domain, <number>); a text
    # identifier would create a second device
    inverter, _client = make_inverter()
    assert asyncio.run(inverter.read_modbus_data()) is True
    info = inverter._device_info()
    assert info["identifiers"] == {(must.DOMAIN, 0x12345678)}
    assert info["serial_number"] == str(0x12345678)  # text: required from Home Assistant 2026.12
