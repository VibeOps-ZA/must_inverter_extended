import logging
from typing import Any

from homeassistant.components.number import NumberEntity
from homeassistant.core import callback
from homeassistant.const import EntityCategory, Platform
from homeassistant.exceptions import PlatformNotReady

from .const import DOMAIN, RANGES, Sensor
from .__init__ import MustInverter

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    inverter_data = hass.data[DOMAIN][entry.entry_id]
    inverter = inverter_data["inverter"]
    sensors = inverter_data["sensors"]
    entities = []

    for sensor_info in sensors:
        if sensor_info.platform == Platform.NUMBER:
            sensor = MustInverterNumber(inverter, sensor_info)
            entities.append(sensor)

    async_add_entities(entities)
    return True


class MustInverterNumber(NumberEntity):
    def __init__(self, inverter: MustInverter, sensor_info: Sensor):
        """Initialize the sensor."""
        self._inverter = inverter
        self._key = sensor_info.name
        self._address = sensor_info.address
        self._coeff = sensor_info.coeff or 1

        self._attr_has_entity_name = True
        self._attr_entity_category = EntityCategory.CONFIG  # EXTENDED 1.1.0: a setting
        self._attr_unique_id = f"{self._inverter.data['InverterSerialNumber']}_{self._key}"
        self._attr_translation_key = self._key.lower()
        self._attr_native_unit_of_measurement = sensor_info.unit
        self._attr_device_class = sensor_info.device_class
        self._attr_entity_registry_enabled_default = sensor_info.enabled

        if self._key in RANGES:
            # EXTENDED 1.0.4: the limits of several settings are worked out from values
            # read from the inverter (battery voltage class, rated current). If those have
            # not been read yet, ask Home Assistant to set the number entities up again a
            # little later instead of failing with a KeyError (no number entities at all
            # until a reload) or creating them with limits of 0.
            try:
                range = RANGES.get(self._key)(self._inverter.data)
            except (KeyError, TypeError, ZeroDivisionError) as err:
                raise PlatformNotReady(f"cannot work out the limits of {self._key} yet (missing {err})") from err
            if range.max <= 0:
                raise PlatformNotReady(f"limits of {self._key} are not usable yet ({range.min} to {range.max})")

            self._attr_native_min_value = range.min
            self._attr_native_max_value = range.max
            self._attr_native_step = range.step

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
            return self._inverter.data[self._key] * self._coeff

    async def async_set_native_value(self, value: float) -> None:
        integer = int(round(value / self._coeff))

        await self._inverter.write_modbus_data(self._address, integer)
        if self._key in self._inverter.data:
            self._inverter.data[self._key] = integer  # optmiistic update

    @property
    def device_info(self) -> dict[str, Any] | None:
        return self._inverter._device_info()

    @property
    def available(self) -> bool:
        # EXTENDED 1.1.0: not available either when the value has become too old
        return self._inverter.has_fresh(self._key)
