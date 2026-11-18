"""Connectivity: whether Home Assistant hears the printer, from its Bluetooth
advertisements, without connecting to it, or is connected to it. The others from the state the
printer told last."""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import protocol

# Key, device class, whether the flag is on
STATE = (
    ("paper", BinarySensorDeviceClass.PROBLEM, lambda s: protocol.ERRORS[protocol.NO_PAPER] in s["errors"]),
    ("cover", BinarySensorDeviceClass.OPENING, lambda s: protocol.ERRORS[protocol.COVER_OPEN] in s["errors"]),
    ("battery_low", BinarySensorDeviceClass.BATTERY, lambda s: s["low_battery"]),
    ("printing", BinarySensorDeviceClass.RUNNING, lambda s: s["printing"]),
    ("print_error", BinarySensorDeviceClass.PROBLEM,
     lambda s: bool(set(s["errors"]) - {protocol.ERRORS[protocol.NO_PAPER], protocol.ERRORS[protocol.COVER_OPEN]})),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    add([Connectivity(entry), *(Flag(entry, *item) for item in STATE)])


class Flag(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, key, device_class, is_on) -> None:
        super().__init__(entry.runtime_data.coordinator)
        self._is_on = is_on
        self._attr_translation_key = key
        self._attr_device_class = device_class
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        self._attr_device_info = dr.DeviceInfo(connections={(dr.CONNECTION_BLUETOOTH, entry.unique_id)})

    @property
    def is_on(self) -> bool | None:
        return self._is_on(self.coordinator.data) if self.coordinator.data else None


class Connectivity(CoordinatorEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry.runtime_data.coordinator)
        self._printer = entry.runtime_data
        self._address = entry.unique_id
        self._attr_unique_id = f"{entry.unique_id}_connectivity"
        self._attr_device_info = dr.DeviceInfo(connections={(dr.CONNECTION_BLUETOOTH, entry.unique_id)})

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        # A connected printer stops advertising
        return self._attr_is_on or self._printer.connected

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
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
