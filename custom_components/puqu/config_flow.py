"""Config flow: printers found over Bluetooth, one entry each."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak, async_discovered_service_info
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN

NAMES = ("Q00-", "P1L-")
# The only thing a passive scan, e.g. of an ESPHome Bluetooth proxy, hears of
# them: the name comes in the answer to an active scan
SERVICE = "0000af30-0000-1000-8000-00805f9b34fb"


def _puqu(info: BluetoothServiceInfoBleak) -> bool:
    return info.name.startswith(NAMES) or SERVICE in info.service_uuids


def _title(info: BluetoothServiceInfoBleak) -> str:
    # P1L-243561(BLE) -> P1L-243561, without a name the address
    name = info.name.removesuffix("(BLE)").strip()
    return name if name.startswith(NAMES) else f"PUQU {info.address}"


class PuquConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._found: dict[str, str] = {}

    async def async_step_bluetooth(self, info: BluetoothServiceInfoBleak) -> ConfigFlowResult:
        await self.async_set_unique_id(info.address)
        self._abort_if_unique_id_configured()
        self._found = {info.address: _title(info)}
        self.context["title_placeholders"] = {"name": self._found[info.address]}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        address, name = next(iter(self._found.items()))
        if user_input is None:
            self._set_confirm_only()
            return self.async_show_form(step_id="bluetooth_confirm", description_placeholders={"name": name})
        return self.async_create_entry(title=name, data={})

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            address = user_input["address"]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=self._found[address], data={})
        configured = self._async_current_ids(include_ignore=False)
        self._found = {info.address: _title(info) for info in async_discovered_service_info(self.hass)
                       if _puqu(info) and info.address not in configured}
        if not self._found:
            return self.async_abort(reason="no_devices_found")
        return self.async_show_form(step_id="user", data_schema=vol.Schema({vol.Required("address"): vol.In(
            {address: f"{name} ({address})" for address, name in self._found.items()})}))
