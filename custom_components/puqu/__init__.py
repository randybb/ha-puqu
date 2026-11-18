"""PUQU label printers (Q00, Reekon P1 Tagger / P1L) over Bluetooth LE, also
through ESPHome Bluetooth proxies. puqu.print prints an image, puqu.status
asks the printer its state; nothing is polled, the printer is reached only
for these. The connectivity sensor tells whether Home Assistant hears it."""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import time

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from . import protocol
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS = ["binary_sensor"]
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

PRINT_SCHEMA = vol.Schema({vol.Required("device_id"): cv.string, vol.Required("image"): cv.string})
STATUS_SCHEMA = vol.Schema({vol.Required("device_id"): cv.string})

_locks: dict[str, asyncio.Lock] = {}


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    async def print_label(call: ServiceCall) -> None:
        await _print(hass, call)

    async def status(call: ServiceCall) -> ServiceResponse:
        return await _status(hass, call)

    hass.services.async_register(DOMAIN, "print", print_label, PRINT_SCHEMA, SupportsResponse.NONE)
    hass.services.async_register(DOMAIN, "status", status, STATUS_SCHEMA, SupportsResponse.ONLY)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # A device, so that the actions take it by its device ID
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        connections={(dr.CONNECTION_BLUETOOTH, entry.unique_id)},
        manufacturer="PUQU", name=entry.title)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _address(hass: HomeAssistant, device_id: str) -> str:
    device = dr.async_get(hass).async_get(device_id)
    entry = next((hass.config_entries.async_get_entry(e) for e in (device.config_entries if device else ())), None)
    if entry is None or entry.domain != DOMAIN:
        raise HomeAssistantError(f"{device_id} is no PUQU printer")
    return entry.unique_id


class _Printer:
    """One connection: the state replies the printer sends come in replies."""

    def __init__(self, hass: HomeAssistant, address: str):
        self.hass, self.address, self.received = hass, address, b""
        self.got = asyncio.Event()
        self.last = 0.0

    async def __aenter__(self):
        ble = bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)
        if ble is None:
            raise HomeAssistantError("Home Assistant does not reach the printer, is it on?")
        try:
            self.client = await establish_connection(BleakClientWithServiceCache, ble, ble.name or self.address)
            await self.client.start_notify(protocol.NOTIFY, self._notified)
        except Exception as e:
            raise HomeAssistantError(f"Could not connect to the printer: {e}") from e
        return self

    async def __aexit__(self, *exc):
        await self.client.disconnect()

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
        """The state reply to a query."""
        self.received = b""
        await self.write(protocol.STATE_QUERY)
        deadline = time.monotonic() + ANSWER_WAIT
        while not protocol.replies(self.received):
            self.got.clear()
            try:
                await asyncio.wait_for(self.got.wait(), max(deadline - time.monotonic(), 0.01))
            except TimeoutError:
                raise HomeAssistantError("The printer does not answer") from None
        return protocol.replies(self.received)[-1]

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


def _lock(address: str) -> asyncio.Lock:
    return _locks.setdefault(address, asyncio.Lock())


async def _status(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    address = _address(hass, call.data["device_id"])
    async with _lock(address), _Printer(hass, address) as printer:
        return protocol.state(await printer.ask())


async def _print(hass: HomeAssistant, call: ServiceCall) -> None:
    address = _address(hass, call.data["device_id"])
    image = call.data["image"]
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(base64.b64decode(image.split(",", 1)[-1])))
        img.load()
    except Exception as e:
        raise HomeAssistantError(f"The image is no PNG or JPEG in base64: {e}") from e
    rows = await hass.async_add_executor_job(protocol.image_rows, img)
    header, body = protocol.label_parts(rows)
    async with _lock(address), _Printer(hass, address) as printer:
        reply = await printer.ask()
        if protocol.errors(reply) or reply[1] & protocol.PRINTING:
            raise HomeAssistantError((protocol.errors(reply) or ["The printer is printing"])[0])
        await printer.write(header)
        await asyncio.sleep(HEADER_PAUSE)
        await printer.write(body)
        await printer.printed(max(PRINT_WAIT, len(rows) / 8 * SECONDS_PER_MM))
        problems = protocol.errors(await printer.ask())
        if problems:
            raise HomeAssistantError(problems[0])
