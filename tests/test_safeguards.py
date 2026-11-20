"""The small safety checks in safeguards.py."""

from __future__ import annotations

import pytest

PV_BLOCKS = [10101, 15201, 20000, 20101, 25201]


# --- answers that cannot be real ---------------------------------------------------------


def test_every_block_of_the_recorded_frame_is_accepted(safeguards, frame):
    for start, values in frame.items():
        assert safeguards.block_reject_reason(int(start), values) is None, start


@pytest.mark.parametrize("start", [*PV_BLOCKS, 20001, 25225])
def test_blank_answer_is_rejected(safeguards, start):
    assert safeguards.block_reject_reason(start, [0] * 17) == "every register is 0"
    assert safeguards.block_reject_reason(start, [0xFFFF] * 17) == "every register is 65535"


@pytest.mark.parametrize("start", PV_BLOCKS)
def test_one_real_value_is_enough(safeguards, start):
    assert safeguards.block_reject_reason(start, [0, 0, 24, 0]) is None
    assert safeguards.block_reject_reason(start, [0xFFFF, 0xFFFF, 0]) is None


def test_blocks_that_may_really_be_blank_are_not_judged(safeguards):
    # battery SoC/SoH, the second PV input at night, and the PH1100 charger blocks
    for start in (113, 16205, 10102, 15104):
        assert safeguards.block_reject_reason(start, [0, 0, 0, 0]) is None
        assert safeguards.block_reject_reason(start, [0xFFFF] * 4) is None


def test_empty_answer_is_left_to_the_length_check(safeguards):
    assert safeguards.block_reject_reason(20000, []) is None


# --- serial number -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("known", "new", "changed"),
    [
        (None, 305419896, False),  # first read
        (305419896, 305419896, False),
        (305419896, 0, True),  # a blank answer that slipped through
        (305419896, 305419897, True),
        (305419896, None, False),  # block without a serial number
        (0, 0, False),  # inverter that really has no serial number
        ("000010002300456", "000010002300456", False),  # PH1100 text serial
        ("000010002300456", "000000000000000", True),
    ],
)
def test_serial_number_changed(safeguards, known, new, changed):
    assert safeguards.serial_number_changed(known, new) is changed


# --- option names ------------------------------------------------------------------------

ENERGY_USE_MODE = ["", "sbu", "sub", "uti", "sol"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1, "sbu"), (4, "sol"), (0, None), (5, None), (-1, None), (65535, None), (None, None), ("1", None), (True, None)],
)
def test_option_for_value(safeguards, value, expected):
    assert safeguards.option_for_value(ENERGY_USE_MODE, value) == expected


def test_every_documented_option_is_reachable(safeguards, const):
    for options in const.OPTIONS.values():
        for value, name in enumerate(options):
            assert safeguards.option_for_value(options, value) == (name or None)


# --- unique ids in the "no serial number" repair -------------------------------------------


@pytest.mark.parametrize(
    ("unique_id", "old", "new", "expected"),
    [
        ("0_BatteryVoltage", 0, 1763640000, "1763640000_BatteryVoltage"),
        ("0_raw_20006", 0, 1763640000, "1763640000_raw_20006"),  # str.replace() gave 1763640000_raw_2<new><new><new>6
        ("0_BatteryChargePower", 0, 77, "77_BatteryChargePower"),
        ("4294967295_PLoad", 4294967295, 12, "12_PLoad"),
        ("305419896_raw_25270", 305419896, 5, "5_raw_25270"),
        ("something_else", 0, 5, "something_else"),  # not ours: left alone
        ("10_PLoad", 0, 5, "10_PLoad"),  # "0_" must be at the very start
    ],
)
def test_rewrite_unique_id(safeguards, unique_id, old, new, expected):
    assert safeguards.rewrite_unique_id(unique_id, old, new) == expected


# --- diagnostics ---------------------------------------------------------------------------


def test_serial_number_registers_are_hidden_in_diagnostics(safeguards, registers):
    hidden = safeguards.redact_registers(registers)
    assert set(hidden) == set(registers)
    for address in (20002, 20003, 25269, 25270):
        assert hidden[address] == safeguards.REDACTED
    assert hidden[20000] == registers[20000]  # model letters stay
    assert hidden[25205] == registers[25205]
    assert registers[20002] != safeguards.REDACTED  # the live data is not touched
    assert not any(value in (0x1234, 0x5678) for value in hidden.values())


@pytest.mark.parametrize(
    ("unique_id", "is_serial"),
    [
        ("305419896_InverterSerialNumber", True),
        ("305419896_raw_25269", True),
        ("305419896_raw_25270", True),
        ("305419896_raw_25271", False),
        ("305419896_BatteryVoltage", False),
        (None, False),
    ],
)
def test_serial_number_entities_are_recognised(safeguards, unique_id, is_serial):
    assert safeguards.is_serial_number_unique_id(unique_id) is is_serial
