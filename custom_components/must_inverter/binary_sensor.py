import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import callback

from .const import DOMAIN, Sensor
from .__init__ import MustInverter

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    inverter_data = hass.data[DOMAIN][entry.entry_id]
    inverter = inverter_data["inverter"]
    sensors = inverter_data["sensors"]
    entities = []

    for sensor_info in sensors:
        if sensor_info.platform == Platform.BINARY_SENSOR:
            sensor = MustInverterBinarySensor(inverter, sensor_info)
            entities.append(sensor)

    # EXTENDED 1.1.0: one entity that says whether the inverter is answering at all
    entities.append(MustInverterConnectedSensor(inverter))

    async_add_entities(entities)
    return True


class MustInverterConnectedSensor(BinarySensorEntity):
    """EXTENDED 1.1.0: on while the inverter answers, off when it has stopped answering.

    Turns off after MAX_MISSED_POLLS polls in a row without any answer (75 seconds at the
    default scan interval) - at the same moment the other entities turn unavailable - and
    on again with the first answer. It is itself always available, which makes it the
    entity to build an "inverter offline" alert on.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, inverter: MustInverter):
        self._inverter = inverter
        self._attr_unique_id = f"{self._inverter.data['InverterSerialNumber']}_Connected"

    async def async_added_to_hass(self):
        self._inverter.async_add_must_inverter_sensor(self._inverter_data_updated)

    async def async_will_remove_from_hass(self) -> None:
        self._inverter.async_remove_must_inverter_sensor(self._inverter_data_updated)

    @callback
    def _inverter_data_updated(self):
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self._inverter.connected

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # counted up to the limit only, so a long outage does not write a new state every poll
        return {"missed_polls": self._inverter.missed_polls}

    @property
    def device_info(self) -> dict[str, Any] | None:
        return self._inverter._device_info()


class MustInverterBinarySensor(BinarySensorEntity):
    def __init__(self, inverter: MustInverter, sensor_info: Sensor):
        """Initialize the binary sensor."""
        self._inverter = inverter
        self._key = sensor_info.name

        self._attr_has_entity_name = True
        self._attr_unique_id = f"{self._inverter.data['InverterSerialNumber']}_{self._key}"
        self._attr_translation_key = self._key.lower()
        self._attr_device_class = sensor_info.device_class
        self._attr_entity_registry_enabled_default = sensor_info.enabled

    async def async_added_to_hass(self):
        self._inverter.async_add_must_inverter_sensor(self._inverter_data_updated)

    async def async_will_remove_from_hass(self) -> None:
        self._inverter.async_remove_must_inverter_sensor(self._inverter_data_updated)

    @callback
    def _inverter_data_updated(self):
        self.async_write_ha_state()

    @property
    def is_on(self):
        if self._key in self._inverter.data:
            return self._inverter.data[self._key] == 1

    @property
    def device_info(self) -> dict[str, Any] | None:
        return self._inverter._device_info()

    @property
    def available(self) -> bool:
        # EXTENDED 1.1.0: not available either when the value has become too old
        return self._inverter.has_fresh(self._key)
