"""Pure decoding functions: number formats, scaling building blocks and fault words."""

from __future__ import annotations

import datetime

import pytest


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(0, 0), (1, 1), (32767, 32767), (32768, -32768), (65531, -5), (65535, -1)],
)
def test_int16_is_twos_complement(mapper, raw, expected):
    assert mapper.int16(100, {100: raw}) == expected


def test_uint16_is_left_alone(mapper):
    assert mapper.uint16(100, {100: 65535}) == 65535


@pytest.mark.parametrize(("raw", "expected"), [(23516, "2.35.16"), (10101, "1.1.1"), (0, "0.0.0")])
def test_version(mapper, raw, expected):
    assert mapper.version(100, {100: raw}) == expected


def test_accumulated_kwh_is_megawatt_hours_plus_tenths_of_kwh(mapper):
    assert mapper.accumulated_kwh(100, {100: 1, 101: 3495}) == pytest.approx(1349.5)
    assert mapper.accumulated_kwh(100, {100: 0, 101: 0}) == 0
    assert mapper.accumulated_kwh(100, {100: 12, 101: 9999}) == pytest.approx(12999.9)


def test_duration_is_hours_minutes_seconds(mapper):
    assert mapper.duration(100, {100: 1, 101: 2, 102: 3}) == 3723


def test_serial_number_is_high_word_then_low_word(mapper):
    assert mapper.serial(100, {100: 0x1234, 101: 0x5678}) == 0x12345678
    assert mapper.serial(100, {100: 0xFFFF, 101: 0xFFFF}) == 0xFFFFFFFF


def test_ph1100_serial_number_is_three_groups_of_five_digits(mapper):
    assert mapper.serial_string(100, {100: 1, 101: 23, 102: 456}) == "000010002300456"


def test_model_is_two_letters_and_a_number(mapper):
    assert mapper.model(100, {100: 20566, 101: 1800}) == "PV1800"


def test_time_of_day(mapper):
    assert mapper.time(100, {100: 1230}) == datetime.time(12, 30)


# --- fault and warning words -------------------------------------------------------------


@pytest.mark.parametrize("table", ["INVERTER_ERROR", "INVERTER_WARNING", "CHARGER_ERROR", "CHARGER_WARNING"])
def test_fault_tables_cover_whole_registers(const, table):
    # error_bits() decodes len(table) // 16 registers: a table of 31 entries silently
    # drops its whole second register (the bug fixed in 1.0.4).
    assert len(getattr(const, table)) % 16 == 0


def test_inverter_fault_table_has_both_words_and_no_glued_messages(const):
    assert len(const.INVERTER_ERROR) == 32
    assert const.INVERTER_ERROR[15] == "Inverter grid over current error"
    assert const.INVERTER_ERROR[16] == "Inverter radiator over temperature"


def test_no_fault_bits_reads_no_errors(mapper, const):
    assert mapper.error_bits(25261, {25261: 0, 25262: 0}, const.INVERTER_ERROR) == "No errors"


@pytest.mark.parametrize(
    ("first_word", "second_word", "expected"),
    [
        (1 << 0, 0, "Fan is locked when inverter is off"),
        (1 << 3, 0, "battery voltage is too low"),
        (1 << 15, 0, "Inverter grid over current error"),
        (0, 1 << 0, "Inverter radiator over temperature"),
        (0, 1 << 4, "Inverter grid voltage is low"),
        (0, 1 << 12, "Battery connection is open"),
        (0, 1 << 15, "Unknown error bit 31"),
        (1 << 4, 1 << 8, "Output short circuited, Inverter over current protection error"),
    ],
)
def test_inverter_faults_are_decoded_from_both_words(mapper, const, first_word, second_word, expected):
    words = {25261: first_word, 25262: second_word}
    assert mapper.error_bits(25261, words, const.INVERTER_ERROR) == expected


def test_recorded_frame_has_no_faults(mapper, registers):
    charger = mapper.convert_partArr3(registers)
    inverter = mapper.convert_partArr6(registers)
    assert charger["ChargerErrorMessage"] == "No errors"
    assert charger["ChargerWarningMessage"] == "No errors"
    assert inverter["InverterErrorMessage"] == "No errors"
    assert inverter["InverterWarningMessage"] == "No errors"


def test_fault_in_second_word_shows_up_in_the_recorded_frame(mapper, registers):
    # the recorded poll, with "battery connection is open" (second fault word, bit 12)
    registers[25262] = 1 << 12
    assert mapper.convert_partArr6(registers)["InverterErrorMessage"] == "Battery connection is open"


def test_faults_in_both_words_show_up_together(mapper, registers):
    registers[25261] = 1 << 1
    registers[25262] = 1 << 0
    assert mapper.convert_partArr6(registers)["InverterErrorMessage"] == (
        "Inverter transformer over temperature, Inverter radiator over temperature"
    )


def test_low_battery_warning(mapper, registers):
    registers[25265] = 1 << 3
    assert mapper.convert_partArr6(registers)["InverterWarningMessage"] == "Low battery"


def test_charger_fault(mapper, registers):
    registers[15213] = 1 << 6
    assert mapper.convert_partArr3(registers)["ChargerErrorMessage"] == "Battery voltage is too high"
