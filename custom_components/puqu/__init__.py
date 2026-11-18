"""PUQU label printers (Q00, Reekon P1 Tagger / P1L) over Bluetooth LE, also
through ESPHome Bluetooth proxies. puqu.print prints an image, puqu.status
asks the printer its state. As in hass-niimbot, the state is asked every scan
interval while Home Assistant hears the printer, and the connection is kept
between them if keep connection is set; the connectivity sensor tells from
the advertisements whether it is heard, without connecting."""

from __future__ import annotations

import asyncio
import base64
from datetime import timedelta
import io
import logging
import time

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import protocol
from .const import CONF_KEEP_CONNECTION, DEFAULT_KEEP_CONNECTION, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS = ["binary_sensor", "sensor"]
# How long the printer may take to answer
ANSWER_WAIT = 3
# Between the header of a label and its rows, as the app does
HEADER_PAUSE = 0.003
# Between two writes, as puquprintJS does
CHUNK_PAUSE = 0.01
# While it prints, a P1L tells its state on its own every 0.2 s, then
# nothing: it has printed once it was quiet this long
QUIET = 0.8
# Longest a label takes: 3 s at least, else per mm at the slowest
PRINT_WAIT, SECONDS_PER_MM = 3, 0.1
LABEL_WAIT = 10
NOT_REACHED = "Home Assistant does not reach the printer, is it on?"

PRINT_SCHEMA = vol.Schema({vol.Required("device_id"): cv.string, vol.Required("image"): cv.string})
STATUS_SCHEMA = vol.Schema({vol.Required("device_id"): cv.string})


def option(entry: ConfigEntry, key: str, default):
    return entry.options.get(key, entry.data.get(key, default))


class Printer:
    """A printer and its connection, kept between uses with keep connection.
    The state replies it sends come in received."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        self.hass, self.address = hass, entry.unique_id
        self.keep = option(entry, CONF_KEEP_CONNECTION, DEFAULT_KEEP_CONNECTION)
        self.lock = asyncio.Lock()
        self.client = None
        self.received, self.last = b"", 0.0
        self.got = asyncio.Event()
        self.coordinator: DataUpdateCoordinator | None = None

    async def connect(self):
        if self.client is not None and self.client.is_connected:
            return
        ble = bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)
        if ble is None:
            raise HomeAssistantError(NOT_REACHED)
        try:
            self.client = await establish_connection(
                BleakClientWithServiceCache, ble, ble.name or self.address, disconnected_callback=self._gone)
            await self.client.start_notify(protocol.NOTIFY, self._notified)
        except Exception as e:
            self.client = None
            raise HomeAssistantError(f"Could not connect to the printer: {e}") from e

    async def release(self, always: bool = False):
        if self.client is not None and (always or not self.keep):
            client, self.client = self.client, None
            await client.disconnect()

    def _gone(self, _client):
        self.client = None

    def _notified(self, _, data: bytearray):
        self.received += bytes(data)
        self.last = time.monotonic()
        self.got.set()

    async def write(self, data: bytes):
        size = max(20, min(self.client.mtu_size - 3, 180))
        for i in range(0, len(data), size):
            await self.client.write_gatt_char(protocol.WRITE, data[i : i + size], response=False)
            await asyncio.sleep(CHUNK_PAUSE)

    async def ask(self) -> bytes:
        """The state reply to a query, also given to the entities."""
        self.received = b""
        await self.write(protocol.STATE_QUERY)
        deadline = time.monotonic() + ANSWER_WAIT
        while not protocol.replies(self.received):
            self.got.clear()
            try:
                await asyncio.wait_for(self.got.wait(), max(deadline - time.monotonic(), 0.01))
            except TimeoutError:
                raise HomeAssistantError("The printer does not answer") from None
        reply = protocol.replies(self.received)[-1]
        if self.coordinator is not None:
            self.coordinator.async_set_updated_data(protocol.state(reply))
        return reply

    async def printed(self, wait: float):
        """Until the printer printed the label: it tells that it prints on
        its own, then it is quiet. Never asked while it prints, that feeds
        an empty label."""
        self.received, self.last = b"", 0.0
        deadline = time.monotonic() + wait + LABEL_WAIT
        sent = time.monotonic()
        while time.monotonic() < deadline:
            await asyncio.sleep(0.1)
            quiet = time.monotonic() - (self.last or sent)
            if (self.last and quiet > QUIET) or (not self.last and quiet > wait):
                return
        raise HomeAssistantError("The printer did not finish the label")

    async def state(self) -> dict:
        async with self.lock:
            try:
                await self.connect()
                return protocol.state(await self.ask())
            except Exception:
                await self.release(always=True)
                raise
            finally:
                await self.release()

    async def print(self, rows: list[list[int]]):
        header, body = protocol.label_parts(rows)
        async with self.lock:
            try:
                await self.connect()
                reply = await self.ask()
                if protocol.errors(reply) or reply[1] & protocol.PRINTING:
                    raise HomeAssistantError((protocol.errors(reply) or ["The printer is printing"])[0])
                await self.write(header)
                await asyncio.sleep(HEADER_PAUSE)
                await self.write(body)
                await self.printed(max(PRINT_WAIT, len(rows) / 8 * SECONDS_PER_MM))
                problems = protocol.errors(await self.ask())
            except Exception:
                await self.release(always=True)
                raise
            finally:
                await self.release()
        if problems:
            raise HomeAssistantError(problems[0])


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    async def print_label(call: ServiceCall) -> None:
        try:
            from PIL import Image

            img = Image.open(io.BytesIO(base64.b64decode(call.data["image"].split(",", 1)[-1])))
            img.load()
        except Exception as e:
            raise HomeAssistantError(f"The image is no PNG or JPEG in base64: {e}") from e
        rows = await hass.async_add_executor_job(protocol.image_rows, img)
        await _printer(hass, call.data["device_id"]).print(rows)

    async def status(call: ServiceCall) -> ServiceResponse:
        return await _printer(hass, call.data["device_id"]).state()

    hass.services.async_register(DOMAIN, "print", print_label, PRINT_SCHEMA, SupportsResponse.NONE)
    hass.services.async_register(DOMAIN, "status", status, STATUS_SCHEMA, SupportsResponse.ONLY)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # A device, so that the actions take it by its device ID
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        connections={(dr.CONNECTION_BLUETOOTH, entry.unique_id)},
        manufacturer="PUQU", name=entry.title)
    printer = Printer(hass, entry)

    async def update() -> dict:
        # One that is not heard is not connected to, it is switched off
        if not bluetooth.async_address_present(hass, printer.address, connectable=True):
            await printer.release(always=True)
            raise UpdateFailed(NOT_REACHED)
        try:
            return await printer.state()
        except HomeAssistantError as e:
            raise UpdateFailed(str(e)) from e

    printer.coordinator = DataUpdateCoordinator(
        hass, _LOGGER, config_entry=entry, name=entry.title, update_method=update,
        update_interval=timedelta(seconds=option(entry, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)))
    entry.runtime_data = printer
    await printer.coordinator.async_refresh()
    entry.async_on_unload(entry.add_update_listener(_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _reload(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.coordinator.async_shutdown()
        await entry.runtime_data.release(always=True)
    return unloaded


def _printer(hass: HomeAssistant, device_id: str) -> Printer:
    device = dr.async_get(hass).async_get(device_id)
    entry = next((hass.config_entries.async_get_entry(e) for e in (device.config_entries if device else ())), None)
    if entry is None or entry.domain != DOMAIN or not hasattr(entry, "runtime_data"):
        raise HomeAssistantError(f"{device_id} is no PUQU printer that is set up")
    return entry.runtime_data
