"""Small safety checks that need no Home Assistant code (EXTENDED 1.0.4).

Everything here is a plain function of its arguments, so it can be tested without
Home Assistant or an inverter (see the tests/ folder).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

REDACTED = "**REDACTED**"

# Register blocks that can never be "all 0" or "all 65535" on a working inverter:
# each holds values that are fixed and non-zero (model, rated power, battery voltage
# class, charge voltages ...). A Must inverter that has shut itself down answers every
# register with 0 until it is powered off and on again; taking such an answer as real
# would set the serial number to 0 (new entity ids at start-up) and drop the energy
# totals to 0 (Home Assistant then counts the whole lifetime total a second time).
#
# Deliberately NOT listed: 113-114 (battery SoC/SoH) and 16205-16208 (second PV
# input, really all 0 at night), and the PH1100 charger blocks, which were never
# recorded on real hardware.
NEVER_BLANK_BLOCKS = frozenset(
    {
        10101,  # PV1800/PV1900 charger settings
        15201,  # PV1800/PV1900 charger readings
        20000,  # PV1800/PV1900 model, serial number, versions
        20101,  # PV1800/PV1900 inverter settings
        25201,  # PV1800/PV1900 inverter readings and energy totals
        20001,  # PH1100 serial number
        25225,  # PH1100 inverter readings and energy totals
    }
)

# Registers that hold the inverter's serial number (20002-20003 on PV1800/PV1900,
# 20001-20003 on PH1100) or a copy of it (25269-25270, seen on a PV18-4024PREM).
SERIAL_NUMBER_REGISTERS = frozenset({20001, 20002, 20003, 25269, 25270})

# Unique-id endings of the entities whose state is the serial number or a part of it.
SERIAL_NUMBER_UNIQUE_ID_ENDINGS = ("_InverterSerialNumber", "_raw_25269", "_raw_25270")


def block_reject_reason(start: int, values: Sequence[int]) -> str | None:
    """Return why a register block cannot be real, or None when it looks fine.

    Only the blocks in NEVER_BLANK_BLOCKS are judged; every other block is accepted.
    """
    if start not in NEVER_BLANK_BLOCKS or not values:
        return None
    if all(value == 0 for value in values):
        return "every register is 0"
    if all(value == 0xFFFF for value in values):
        return "every register is 65535"
    return None


def serial_number_changed(known: Any, new: Any) -> bool:
    """Tell whether a freshly read serial number contradicts the one read earlier.

    An inverter cannot change its serial number while Home Assistant is running, so
    a different value means the answer is damaged. `known` is None until the first
    serial number has been accepted; a missing new value is not a contradiction.
    """
    return known is not None and new is not None and new != known


def option_for_value(options: Sequence[str], value: Any) -> str | None:
    """Translate a register value into its option name, or None when it has none.

    Values outside the list, negative values, and gaps in the list (empty names)
    all give None instead of an IndexError or a wrong option.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if 0 <= value < len(options):
        return options[value] or None
    return None


def rewrite_unique_id(unique_id: str, old_serial: Any, new_serial: Any) -> str:
    """Swap the serial number at the start of an entity's unique id.

    Unique ids look like "<serial>_<Key>". Only that leading part is replaced; the
    earlier str.replace() also changed matching digits inside the key (with an old
    serial of 0, "0_raw_20006" lost every 0).
    """
    prefix = f"{old_serial}_"
    if unique_id.startswith(prefix):
        return f"{new_serial}_{unique_id[len(prefix) :]}"
    return unique_id


def redact_registers(registers: Mapping[int, int], addresses: Iterable[int] = SERIAL_NUMBER_REGISTERS) -> dict:
    """Return a copy of the raw register map with the serial number registers hidden."""
    hidden = set(addresses)
    return {address: (REDACTED if address in hidden else value) for address, value in registers.items()}


def is_serial_number_unique_id(unique_id: Any) -> bool:
    """Tell whether an entity with this unique id shows the serial number (or part of it)."""
    return isinstance(unique_id, str) and unique_id.endswith(SERIAL_NUMBER_UNIQUE_ID_ENDINGS)
