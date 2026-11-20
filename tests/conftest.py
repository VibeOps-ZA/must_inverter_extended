"""Test setup: run the tests without Home Assistant, pymodbus or an inverter.

The decoding and safety logic of the integration is plain Python, but the files import
Home Assistant and pymodbus. When those are not installed, tiny stand-ins are registered
here before the integration is imported - just enough for the imports to succeed. The
tests never open a serial port or a network connection.

Run from the repository root with:  python3 -m pytest
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import pathlib
import sys
import types

import pytest

TESTS_DIR = pathlib.Path(__file__).resolve().parent
# MUST_INVERTER_REPO_ROOT lets the same tests run against another copy of the code
# (for example an older release) to compare results.
REPO_ROOT = pathlib.Path(os.environ.get("MUST_INVERTER_REPO_ROOT", TESTS_DIR.parent)).resolve()
COMPONENT_DIR = REPO_ROOT / "custom_components" / "must_inverter"
PACKAGE = "custom_components.must_inverter"


def _is_installed(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _module(name: str, **attributes) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__dict__.update(attributes)
    sys.modules[name] = module
    parent, _, child = name.rpartition(".")
    if parent:
        setattr(sys.modules[parent], child, module)
    return module


class _LowerCaseNames(type):
    """Class whose attributes are their own name in lower case (Platform.SENSOR == "sensor")."""

    def __getattr__(cls, name: str) -> str:
        if name.startswith("_"):
            raise AttributeError(name)
        return name.lower()


class _Names(metaclass=_LowerCaseNames):
    """Stand-in for Home Assistant's string enums (Platform, SensorDeviceClass ...)."""


class _HomeAssistantError(Exception):
    pass


class _StubModbusClient:
    """Stand-in for the pymodbus clients; the tests replace it with their own fake."""

    def __init__(self, *args, **kwargs) -> None:
        self.connected = False
        self.comm_params = types.SimpleNamespace(host=args[0] if args else None, port=kwargs.get("port"))

    def close(self) -> None:
        self.connected = False


def _install_home_assistant_stand_ins() -> None:
    _module("homeassistant")
    _module(
        "homeassistant.const",
        Platform=_Names,
        EntityCategory=_Names,
        EVENT_HOMEASSISTANT_STOP="homeassistant_stop",
        CONF_NAME="name",
        CONF_DEVICE="device",
        CONF_MODEL="model",
        CONF_SCAN_INTERVAL="scan_interval",
        CONF_MODE="mode",
        CONF_HOST="host",
        CONF_PORT="port",
        CONF_TIMEOUT="timeout",
    )
    _module("homeassistant.core", HomeAssistant=type("HomeAssistant", (), {}), callback=lambda function: function)
    _module(
        "homeassistant.exceptions",
        HomeAssistantError=_HomeAssistantError,
        ConfigEntryNotReady=type("ConfigEntryNotReady", (_HomeAssistantError,), {}),
        PlatformNotReady=type("PlatformNotReady", (_HomeAssistantError,), {}),
    )
    _module("homeassistant.config_entries", ConfigEntry=type("ConfigEntry", (), {}))
    _module("homeassistant.helpers")
    _module("homeassistant.helpers.config_validation", config_entry_only_config_schema=lambda domain: domain)
    _module(
        "homeassistant.helpers.issue_registry",
        IssueSeverity=_Names,
        async_create_issue=lambda *args, **kwargs: None,
        async_delete_issue=lambda *args, **kwargs: None,
    )
    _module("homeassistant.helpers.event", async_track_time_interval=lambda *args, **kwargs: lambda: None)
    _module("homeassistant.components")
    _module("homeassistant.components.binary_sensor", BinarySensorDeviceClass=_Names)
    _module("homeassistant.components.number", NumberDeviceClass=_Names)
    _module("homeassistant.components.sensor", SensorDeviceClass=_Names)


def _install_pymodbus_stand_ins() -> None:
    _module("pymodbus")
    _module(
        "pymodbus.client",
        AsyncModbusSerialClient=_StubModbusClient,
        AsyncModbusTcpClient=_StubModbusClient,
        AsyncModbusUdpClient=_StubModbusClient,
    )


if not _is_installed("homeassistant"):
    _install_home_assistant_stand_ins()
if not _is_installed("pymodbus"):
    _install_pymodbus_stand_ins()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class FakeResponse:
    """What a pymodbus read or write returns, reduced to what the integration uses."""

    def __init__(self, registers=None, error: bool = False, retries: int = 0) -> None:
        self.registers = list(registers or [])
        self.retries = retries
        self._error = error

    def isError(self) -> bool:  # noqa: N802 - pymodbus spelling
        return self._error

    def __repr__(self) -> str:
        """Show what kind of answer this is in test failures."""
        return "FakeResponse(error)" if self._error else f"FakeResponse({len(self.registers)} registers)"


class FakeClient:
    """An inverter on the other end of the cable, scripted per start address.

    answers[address] may be a list of register values, a FakeResponse, an Exception to
    raise, or a function(address, count). No entry means the inverter answers with a
    Modbus error.
    """

    def __init__(self) -> None:
        self.connected = True
        self.comm_params = types.SimpleNamespace(host="test", port=0)
        self.answers: dict = {}
        self.reads: list = []
        self.writes: list = []
        self.refuse_writes = False

    async def connect(self) -> bool:
        self.connected = True
        return True

    def close(self) -> None:
        self.connected = False

    async def read_holding_registers(self, address, count, device_id):
        self.reads.append((address, count))
        answer = self.answers.get(address)
        if callable(answer):
            answer = answer(address, count)
        if answer is None:
            return FakeResponse(error=True)
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, FakeResponse):
            return answer
        return FakeResponse(answer)

    async def write_register(self, address, value, device_id):
        self.writes.append((address, value))
        return FakeResponse(error=self.refuse_writes)


def flatten(blocks: dict) -> dict:
    """Turn {"start": [values]} into {address: value}."""
    registers = {}
    for start, values in blocks.items():
        for offset, value in enumerate(values):
            registers[int(start) + offset] = value
    return registers


@pytest.fixture
def frame() -> dict:
    """Return the recorded poll of a PV18-4024PREM as {"start": [values]} (a fresh copy)."""
    with open(TESTS_DIR / "fixtures" / "pv18_4024prem_frame.json") as handle:
        return json.load(handle)["blocks"]


@pytest.fixture
def registers(frame) -> dict:
    """Return the recorded poll as {address: value}."""
    return flatten(frame)


@pytest.fixture
def must():
    """Return the integration package (custom_components.must_inverter)."""
    return importlib.import_module(PACKAGE)


@pytest.fixture
def mapper():
    return importlib.import_module(f"{PACKAGE}.mapper")


@pytest.fixture
def const():
    return importlib.import_module(f"{PACKAGE}.const")


@pytest.fixture
def safeguards():
    return importlib.import_module(f"{PACKAGE}.safeguards")


@pytest.fixture
def issues(must, monkeypatch) -> list:
    """Collect the repair issues the integration raises or clears, as (action, issue id)."""
    seen: list = []
    monkeypatch.setattr(
        must.ir, "async_create_issue", lambda hass, domain, issue_id, **kwargs: seen.append(("create", issue_id))
    )
    monkeypatch.setattr(must.ir, "async_delete_issue", lambda hass, domain, issue_id: seen.append(("delete", issue_id)))
    return seen


@pytest.fixture
def make_inverter(must, frame, issues, monkeypatch):
    """Build a MustInverter that talks to a FakeClient holding the recorded frame."""
    # no real waiting in tests
    monkeypatch.setattr(must, "QUIET_AFTER_DESYNC_S", 0, raising=False)

    def build(model: str = "pv1800", **options):
        entry = types.SimpleNamespace(
            entry_id="test-entry",
            options={
                "mode": "serial",
                "device": "/dev/null",
                "baudrate": 19200,
                "stopbits": 1,
                "bytesize": 8,
                "parity": "N",
                "timeout": 2.0,
                "retries": 3,
                "reconnect_delay": 0.3,
                "reconnect_delay_max": 1.0,
                "device_id": 4,
                "scan_interval": 15,
                "model": model,
                **options,
            },
        )
        inverter = must.MustInverter(object(), entry)
        client = FakeClient()
        client.answers = {int(start): list(values) for start, values in frame.items()}
        inverter._client = client
        return inverter, client

    return build
