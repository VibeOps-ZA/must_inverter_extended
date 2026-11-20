"""The entities themselves: created the way Home Assistant creates them, on a fake inverter."""

from __future__ import annotations

import asyncio

import pytest
from conftest import TESTS_DIR

SERIAL = 0x12345678
MAX_MISSED_POLLS = 5


def uid(key: str) -> str:
    return f"{SERIAL}_{key}"


def poll(inverter):
    return asyncio.run(inverter._async_refresh_modbus_data())


def golden() -> set:
    lines = (TESTS_DIR / "golden" / "pv1800_unique_id_suffixes.txt").read_text().splitlines()
    return {line.strip() for line in lines if line.strip()}


# --- ids ---------------------------------------------------------------------------------------


def test_created_entities_have_exactly_the_golden_unique_ids(make_entities):
    _inverter, _client, entities = make_entities()
    assert set(entities) == {uid(key) for key in golden()}


def test_values_shown_by_some_entities(make_entities):
    _inverter, _client, entities = make_entities()
    assert entities[uid("InverterBatteryVoltage")].state == pytest.approx(26.6)
    assert entities[uid("AccumulatedLoadPower")].state == pytest.approx(1520.2)
    assert entities[uid("WorkState")].state == "offgrid"
    assert entities[uid("ChargingState")].state is None  # raw value 5: unknown
    assert entities[uid("EnergyUseMode")].current_option == "sbu"
    assert entities[uid("FloatVoltage")].state == pytest.approx(28.0)
    assert entities[uid("InverterRelayState")].is_on is True
    assert entities[uid("Buzz")].is_on is False  # system setting 751: bit 5 set, shown inverted
    assert entities[uid("BatteryDischargePower")].native_value == 244
    assert entities[uid("BatteryChargePower")].native_value == 0
    assert entities[uid("raw_15203")].native_value == 5


def test_select_with_an_undocumented_value_is_unknown(make_entities):
    inverter, _client, entities = make_entities()
    inverter.data["BatteryType"] = 9
    assert entities[uid("BatteryType")].current_option is None
    inverter.data["BatteryType"] = -1
    assert entities[uid("BatteryType")].current_option is None


# --- availability and the Connected sensor -------------------------------------------------------

DATA_ENTITIES = [
    "InverterBatteryVoltage",  # sensor
    "AccumulatedLoadPower",  # energy sensor
    "StateOfCharge",  # sensor from the battery block
    "FloatVoltage",  # number
    "EnergyUseMode",  # select
    "SolarPowerBalance",  # switch
    "Buzz",  # system-setting switch
    "GridRelayState",  # binary sensor
    "BatteryChargePower",  # derived sensor
]


def silence(client):
    """From now on the inverter answers nothing (each request ends in a Modbus error)."""
    client.answers = {}


def test_everything_is_available_after_a_good_poll(make_entities):
    inverter, _client, entities = make_entities()
    for key in DATA_ENTITIES:
        assert entities[uid(key)].available is True, key
    connected = entities[uid("Connected")]
    assert connected.is_on is True
    assert connected.extra_state_attributes == {"missed_polls": 0}
    assert inverter.connected is True


def test_values_stay_for_four_missed_polls_and_go_unavailable_at_the_fifth(make_entities):
    inverter, client, entities = make_entities()
    silence(client)

    for _ in range(MAX_MISSED_POLLS - 1):
        poll(inverter)
    for key in DATA_ENTITIES:
        assert entities[uid(key)].available is True, key
    assert entities[uid("Connected")].is_on is True
    assert entities[uid("Connected")].extra_state_attributes == {"missed_polls": 4}

    poll(inverter)
    for key in DATA_ENTITIES:
        assert entities[uid(key)].available is False, key
    assert entities[uid("Connected")].is_on is False
    assert entities[uid("Connected")].extra_state_attributes == {"missed_polls": 5}


def test_missed_poll_count_stops_at_the_limit(make_entities):
    inverter, client, entities = make_entities()
    silence(client)
    for _ in range(MAX_MISSED_POLLS + 20):
        poll(inverter)
    # a long outage must not write a new state every 15 seconds
    assert entities[uid("Connected")].extra_state_attributes == {"missed_polls": 5}


def test_first_answer_brings_everything_back(make_entities, frame):
    inverter, client, entities = make_entities()
    silence(client)
    for _ in range(MAX_MISSED_POLLS + 2):
        poll(inverter)
    assert entities[uid("InverterBatteryVoltage")].available is False

    client.answers = {int(start): list(values) for start, values in frame.items()}
    poll(inverter)

    for key in DATA_ENTITIES:
        assert entities[uid(key)].available is True, key
    assert entities[uid("Connected")].is_on is True
    assert entities[uid("Connected")].extra_state_attributes == {"missed_polls": 0}


def test_blank_answers_also_count_as_missed(make_entities, frame):
    inverter, client, entities = make_entities()
    client.answers = {int(start): [0] * len(values) for start, values in frame.items() if int(start) != 113}
    for _ in range(MAX_MISSED_POLLS):
        poll(inverter)
    assert entities[uid("AccumulatedLoadPower")].available is False
    assert entities[uid("StateOfCharge")].available is False
    assert entities[uid("Connected")].is_on is False


def test_unplugged_cable_counts_as_missed_and_entities_are_told(make_entities):
    inverter, client, entities = make_entities()
    told: list = []
    inverter._callbacks.append(lambda: told.append(1))
    client.unplugged = True
    client.connected = False

    for _ in range(MAX_MISSED_POLLS):
        assert poll(inverter) is False

    assert len(told) == MAX_MISSED_POLLS
    assert entities[uid("InverterBatteryVoltage")].available is False
    assert entities[uid("Connected")].is_on is False


def test_one_silent_block_only_affects_its_own_entities(make_entities):
    inverter, client, entities = make_entities()
    del client.answers[25201]  # inverter readings and energy totals stop answering
    for _ in range(MAX_MISSED_POLLS):
        poll(inverter)

    assert entities[uid("PLoad")].available is False  # from 25201-25279
    assert entities[uid("AccumulatedLoadPower")].available is False
    assert entities[uid("BatteryChargePower")].available is False
    assert entities[uid("PvVoltage")].available is True  # from 15201-15221
    assert entities[uid("FloatVoltage")].available is True
    assert entities[uid("Connected")].is_on is True  # the inverter still answers


def test_battery_values_go_unavailable_when_the_bms_stops_answering(make_entities):
    inverter, client, entities = make_entities()
    del client.answers[113]
    for _ in range(MAX_MISSED_POLLS):
        poll(inverter)

    asked_for_bms = [start for start, _count in client.reads if start == 113]
    assert len(asked_for_bms) == 1 + 3  # the good poll, then given up after 3 failures
    assert entities[uid("StateOfCharge")].available is False
    assert entities[uid("BatteryStateOfHealth")].available is False
    assert entities[uid("InverterBatteryVoltage")].available is True
    assert entities[uid("Connected")].is_on is True


def test_outage_does_not_make_the_integration_give_up_on_the_bms(make_entities, frame):
    # before 1.1.0 any outage of 3 polls stopped the SoC/SoH reads until a restart,
    # leaving the last battery percentage on screen for ever
    inverter, client, entities = make_entities()
    silence(client)
    for _ in range(10):
        poll(inverter)
    restored = {int(start): list(values) for start, values in frame.items()}
    restored[113] = [55, 99]
    client.answers = restored

    poll(inverter)

    assert entities[uid("StateOfCharge")].available is True
    assert entities[uid("StateOfCharge")].state == 55
    assert entities[uid("BatteryStateOfHealth")].state == 99


def test_single_missed_poll_changes_nothing(make_entities, frame):
    inverter, client, entities = make_entities()
    silence(client)
    poll(inverter)
    client.answers = {int(start): list(values) for start, values in frame.items()}
    poll(inverter)
    assert entities[uid("Connected")].extra_state_attributes == {"missed_polls": 0}
    assert entities[uid("InverterBatteryVoltage")].available is True


def test_entity_that_fails_to_update_does_not_stop_the_others(make_entities):
    inverter, _client, _entities = make_entities()
    told: list = []

    def broken():
        raise RuntimeError("boom")

    inverter._callbacks.extend([broken, lambda: told.append(1)])
    assert poll(inverter) is True
    assert told == [1]
