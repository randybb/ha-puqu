# PUQU label printers for Home Assistant

Prints on the PUQU Q00 and the Reekon P1 Tagger (P1L, the same printer) over
Bluetooth LE, through the Bluetooth of Home Assistant, so also through ESPHome
Bluetooth proxies (with `active: true`). The protocol is the one of
[puquprintJS](https://github.com/MatinxHT/puquprintJS).

Printers are found by their Bluetooth name (`Q00-…`, `P1L-…`) and set up one
by one. Nothing is polled: the printer is reached only for the two actions,
so it can switch itself off and its battery lasts.

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

`darkness_level` is the darkness set on the printer, coarsely: 0 for 5-7,
1 for 8-10, 2 for 11-13, 3 for 14-15.

[Labelburg](https://github.com/DL6ER/labelburg) designs the labels.

## Tests

```sh
python tests/test_protocol.py
```
