"""The darkness set on the printer, coarsely, from the state it told last."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    add([Darkness(entry)])


class Darkness(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "darkness_level"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry.runtime_data.coordinator)
        self._attr_unique_id = f"{entry.unique_id}_darkness_level"
        self._attr_device_info = dr.DeviceInfo(connections={(dr.CONNECTION_BLUETOOTH, entry.unique_id)})

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data["darkness_level"] if self.coordinator.data else None
