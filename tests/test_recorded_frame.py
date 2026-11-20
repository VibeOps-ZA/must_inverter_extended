"""Decode and scale one recorded poll of a PV18-4024PREM and compare with known values.

The expected numbers are what Home Assistant showed for this poll (release 1.0.3), worked
out by hand from the raw registers - so a changed address, sign or scale factor fails here.
"""

from __future__ import annotations

import pytest

# name: value as shown in Home Assistant (raw register value x scale factor)
EXPECTED = {
    # charger settings (10101-10124)
    "AbsorbVoltage": 25.0,
    "FloatVoltage": 28.0,
    "AbsorptionVoltage": 28.4,
    "BatteryLowVoltage": 21.0,
    "BatteryHighVoltage": 30.0,
    "MaxChargerCurrent": 85.0,
    "AbsorbChargerCurrent": 10.0,
    "BatteryAh": 280,
    "BatteryEqualizationVoltage": 28.0,
    "BatteryEqualizationTime": 5,
    "BatteryEqualizationTimeout": 5,
    "BatteryEqualizationInterval": 90,
    # charger readings (15201-15221)
    "PvVoltage": 101.8,
    "BatteryVoltage": 0.0,
    "ChargerCurrent": 2.2,
    "ChargerPower": 222,
    "RadiatorTemperature": 54,
    "ExternalTemperature": 0,
    "BattVolGrade": 24,
    "RatedCurrent": 100.0,
    "AccumulatedPower": 1349.5,
    "AccumulatedTime": 0,
    # inverter settings (20101-20214)
    "InverterOutputVoltageSet": 220.0,
    "InverterOutputFrequencySet": 50.0,
    "InverterMaxDischargerCurrent": 15.9,
    "BatteryStopDischargingVoltage": 24.0,
    "BatteryStopChargingVoltage": 27.8,
    "GridMaxChargerCurrentSet": 40.0,
    "InverterBatteryLowVoltage": 22.6,
    "InverterBatteryHighVoltage": 30.0,
    "MaxCombineChargerCurrent": 80.0,
    "SystemSetting": 751,
    "SocBackToGrid": 20,
    "SocBackToBattery": 95,
    # inverter readings (25201-25279)
    "AcVoltageGrade": 230,
    "RatedPower": 4000,
    "InverterBatteryVoltage": 26.6,
    "InverterVoltage": 220.0,
    "GridVoltage": 218.0,
    "BusVoltage": 437.0,
    "ControlCurrent": 0.0,
    "InverterCurrent": 2.0,
    "GridCurrent": 0.0,
    "LoadCurrent": 2.2,
    "PInverter": 411,
    "PGrid": 0,
    "PLoad": 431,
    "LoadPercent": 12,
    "SInverter": 411,
    "SGrid": 0,
    "Sload": 454,
    "Qinverter": 0,
    "Qgrid": 0,
    "Qload": 229,
    "InverterFrequency": 50.0,
    "GridFrequency": 49.92,
    "AcRadiatorTemperature": 48,
    "TransformerTemperature": 0,
    "DcRadiatorTemperature": 62,
    "AccumulatedChargerPower": 0.0,
    "AccumulatedDischargerPower": 1196.2,
    "AccumulatedBuyPower": 432.8,
    "AccumulatedSellPower": 0.0,
    "AccumulatedLoadPower": 1520.2,
    "AccumulatedSelfUsePower": 1196.9,
    "AccumulatedPvSellPower": 0.0,
    "AccumulatedGridChargerPower": 179.0,
    "BattPower": 244,
    "BattCurrent": 9,
    "RatedPowerW": 4000,
    # battery management system (113-114)
    "StateOfCharge": 70,
    "BatteryStateOfHealth": 100,
}

EXPECTED_TEXT = {
    "InverterMachineType": "PV1800",
    "InverterSerialNumber": 0x12345678,
    "InverterHardwareVersion": "1.1.1",
    "InverterSoftwareVersion": "2.35.16",
}

# name: option shown in Home Assistant (None = "unknown")
EXPECTED_OPTIONS = {
    "EnergyUseMode": "sbu",
    "GridProtectStandard": "ups",
    "SolarUseAim": "lbu",
    "ChargerSourcePriority": "solar_and_utility",
    "WorkState": "offgrid",
    "BatteryType": "lithium",
    "ChargerWorkstate": "work",
    "MpptState": "mppt",
    "ChargingState": None,  # register 15203 reads 5, which has no documented meaning
}

EXPECTED_ON = {
    "ChargerWorkEnable": True,
    "BatteryEqualizationEnable": False,
    "BatteryEqualizationImmediately": False,
    "InverterOffgridWorkEnable": True,
    "InverterSearchModeEnable": False,
    "InverterOngridWorkEnable": True,
    "InverterChargerFromGridEnable": True,
    "InverterDischargerEnable": True,
    "InverterDischargerToGridEnable": False,
    "SolarPowerBalance": False,
    "BatteryRelay": False,
    "PvRelay": False,
    "InverterRelayState": True,
    "GridRelayState": False,
    "LoadRelayState": True,
    "N_LineRelayState": False,
    "DCRelayState": False,
    "EarthRelayState": False,
}


@pytest.fixture
def decoded(mapper, registers) -> dict:
    """Return the recorded poll run through every PV1800 decoder, as the integration does."""
    data = {}
    for convert in (
        mapper.convert_partArr2,
        mapper.convert_partArr3,
        mapper.convert_partArr4,
        mapper.convert_partArr5,
        mapper.convert_partArr6,
        mapper.convert_battery_status,
    ):
        data.update(convert(registers))
    return data


@pytest.fixture
def sensors(const) -> dict:
    """Return the PV1800 entity definitions by name (base set plus battery SoC/SoH)."""
    by_name = {sensor.name: sensor for sensor in const.PV1900_SENSORS}
    by_name.update({sensor.name: sensor for sensor in const.SENSORS_ARRAY})
    return by_name


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_scaled_value(decoded, sensors, name):
    sensor = sensors[name]
    shown = decoded[name] * (sensor.coeff or 1)  # same sum as the sensor and number entities
    assert shown == pytest.approx(EXPECTED[name], abs=1e-9)


@pytest.mark.parametrize("name", sorted(EXPECTED_TEXT))
def test_identity_value(decoded, name):
    assert decoded[name] == EXPECTED_TEXT[name]


@pytest.mark.parametrize("name", sorted(EXPECTED_OPTIONS))
def test_option(decoded, const, name):
    options = const.OPTIONS[name]
    value = decoded[name]
    shown = options[value] if 0 <= value < len(options) and options[value] else None
    assert shown == EXPECTED_OPTIONS[name]


@pytest.mark.parametrize("name", sorted(EXPECTED_ON))
def test_switch_or_relay(decoded, name):
    assert (decoded[name] == 1) is EXPECTED_ON[name]


def test_every_entity_definition_is_decoded(decoded, const):
    # a definition whose key no decoder produces would be an entity that never has a value
    buttons = {sensor.name for sensor in const.SENSORS_ARRAY if sensor.platform == "button"}
    missing = {sensor.name for sensor in const.SENSORS_ARRAY} - buttons - set(decoded)
    assert missing == set()


def test_units_of_energy_sensors(const):
    # the Energy dashboard needs kWh + device class energy on every lifetime counter
    for sensor in const.SENSORS_ARRAY:
        if sensor.name.startswith("Accumulated") and sensor.name != "AccumulatedTime":
            assert (sensor.unit, sensor.device_class, sensor.coeff) == ("kWh", "energy", None), sensor.name


def test_pv1900_pv1_values_come_from_the_charger_block(mapper, registers):
    decoded = mapper.convert_partArr3_with_pv1(registers)
    assert decoded["PV1ChargerCurrent"] == 22  # 2.2 A after the 0.1 scale factor
    assert decoded["PV1ChargerPower"] == 222
    assert decoded["ChargerPower"] == 222  # the normal charger values are still there
