"""Connectivity: whether Home Assistant hears the printer, from its Bluetooth
advertisements, without connecting to it."""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddEntitiesCallback


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    add([Connectivity(entry)])


class Connectivity(BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._address = entry.unique_id
        self._attr_unique_id = f"{entry.unique_id}_connectivity"
        self._attr_device_info = dr.DeviceInfo(connections={(dr.CONNECTION_BLUETOOTH, entry.unique_id)})

    async def async_added_to_hass(self) -> None:
        self._attr_is_on = bluetooth.async_address_present(self.hass, self._address, connectable=True)
        self.async_on_remove(bluetooth.async_register_callback(
            self.hass, self._seen, bluetooth.BluetoothCallbackMatcher(address=self._address, connectable=True),
            bluetooth.BluetoothScanningMode.PASSIVE))
        self.async_on_remove(bluetooth.async_track_unavailable(
            self.hass, self._gone, self._address, connectable=True))

    @callback
    def _seen(self, info: bluetooth.BluetoothServiceInfoBleak, change: bluetooth.BluetoothChange) -> None:
        if not self._attr_is_on:
            self._attr_is_on = True
            self.async_write_ha_state()

    @callback
    def _gone(self, info: bluetooth.BluetoothServiceInfoBleak) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()
