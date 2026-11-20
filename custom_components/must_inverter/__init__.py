import asyncio
# Aliased: HA sets this package's "time" attribute to the time.py platform once it
# loads, which would shadow a plain "import time" (AttributeError on time.monotonic).
import time as _stdlib_time
from collections import deque
import logging
import contextlib

from datetime import timedelta

from homeassistant.helpers import config_validation as cv
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_interval
from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient, AsyncModbusUdpClient

from homeassistant.const import (
    CONF_NAME,
    CONF_DEVICE,
    CONF_MODEL,
    CONF_SCAN_INTERVAL,
    CONF_MODE,
    CONF_HOST,
    CONF_PORT,
    CONF_TIMEOUT,
)

from .const import (
    DOMAIN,
    CONF_BAUDRATE,
    CONF_PARITY,
    CONF_STOPBITS,
    CONF_BYTESIZE,
    CONF_RETRIES,
    CONF_RECONNECT_DELAY,
    CONF_RECONNECT_DELAY_MAX,
    CONF_DEVICE_ID,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_DEVICE_ID,
    get_sensors_for_model,
    MODEL_PV1900,
    MODEL_PH1100,
)

from .mapper import (
    convert_ph1100_partArr1,
    convert_ph1100_partArr2,
    convert_ph1100_partArr3,
    convert_ph1100_partArr4,
    convert_partArr2,
    convert_partArr3,
    convert_partArr3_with_pv1,
    convert_partArr4,
    convert_partArr5,
    convert_partArr6,
    convert_battery_status,
    convert_pv_data,
)
from .safeguards import block_reject_reason, serial_number_changed
# from .utils.register_monitor import RegisterMonitor

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.BUTTON,
    Platform.TIME,
]
_LOGGER = logging.getLogger(__name__)

# EXTENDED 1.0.1: only flag persistent register mismatches (one-offs happen around restarts)
STARTUP_GRACE_S = 120
MISMATCH_WINDOW_S = 600
MISMATCH_COUNT = 3
CLEAR_AFTER_GOOD_READS = 10
# EXTENDED 1.0.4: pause after a reply that does not belong to its request (or that only
# came after a retry). The reply that is still on its way then arrives while nothing is
# waiting for it and is thrown away, instead of being taken as the answer to the next
# request - which shifted every later reply of that poll by one.
QUIET_AFTER_DESYNC_S = 1.0
# EXTENDED 1.0.4: a scan interval of 0 (or less) would poll without a pause.
MIN_SCAN_INTERVAL_S = 1.0
MISMATCH_LEARN_MORE_URL = (
    "https://github.com/VibeOps-ZA/must_inverter_extended#repair-mismatched-modbus-registers"
)

# EXTENDED: config-entry only (silences the hassfest CONFIG_SCHEMA warning).
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# LOCAL PATCH (2026-10-07): battery SoC/SoH keys served at registers 113-114.
BATTERY_STATUS_KEYS = ("StateOfCharge", "BatteryStateOfHealth")
# EXTENDED: give up on 113-114 after this many failed reads in a row (no BMS link).
BMS_MAX_FAILURES = 3


async def async_setup(hass, config):
    hass.data[DOMAIN] = {}
    return True  # Return boolean to indicate that initialization was successful.


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the must inverter component."""
    # EXTENDED 1.0.1: a mismatch repair from before a restart is stale - start clean
    ir.async_delete_issue(hass, DOMAIN, "mismatched_registers")
    try:
        entry.async_on_unload(entry.add_update_listener(async_reload_entry))

        # Initialize inverter with model-specific sensors
        inverter = MustInverter(hass, entry)

        try:
            return await _async_setup_inverter(hass, entry, inverter)
        except BaseException:
            # EXTENDED (upstream PR #117): a failed setup must never leave the serial
            # port open - the leaked client keeps the exclusive port lock, so every
            # retry fails with "Could not exclusively lock port" until HA restarts.
            inverter.close()
            hass.data[DOMAIN].pop(entry.entry_id, None)
            raise
    except ConfigEntryNotReady as ex:
        raise ex
    except Exception as ex:
        _LOGGER.exception("Error setting up modbus device", exc_info=True)
        raise ConfigEntryNotReady("Unknown error connecting to modbus device") from ex


async def _async_setup_inverter(hass: HomeAssistant, entry: ConfigEntry, inverter) -> bool:
    """Connect, read once and forward platforms (body of the original setup)."""
    successConnecting = await inverter.connect()

    if not successConnecting:
        raise ConfigEntryNotReady("Unable to connect to modbus device")

    successReading = await inverter._async_refresh_modbus_data()

    if not successReading:
        raise ConfigEntryNotReady("Unable to read from modbus device")

    model = inverter.model
    sensors = get_sensors_for_model(model)

    # LOCAL PATCH (2026-10-07): a PV1800 (PV18-4024PREM, fw 2.35.16) with a
    # CAN-connected lithium BMS also serves battery SoC/SoH at registers 113-114
    # (verified by a one-off read: [22, 100] with the battery at 22%).
    # Reuse the PV1900 sensor definitions for those two keys.
    if model not in (MODEL_PV1900, MODEL_PH1100):
        have = {s.name for s in sensors}
        sensors = list(sensors) + [
            s
            for s in get_sensors_for_model(MODEL_PV1900)
            if s.name in BATTERY_STATUS_KEYS and s.name not in have
        ]

    _LOGGER.debug("Setting up Must Inverter with model: %s", model)

    # Store sensors to be used by platforms
    hass.data[DOMAIN][entry.entry_id] = {"inverter": inverter, "sensors": sensors}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # EXTENDED 1.0.3: stop polling as soon as Home Assistant starts shutting down.
    # Polls that kept running during shutdown failed ("error reading modbus data")
    # and left a read task HA could not cancel. Writes (e.g. an automation that
    # writes a safe value on shutdown) still work.
    @callback
    def _async_on_ha_stop(_event):
        inverter.async_stop_polling()

    entry.async_on_unload(hass.bus.async_listen(EVENT_HOMEASSISTANT_STOP, _async_on_ha_stop))

    # Removing register monitor as we've found all needed registers
    # If you need to add it back, uncomment the following lines and set the ranges to scan in register_monitor.py
    # monitor = RegisterMonitor(hass)

    # Add monitoring to the update cycle, but at a slower rate
    # async def delayed_monitor():
    #     """Run monitor at a slower rate to avoid overwhelming the device."""
    #     try:
    #         while True:
    #             await monitor.scan_ranges(inverter)
    #             await asyncio.sleep(300)  # Run every 5 minutes
    #     except asyncio.CancelledError:
    #         _LOGGER.debug("Register monitor task cancelled")
    #         raise

    # monitor_task = asyncio.create_task(delayed_monitor())

    # Store the task so we can cancel it later
    # hass.data[DOMAIN][entry.entry_id]["monitor_task"] = monitor_task

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Cancel the monitor task
        if monitor_task := hass.data[DOMAIN][entry.entry_id].get("monitor_task"):
            monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await monitor_task

        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update listener, called when the config entry options are changed."""
    await hass.config_entries.async_reload(entry.entry_id)


class MustInverter:
    def __init__(self, hass, entry: ConfigEntry):
        self._hass = hass
        self._callbacks = []  # Store callbacks separately
        self._unsub_interval_method = None
        self._stopping = False  # EXTENDED 1.0.3: set when Home Assistant is shutting down
        self._entry = entry
        # Check both data and options

        common = {
            "timeout": entry.options[CONF_TIMEOUT],
            "retries": entry.options[CONF_RETRIES],
            "reconnect_delay": entry.options[CONF_RECONNECT_DELAY],
            "reconnect_delay_max": entry.options[CONF_RECONNECT_DELAY_MAX],
        }

        match entry.options[CONF_MODE]:
            case "serial":
                self._client = AsyncModbusSerialClient(
                    entry.options[CONF_DEVICE],
                    baudrate=entry.options[CONF_BAUDRATE],
                    stopbits=entry.options[CONF_STOPBITS],
                    bytesize=entry.options[CONF_BYTESIZE],
                    parity=entry.options[CONF_PARITY],
                    **common,
                )
            case "tcp":
                self._client = AsyncModbusTcpClient(entry.options[CONF_HOST], port=entry.options[CONF_PORT], **common)
            case "udp":
                self._client = AsyncModbusUdpClient(entry.options[CONF_HOST], port=entry.options[CONF_PORT], **common)
            case _:
                raise Exception("Invalid mode")

        self._client.rts = False
        self._client.dtr = False
        self._lock = asyncio.Lock()
        self._device_id = entry.options.get(CONF_DEVICE_ID, DEFAULT_DEVICE_ID)
        self._scan_interval = timedelta(
            seconds=max(MIN_SCAN_INTERVAL_S, float(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)))
        )
        self._reading = False
        self._bms_failures = 0
        # EXTENDED 1.0.1: mismatched-register handling (see _note_mismatch)
        self._started = _stdlib_time.monotonic()
        self._mismatches = deque()
        self._good_reads = 0
        self._issue_raised = False
        self._needs_flush = True
        # EXTENDED 1.0.4: implausible-answer handling (see _accept_block)
        self._known_serial = None
        self._implausible = set()
        self.registers = {}
        self.data = {}

    @callback
    def async_add_must_inverter_sensor(self, update_callback):
        # This is the first sensor, set up interval.
        if not self._callbacks:
            self._unsub_interval_method = async_track_time_interval(
                self._hass, self._async_refresh_modbus_data, self._scan_interval
            )

        self._callbacks.append(update_callback)

    @callback
    def async_remove_must_inverter_sensor(self, update_callback):
        self._callbacks.remove(update_callback)

        if not self._callbacks:
            """stop the interval timer upon removal of last sensor"""
            if self._unsub_interval_method:
                self._unsub_interval_method()
                self._unsub_interval_method = None
            self.close()

    @callback
    def async_stop_polling(self):
        """Stop the poll timer because Home Assistant is shutting down (EXTENDED 1.0.3)."""
        if self._stopping:
            return
        self._stopping = True
        if self._unsub_interval_method:
            self._unsub_interval_method()
            self._unsub_interval_method = None
        _LOGGER.debug("Home Assistant is stopping - inverter polling stopped")

    async def _async_refresh_modbus_data(self, now=None):
        if self._stopping:
            return False

        if not await self._check_and_reopen():
            # if not connected, skip
            _LOGGER.warning("not connected, skipping refresh")
            return False

        try:
            update_result = await self.read_modbus_data()

            if update_result:
                for update_callback in self._callbacks:
                    update_callback()
        except Exception:
            _LOGGER.exception("error reading inverter data", exc_info=True)
            update_result = False

        return update_result

    @property
    def name(self):
        return self._entry.options.get(CONF_NAME, self.data.get("InverterMachineType", self.model))

    @property
    def model(self):
        from_config = self._entry.options.get(CONF_MODEL)
        detected = self.data.get("InverterMachineType")

        if from_config == "autodetect":
            return detected

        return from_config or detected

    @property
    def has_extra_registers(self):
        return self.model == MODEL_PV1900

    def _note_bms_failure(self, response):
        """Count failed BMS (113-114) reads and stop asking after a few (EXTENDED)."""
        self._bms_failures += 1
        if self._bms_failures >= BMS_MAX_FAILURES:
            _LOGGER.warning(
                "battery SoC/SoH registers 113-114 failed %s times in a row (%s) - this inverter "
                "probably has no BMS link; not reading them again until Home Assistant restarts",
                self._bms_failures,
                response,
            )
        else:
            _LOGGER.debug("battery SoC/SoH read failed (%s/%s): %s", self._bms_failures, BMS_MAX_FAILURES, response)

    def _flush_input(self):
        """Drop stale bytes from the serial receive buffer (EXTENDED 1.0.1).

        A reply that arrives after its request timed out (Home Assistant busy, e.g. while
        starting or stopping) would otherwise be taken as the answer to the next request,
        giving a 'wrong number of registers' read. Serial mode only; no-op for TCP/UDP.
        """
        try:
            transport = getattr(getattr(self._client, "ctx", None), "transport", None)
            ser = getattr(transport, "sync_serial", None)
            if ser is not None:
                ser.reset_input_buffer()
                _LOGGER.debug("serial input buffer flushed")
        except Exception:  # noqa: BLE001
            _LOGGER.debug("could not flush the serial input buffer", exc_info=True)

    def _note_mismatch(self, count_it=True):
        """Raise the repair only for a persistent problem (EXTENDED 1.0.1).

        Single mismatches right after a restart are expected and harmless. The repair is
        raised after MISMATCH_COUNT mismatches within MISMATCH_WINDOW_S, ignoring the
        first STARTUP_GRACE_S after start, and cleared after CLEAR_AFTER_GOOD_READS good reads.

        EXTENDED 1.0.4: count_it is False for the second and later mismatches of the same
        poll. One late reply shifts every following reply of that poll, so it used to count
        as several mismatches and could raise the repair on its own.
        """
        now = _stdlib_time.monotonic()
        self._good_reads = 0
        self._needs_flush = True
        if not count_it:
            return
        self._mismatches.append(now)
        while self._mismatches and now - self._mismatches[0] > MISMATCH_WINDOW_S:
            self._mismatches.popleft()
        if (
            not self._issue_raised
            and now - self._started > STARTUP_GRACE_S
            and len(self._mismatches) >= MISMATCH_COUNT
        ):
            self._issue_raised = True
            ir.async_create_issue(
                self._hass,
                DOMAIN,
                "mismatched_registers",
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="mismatched_registers",
                is_persistent=False,
                learn_more_url=MISMATCH_LEARN_MORE_URL,
            )

    def _note_good_read(self):
        self._good_reads += 1
        if self._issue_raised and self._good_reads >= CLEAR_AFTER_GOOD_READS:
            self._issue_raised = False
            self._mismatches.clear()
            ir.async_delete_issue(self._hass, DOMAIN, "mismatched_registers")
            _LOGGER.info("reads are consistent again - mismatched registers repair cleared")

    async def _quiet_wait(self):
        """Wait until a late reply has arrived and been thrown away (EXTENDED 1.0.4).

        The lock is held so that no write is sent in the meantime either. Skipped while
        Home Assistant is shutting down.
        """
        if self._stopping:
            return
        async with self._lock:
            await asyncio.sleep(QUIET_AFTER_DESYNC_S)
        self._needs_flush = True

    def forget_known_serial(self):
        """Accept a new serial number on the next read (used after the repair wrote one)."""
        self._known_serial = None

    def _accept_block(self, start, values, convert, read):
        """Check one register block and, if it is believable, take it over (EXTENDED 1.0.4).

        Returns False - and leaves all earlier values untouched - when the block cannot be
        real: every register 0 or 65535 in a block that always holds fixed non-zero values,
        or a serial number different from the one read earlier. A Must inverter that has
        shut itself down answers every register with 0; taken as real, that gave the
        entities new ids (serial number 0) when Home Assistant started in that state, and
        made Home Assistant count the lifetime energy totals a second time.
        """
        reason = block_reject_reason(start, values)
        block = {start + i: value for i, value in enumerate(values)}
        decoded = None

        if reason is None:
            candidate = dict(read)
            candidate.update(block)
            decoded = convert(candidate)
            serial = decoded.get("InverterSerialNumber") if decoded else None
            if serial_number_changed(self._known_serial, serial):
                reason = "the serial number differs from the one read earlier"
            elif serial is not None:
                self._known_serial = serial

        if reason is not None:
            self._needs_flush = True
            if start not in self._implausible:
                self._implausible.add(start)
                _LOGGER.warning(
                    "ignoring an implausible answer at address %s (%s) - keeping the previous values. "
                    "If this stays, the inverter may have shut itself down and need a full power cycle",
                    start,
                    reason,
                )
            else:
                _LOGGER.debug("still an implausible answer at address %s (%s)", start, reason)
            return False

        if start in self._implausible:
            self._implausible.discard(start)
            _LOGGER.info("answers at address %s are plausible again", start)
        read.update(block)
        if decoded:
            self.data.update(decoded)
        return True

    def close(self):
        _LOGGER.info("closing modbus client")
        self._client.close()

    async def _check_and_reopen(self):
        if not self._client.connected:
            _LOGGER.info("modbus client is not connected, trying to reconnect")
            return await self.connect()

        return self._client.connected

    async def connect(self):
        result = False

        _LOGGER.debug("connecting to %s:%s", self._client.comm_params.host, self._client.comm_params.port)

        async with self._lock:
            result = await self._client.connect()

        if result:
            self._flush_input()
            _LOGGER.info(
                "successfully connected to %s:%s", self._client.comm_params.host, self._client.comm_params.port
            )
        else:
            _LOGGER.warning(
                "not able to connect to %s:%s", self._client.comm_params.host, self._client.comm_params.port
            )
        return result

    async def write_modbus_data(self, address, value):
        await self._check_and_reopen()

        _LOGGER.debug("writing modbus data: %s %s", address, value)
        async with self._lock:
            response = await self._client.write_register(address=address, value=value, device_id=self._device_id)

        if response.isError():
            _LOGGER.error("error writing modbus data: %s", response)
            # EXTENDED 1.0.4: tell the caller. Before, a write the inverter refused looked
            # like a success: the entity showed the new value until the next poll and
            # automations carried on as if the setting had changed.
            raise HomeAssistantError(f"The inverter refused to write {value} to register {address}: {response}")
        else:
            _LOGGER.debug("successfully wrote modbus data: %s %s", address, value)

        # await self._async_refresh_modbus_data()
        return response

    async def read_modbus_data(self):
        _LOGGER.debug("reading modbus data")

        if self._reading:
            _LOGGER.warning(
                "skipping reading modbus data, previous read still in progress, make sure your scan interval is not too low"
            )
            return False
        self._reading = True
        try:
            return await self._read_modbus_data_locked()
        finally:
            # EXTENDED: always clear the flag. Upstream left it set when a read was
            # cancelled or raised, so every later poll was skipped ("previous read
            # still in progress") until Home Assistant was restarted.
            self._reading = False

    async def _read_modbus_data_locked(self):

        # Reading all the control messages at once (ranges 20016-20100 and/or
        # 10009-10100 are problematic) causes the inverter to shut down
        # immediately and the charger stops working afterwards (all registers
        # return zeroes). Requires the grid/batteries/PV to be disconnected and
        # the inverter restarted for it to come back online.
        if self.model == MODEL_PH1100:
            registersAddresses = [
                (10102, 10119, convert_ph1100_partArr1),  # Charger Control Messages
                (15104, 15119, convert_ph1100_partArr2),  # Charger Display Messages
                (20001, 20003, convert_ph1100_partArr3),  # Inverter Control Messages
                (25225, 25339, convert_ph1100_partArr4),  # Inverter Display Messages
            ]
        else:
            # Base register ranges for all models
            registersAddresses = [
                # (10000, 10008, convert_partArr1), # Charger Control Messages
                (10101, 10124, convert_partArr2),  # Charger Control Messages
                # EXTENDED 1.0.4: on a PV1900 this block also gives the PV1 values (see below)
                (15201, 15221, convert_partArr3_with_pv1 if self.has_extra_registers else convert_partArr3),
                (20000, 20016, convert_partArr4),  # Inverter Control Messages
                (20101, 20214, convert_partArr5),  # Inverter Control Messages
                (25201, 25279, convert_partArr6),  # Inverter Display Messages
            ]

            # Add PV19-specific register ranges if needed
            # Keep register ranges for pv separate to not overload the inverter
            if self.has_extra_registers:
                registersAddresses.extend(
                    [
                        (113, 114, convert_battery_status),  # Battery Status (SoC, SoH)
                        # EXTENDED 1.0.4: 15207-15208 (PV1 current, power) is no longer read a
                        # second time - it is part of 15201-15221 above. Being a 2-register
                        # read like 113-114, a late reply to one could pass as the other.
                        (16205, 16208, convert_pv_data),  # PV2 Data (Voltage, Current, Power)
                    ]
                )
            elif self._bms_failures < BMS_MAX_FAILURES:
                # LOCAL PATCH (2026-10-07): battery SoC/SoH only (NOT the PV2 ranges)
                # for PV1800 units with a BMS; verified on PV18-4024PREM fw 2.35.16.
                # EXTENDED: inverters without a BMS link answer this with an error;
                # after BMS_MAX_FAILURES failed reads in a row it is skipped until the
                # next restart/reload, so they don't log an error every poll.
                registersAddresses.append((113, 114, convert_battery_status))

        read = {}
        mismatch_noted = False

        for register in registersAddresses:
            if self.has_extra_registers:
                # Add a small delay between reading standard and PV19-specific registers
                # to prevent any potential issues
                await asyncio.sleep(0.1)

            if self._stopping:
                # EXTENDED 1.0.3: Home Assistant is shutting down - don't start more reads
                break

            start = register[0]
            end = register[1]
            count = end - start + 1

            try:
                _LOGGER.debug("reading modbus data from %s to %s (%s)", start, end, count)

                if not await self._check_and_reopen():
                    break

                async with self._lock:
                    if self._needs_flush:
                        self._needs_flush = False
                        self._flush_input()
                    response = await self._client.read_holding_registers(
                        address=start, count=count, device_id=self._device_id
                    )
                if response.isError():
                    if start == 113 and not self.has_extra_registers:
                        self._note_bms_failure(response)
                    elif self._stopping:
                        _LOGGER.debug("read at address %s failed during shutdown: %s", start, response)
                    else:
                        _LOGGER.error("error reading modbus data at address %s: %s", start, response)
                    self._needs_flush = True
                elif len(response.registers) != count:
                    _LOGGER.warning(
                        "wrong number of registers read at address %s, expected %s, got %s - this usually is caused by concurrent access to modbus (usb/wifi/rs485), please remove other devices",
                        start,
                        count,
                        len(response.registers),
                    )
                    # Log the actual values received
                    _LOGGER.debug("Received registers (wrong): %s", response.registers)

                    # EXTENDED 1.0.4: count it once per poll, then let the late reply pass
                    self._note_mismatch(count_it=not mismatch_noted)
                    mismatch_noted = True
                    await self._quiet_wait()
                else:
                    if getattr(response, "retries", 0):
                        # EXTENDED 1.0.4: the request was sent more than once, so a second
                        # reply may still be on its way - don't let the next request get it
                        _LOGGER.debug("answer at address %s needed a retry, waiting for the line to go quiet", start)
                        await self._quiet_wait()
                    if self._accept_block(start, response.registers, register[2], read):
                        _LOGGER.debug("Correctly read %s registers from start %s", count, start)
                        self._note_good_read()
                        if start == 113:
                            self._bms_failures = 0
            except asyncio.exceptions.CancelledError:
                _LOGGER.warning("cancelled modbus read")
                raise
            except Exception:
                self._needs_flush = True
                if start == 113 and not self.has_extra_registers:
                    self._note_bms_failure("exception")
                elif self._stopping:
                    _LOGGER.debug("read at address %s failed during shutdown", start, exc_info=True)
                else:
                    _LOGGER.error("error reading modbus data at address %s", start, exc_info=True)

        _LOGGER.debug("finished reading modbus data, %s", read)
        self.registers = read
        # _LOGGER.debug("Data: %s", self.data)

        if "InverterSerialNumber" not in self.data:
            # EXTENDED (upstream PR #117): nothing could be read at all (e.g. the
            # inverter is powered off) - report failure instead of a KeyError.
            _LOGGER.warning("no data could be read from the inverter")
            return False

        if self.data["InverterSerialNumber"] == 0xFFFFFFFF or self.data["InverterSerialNumber"] == 0:
            ir.async_create_issue(
                self._hass,
                DOMAIN,
                "no_serial_number",
                is_fixable=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key="no_serial_number",
                data={"entry_id": self._entry.entry_id},
            )

        return True

    def _device_info(self):
        return {
            "identifiers": {(DOMAIN, self.data["InverterSerialNumber"])},
            "name": self.name,
            "manufacturer": "Must Solar",
            "model": self.data.get("InverterMachineType", self.model),
            "hw_version": self.data.get("InverterHardwareVersion"),
            "sw_version": self.data.get("InverterSoftwareVersion"),
            # EXTENDED: HA 2026.12 requires a string serial number (upstream issue #119).
            # The device identifier is left unchanged so existing devices/entities keep their ids.
            "serial_number": str(self.data["InverterSerialNumber"]),
        }
