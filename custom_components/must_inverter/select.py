import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import callback
from homeassistant.const import EntityCategory, Platform

from .const import DOMAIN, OPTIONS, Sensor
from .__init__ import MustInverter
from .safeguards import option_for_value

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    inverter_data = hass.data[DOMAIN][entry.entry_id]
    inverter = inverter_data["inverter"]
    sensors = inverter_data["sensors"]
    entities = []

    for sensor_info in sensors:
        if sensor_info.platform == Platform.SELECT:
            sensor = MustInverterSelect(inverter, sensor_info)
            entities.append(sensor)

    async_add_entities(entities)
    return True


class MustInverterSelect(SelectEntity):
    def __init__(self, inverter: MustInverter, sensor_info: Sensor):
        """Initialize the sensor."""
        self._inverter = inverter
        self._key = sensor_info.name
        self._options = OPTIONS.get(self._key)
        self._address = sensor_info.address

        self._attr_has_entity_name = True
        self._attr_entity_category = EntityCategory.CONFIG  # EXTENDED 1.1.0: a setting
        self._attr_unique_id = f"{self._inverter.data['InverterSerialNumber']}_{self._key}"
        self._attr_translation_key = self._key.lower()
        self._attr_entity_registry_enabled_default = sensor_info.enabled
        self._attr_options = list(filter(len, self._options))
        self._unmapped_logged = set()

    async def async_added_to_hass(self):
        self._inverter.async_add_must_inverter_sensor(self._inverter_data_updated)

    async def async_will_remove_from_hass(self) -> None:
        self._inverter.async_remove_must_inverter_sensor(self._inverter_data_updated)

    @callback
    def _inverter_data_updated(self):
        self.async_write_ha_state()

    @property
    def current_option(self):
        if self._key in self._inverter.data:
            # EXTENDED 1.0.4: a value without an option name (outside the list, negative,
            # or a gap in the list) is reported as unknown instead of raising IndexError
            # on every poll or picking a wrong option - same as the enum sensors.
            value = self._inverter.data[self._key]
            option = option_for_value(self._options, value)
            if option is None and value not in self._unmapped_logged:
                self._unmapped_logged.add(value)
                _LOGGER.warning("%s: undocumented value %s, reporting as unknown", self._key, value)
            return option

    async def async_select_option(self, option: str) -> None:
        value = self._options.index(option)
        await self._inverter.write_modbus_data(self._address, int(value))
        if self._key in self._inverter.data:
            self._inverter.data[self._key] = value  # optmiistic update

    @property
    def device_info(self) -> dict[str, Any] | None:
        return self._inverter._device_info()

    @property
    def available(self) -> bool:
        # EXTENDED 1.1.0: not available either when the value has become too old
        return self._inverter.has_fresh(self._key)
