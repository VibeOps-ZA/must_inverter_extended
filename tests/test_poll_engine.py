"""The poll loop and the write path, driven by a scripted fake inverter (no hardware)."""

from __future__ import annotations

import asyncio

import pytest
from conftest import FakeResponse

PV1800_BLOCKS = [(10101, 24), (15201, 21), (20000, 17), (20101, 114), (25201, 79), (113, 2)]
SERIAL = 0x12345678


def poll(inverter):
    return asyncio.run(inverter.read_modbus_data())


def count_quiet_waits(inverter) -> list:
    waits: list = []
    original = inverter._quiet_wait

    async def counted():
        waits.append(1)
        await original()

    inverter._quiet_wait = counted
    return waits


# --- normal operation ----------------------------------------------------------------------


def test_good_poll_reads_the_six_blocks_once_and_decodes_them(make_inverter, issues):
    inverter, client = make_inverter()

    assert poll(inverter) is True

    assert client.reads == PV1800_BLOCKS
    assert len(inverter.registers) == 257
    assert inverter.data["InverterSerialNumber"] == SERIAL
    assert inverter.data["InverterMachineType"] == "PV1800"
    assert inverter.data["StateOfCharge"] == 70
    assert inverter.data["AccumulatedLoadPower"] == pytest.approx(1520.2)
    assert inverter.data["InverterErrorMessage"] == "No errors"
    assert issues == []


def test_forbidden_register_areas_are_never_read(make_inverter):
    # reading 10009-10100 or 20017-20100 can shut a Must inverter down
    inverter, client = make_inverter()
    poll(inverter)
    for start, count in client.reads:
        touched = range(start, start + count)
        assert not any(10009 <= address <= 10100 or 20017 <= address <= 20100 for address in touched)


def test_fault_in_the_second_word_reaches_the_entities(make_inverter):
    inverter, client = make_inverter()
    client.answers[25201][25262 - 25201] = 1 << 0  # radiator over temperature
    poll(inverter)
    assert inverter.data["InverterErrorMessage"] == "Inverter radiator over temperature"


# --- answers that cannot be real -----------------------------------------------------------


def test_inverter_answering_all_zeroes_at_start_up_is_not_set_up(make_inverter, issues):
    inverter, client = make_inverter()
    for start, count in PV1800_BLOCKS:
        client.answers[start] = [0] * count

    assert poll(inverter) is False  # setup then retries later instead of creating entities

    assert "InverterSerialNumber" not in inverter.data  # no entity ids starting with "0_"
    assert not any(name.startswith("Accumulated") for name in inverter.data)
    assert ("create", "no_serial_number") not in issues


def test_all_zero_answers_while_running_keep_serial_number_and_energy_totals(make_inverter, issues):
    inverter, client = make_inverter()
    assert poll(inverter) is True
    before = dict(inverter.data)

    for start, count in PV1800_BLOCKS[:5]:
        client.answers[start] = [0] * count
    assert poll(inverter) is True

    assert inverter.data["InverterSerialNumber"] == SERIAL
    for name in ("AccumulatedPower", "AccumulatedLoadPower", "AccumulatedBuyPower", "AccumulatedDischargerPower"):
        assert inverter.data[name] == before[name], name  # no drop to 0 = no double counting
    assert inverter.data["BattVolGrade"] == 24
    assert ("create", "no_serial_number") not in issues
    # the raw-register sensors of the ignored blocks have no value for this poll
    assert set(inverter.registers) == {113, 114}


def test_only_the_blank_block_is_ignored(make_inverter):
    inverter, client = make_inverter()
    poll(inverter)
    client.answers[25201] = [0] * 79
    client.answers[15201][15205 - 15201] = 1500  # PV voltage moved on

    poll(inverter)

    assert inverter.data["AccumulatedLoadPower"] == pytest.approx(1520.2)  # kept
    assert inverter.data["PvVoltage"] == 1500  # fresh
    assert 25253 not in inverter.registers
    assert 15205 in inverter.registers


def test_all_65535_answer_is_ignored(make_inverter):
    inverter, client = make_inverter()
    poll(inverter)
    client.answers[20101] = [0xFFFF] * 114
    poll(inverter)
    assert inverter.data["EnergyUseMode"] == 1
    assert inverter.data["FloatVoltage"] == 280


def test_values_come_back_after_a_blank_answer(make_inverter, frame):
    inverter, client = make_inverter()
    poll(inverter)
    client.answers[25201] = [0] * 79
    poll(inverter)
    recovered = list(frame["25201"])
    recovered[25254 - 25201] = 5210  # load energy counted on
    client.answers[25201] = recovered

    poll(inverter)

    assert inverter.data["AccumulatedLoadPower"] == pytest.approx(1521.0)
    assert 25253 in inverter.registers


def test_changed_serial_number_is_ignored(make_inverter, issues):
    inverter, client = make_inverter()
    poll(inverter)
    garbled = list(client.answers[20000])
    garbled[2:4] = [0, 0]  # serial number reads 0, rest of the block looks normal
    client.answers[20000] = garbled

    assert poll(inverter) is True

    assert inverter.data["InverterSerialNumber"] == SERIAL
    assert ("create", "no_serial_number") not in issues


def test_new_serial_number_is_accepted_after_the_repair_wrote_it(make_inverter):
    inverter, client = make_inverter()
    poll(inverter)
    renamed = list(client.answers[20000])
    renamed[2:4] = [0x0001, 0x0002]
    client.answers[20000] = renamed

    inverter.forget_known_serial()
    poll(inverter)

    assert inverter.data["InverterSerialNumber"] == 0x00010002


def test_inverter_without_a_serial_number_still_works_and_offers_the_repair(make_inverter, issues):
    inverter, client = make_inverter()
    client.answers[20000][2:4] = [0xFFFF, 0xFFFF]

    assert poll(inverter) is True
    assert poll(inverter) is True

    assert inverter.data["InverterSerialNumber"] == 0xFFFFFFFF
    assert ("create", "no_serial_number") in issues


def test_battery_block_reading_zero_is_taken_as_is(make_inverter):
    # 113-114 is not judged: a BMS may really report 0 %
    inverter, client = make_inverter()
    client.answers[113] = [0, 0]
    poll(inverter)
    assert inverter.data["StateOfCharge"] == 0


# --- replies that arrive late ----------------------------------------------------------------


def shift_replies(client, frame):
    """Every request gets the reply to the request before it (what one late reply causes)."""
    starts = [start for start, _count in PV1800_BLOCKS]
    for previous, start in zip(starts, starts[1:], strict=False):
        client.answers[start] = list(frame[str(previous)])


def test_one_shifted_poll_counts_as_one_mismatch_and_raises_no_repair(make_inverter, frame, issues):
    inverter, client = make_inverter()
    poll(inverter)
    inverter._started -= 3600  # well past the start-up grace period
    good = dict(inverter.data)
    waits = count_quiet_waits(inverter)
    shift_replies(client, frame)

    assert poll(inverter) is True

    assert len(inverter._mismatches) == 1  # was 5, enough to raise the repair on its own
    assert len(waits) == 5  # one pause per shifted reply, to let the late reply pass
    assert ("create", "mismatched_registers") not in issues
    assert inverter.data["AccumulatedLoadPower"] == good["AccumulatedLoadPower"]
    assert inverter.data["InverterSerialNumber"] == SERIAL


def test_three_shifted_polls_still_raise_the_repair(make_inverter, frame, issues):
    inverter, client = make_inverter()
    poll(inverter)
    inverter._started -= 3600
    shift_replies(client, frame)

    for _ in range(3):
        poll(inverter)

    assert len(inverter._mismatches) == 3
    assert ("create", "mismatched_registers") in issues


def test_answer_that_needed_a_retry_is_followed_by_a_pause(make_inverter, frame):
    inverter, client = make_inverter()
    waits = count_quiet_waits(inverter)
    client.answers[15201] = FakeResponse(frame["15201"], retries=1)

    assert poll(inverter) is True

    assert len(waits) == 1
    assert inverter.data["PvVoltage"] == 1018  # the answer itself is used


def test_no_pause_on_a_clean_poll(make_inverter):
    inverter, _client = make_inverter()
    waits = count_quiet_waits(inverter)
    poll(inverter)
    assert waits == []


# --- writes ----------------------------------------------------------------------------------


def test_accepted_write_is_sent_once(make_inverter):
    inverter, client = make_inverter()
    response = asyncio.run(inverter.write_modbus_data(20109, 3))
    assert client.writes == [(20109, 3)]
    assert response.isError() is False


def test_refused_write_raises_instead_of_looking_like_success(make_inverter, must):
    from homeassistant.exceptions import HomeAssistantError

    inverter, client = make_inverter()
    client.refuse_writes = True

    with pytest.raises(HomeAssistantError, match="20109"):
        asyncio.run(inverter.write_modbus_data(20109, 3))

    assert client.writes == [(20109, 3)]


# --- model variants and options ----------------------------------------------------------------


def test_pv1900_reads_pv1_values_from_the_charger_block(make_inverter):
    inverter, client = make_inverter(model="pv1900")
    client.answers[16205] = [0, 0, 0, 0]  # second PV input at night: really all 0

    assert poll(inverter) is True

    starts = [start for start, _count in client.reads]
    assert starts == [10101, 15201, 20000, 20101, 25201, 113, 16205]  # 15207-15208 not asked twice
    assert inverter.data["PV1ChargerCurrent"] == 22
    assert inverter.data["PV1ChargerPower"] == 222
    assert inverter.data["PV2ChargerPower"] == 0
    assert inverter.data["StateOfCharge"] == 70


def test_pv1800_does_not_get_pv1900_values(make_inverter):
    inverter, _client = make_inverter()
    poll(inverter)
    assert "PV1ChargerCurrent" not in inverter.data


@pytest.mark.parametrize("configured", [0, -5, 0.2])
def test_scan_interval_is_never_below_one_second(make_inverter, configured):
    inverter, _client = make_inverter(scan_interval=configured)
    assert inverter._scan_interval.total_seconds() == 1


def test_normal_scan_interval_is_kept(make_inverter):
    inverter, _client = make_inverter(scan_interval=15)
    assert inverter._scan_interval.total_seconds() == 15
