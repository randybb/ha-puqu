# PUQU label printers for Home Assistant

Prints on the PUQU Q00 and the Reekon P1 Tagger (P1L, the same printer) over
Bluetooth LE, through the Bluetooth of Home Assistant, so also through ESPHome
Bluetooth proxies (with `active: true`). The protocol is the one of
[puquprintJS](https://github.com/MatinxHT/puquprintJS).

Printers are found by their Bluetooth name (`Q00-…`, `P1L-…`) or, as a
passive scan (e.g. of ESPHome proxies) hears no name, by their service `af30`,
then named by their address; each is set up on its own.

## Options

As in [hass-niimbot](https://github.com/eigger/hass-niimbot), which this
integration follows:

* **Scan interval** (600 s): how often the state is asked while Home
  Assistant hears the printer. A printer that is not heard is not connected
  to, so it can switch itself off.
* **Keep connection** (off): the Bluetooth connection stays between the
  scans and the actions. It takes one of the connection slots of a Bluetooth
  proxy (3 on an ESP32).

## Entities

* **Connectivity**: whether Home Assistant hears the printer, from its
  advertisements, without connecting.
* From the state the printer told last: **Labels out**, **Cover**,
  **Battery low**, **Printing**, **Print error** and **Darkness level**, the
  darkness set on the printer, coarsely: 0 for 5-7, 1 for 8-10, 2 for 11-13,
  3 for 14-15.

That is all the printer tells: the details query of puquprintJS (battery
level, speed, paper type, auto power off) gets no answer from a Q00 or a P1L.

## Actions

`puqu.print` prints an image, PNG or JPEG in base64 (also as a `data:` URL).
Dark dots are printed; the image is at most 384 dots (48 mm, 8 dots per mm)
across the printhead, the first row leaves first. A 50 x 30 mm label is
384 x 240 dots. The printer is asked its state first, and an error it reports
(no labels, cover open) refuses the label.

```yaml
action: puqu.print
data:
  device_id: 0123456789abcdef0123456789abcdef
  image: "data:image/png;base64,iVBORw0KGgo..."
```

`puqu.status` answers the state of the printer:

```yaml
action: puqu.status
data:
  device_id: 0123456789abcdef0123456789abcdef
response_variable: printer
# errors: [], printing: false, low_battery: false, darkness_level: 2
```

[Labelburg](https://github.com/DL6ER/labelburg) designs the labels.

## Thanks

* [puquprintJS](https://github.com/MatinxHT/puquprintJS) for the protocol.
* [hass-niimbot](https://github.com/eigger/hass-niimbot) for how a label
  printer on Bluetooth LE fits into Home Assistant: the options, the entities
  and printing as an action.

## Tests

```sh
python tests/test_protocol.py
```
