import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory, Platform, UnitOfEnergy
from homeassistant.core import callback

from .const import DOMAIN, OPTIONS, Sensor
from .__init__ import MustInverter

_LOGGER = logging.getLogger(__name__)

# LOCAL PATCH (2026-10-07): registers that are ALREADY read every poll (inside the
# existing 15201-15221 / 20000-20016 / 25201-25279 ranges) but not decoded by the
# integration. Exposed raw as diagnostic sensors to work out what they mean.
# No extra Modbus reads are made for these.
# LOCAL PATCH (2026-10-08): added 15202 (MPPT state), 15203 (ChargingState, raw so
# undocumented values 5/8 are recorded) and 25273 (toggles 0/5 with the charger).
RAW_REGISTERS = (
    15202, 15203, 15204, 15218,  # LOCAL PATCH 6: 15218 (unknown, tracks inverter output)
    20117,  # LOCAL PATCH 6: low-battery warning voltage (= 20118 - 0.3 V)
    20006, 20007, 20008,
    25204, 25220, 25224, 25227, 25228, 25232, 25236, 25243, 25244,
    25269, 25270, 25271, 25272, 25273, 25275, 25276, 25278, 25279,
)


async def async_setup_entry(hass, entry, async_add_entities):
    inverter_data = hass.data[DOMAIN][entry.entry_id]
    inverter = inverter_data["inverter"]
    sensors = inverter_data["sensors"]
    entities = []

    for sensor_info in sensors:
        if sensor_info.platform == Platform.SENSOR:
            sensor = MustInverterSensor(inverter, sensor_info)
            entities.append(sensor)

    entities.extend(MustRawRegisterSensor(inverter, address) for address in RAW_REGISTERS)

    async_add_entities(entities)
    return True


class MustRawRegisterSensor(SensorEntity):
    """LOCAL PATCH (2026-10-07): raw value of an already-read, undecoded register."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, inverter: MustInverter, address: int):
        self._inverter = inverter
        self._address = address
        self._attr_unique_id = f"{self._inverter.data['InverterSerialNumber']}_raw_{address}"
        self._attr_name = f"Raw register {address}"

    async def async_added_to_hass(self):
        self._inverter.async_add_must_inverter_sensor(self._inverter_data_updated)

    async def async_will_remove_from_hass(self) -> None:
        self._inverter.async_remove_must_inverter_sensor(self._inverter_data_updated)

    @callback
    def _inverter_data_updated(self):
        self.async_write_ha_state()

    @property
    def native_value(self):
        value = self._inverter.registers.get(self._address)
        if value is None:
            return None
        return value - 0x10000 if value & 0x8000 else value

    @property
    def available(self) -> bool:
        return self._address in self._inverter.registers

    @property
    def device_info(self) -> dict[str, Any] | None:
        return self._inverter._device_info()


class MustInverterSensor(SensorEntity):
    def __init__(self, inverter: MustInverter, sensor_info: Sensor):
        """Initialize the sensor."""
        self._inverter = inverter
        self._key = sensor_info.name
        self._coeff = sensor_info.coeff or 1
        self._unmapped_logged = set()

        self._attr_has_entity_name = True
        self._attr_unique_id = f"{self._inverter.data['InverterSerialNumber']}_{self._key}"
        self._attr_translation_key = self._key.lower()
        self._attr_native_unit_of_measurement = sensor_info.unit
        self._attr_device_class = sensor_info.device_class
        self._attr_entity_registry_enabled_default = sensor_info.enabled
        self._attr_options = OPTIONS.get(self._key)

        if self._attr_native_unit_of_measurement == UnitOfEnergy.KILO_WATT_HOUR:
            self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        elif self._attr_options is None:
            self._attr_state_class = SensorStateClass.MEASUREMENT

    async def async_added_to_hass(self):
        self._inverter.async_add_must_inverter_sensor(self._inverter_data_updated)

    async def async_will_remove_from_hass(self) -> None:
        self._inverter.async_remove_must_inverter_sensor(self._inverter_data_updated)

    @callback
    def _inverter_data_updated(self):
        self.async_write_ha_state()

    @property
    def state(self):
        if self._key in self._inverter.data:
            value = self._inverter.data[self._key]
            if self._attr_options is not None:
                # LOCAL PATCH (2026-10-06): registers can report values that are not
                # documented in the Must protocol (e.g. ChargingState 15203 = 5).
                # Report them as unknown instead of raising IndexError every poll.
                if isinstance(value, int) and 0 <= value < len(self._attr_options):
                    return self._attr_options[value]
                if value not in self._unmapped_logged:
                    self._unmapped_logged.add(value)
                    _LOGGER.warning("%s: undocumented value %s, reporting as unknown", self._key, value)
                return None
            return value * self._coeff

    @property
    def device_info(self) -> dict[str, Any] | None:
        return self._inverter._device_info()

    @property
    def available(self) -> dict[str, Any] | None:
        return self._key in self._inverter.data
