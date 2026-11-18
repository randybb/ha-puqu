"""The protocol of the PUQU label printers (Q00, Reekon P1 Tagger / P1L), as
https://github.com/MatinxHT/puquprintJS (src/protocol.ts) sends it. A label is
a header and its rows, run-length compressed. State replies are 8 bytes,
3a <flags> <settings> 00 <buffer> .. 00 0a. No Home Assistant in here."""

from __future__ import annotations

# 8 dots per mm, the printhead is 48 mm wide
HEAD = 384
WRITE = "0000ae01-0000-1000-8000-00805f9b34fb"
NOTIFY = "0000ae02-0000-1000-8000-00805f9b34fb"
STATE_QUERY = bytes([0x3A, 0x5A, 0, 0, 0, 0, 0, 0x0A])
NO_PAPER, COVER_OPEN, BAD_DATA, LOW_BATTERY, PRINTING, PRINT_ERROR, CANCELING = 0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02
ERRORS = {
    NO_PAPER: "The printer has no labels",
    COVER_OPEN: "The cover of the printer is open",
    BAD_DATA: "The printer could not read the label",
    PRINT_ERROR: "The printer reports a print error",
}


def compress(rows: list[list[int]]) -> bytes:
    """Rows of dots, 1 printed: equal rows that follow each other once with
    their count, without the empty bytes at both ends."""
    out, y = bytearray(), 0
    while y < len(rows):
        n = 1
        while y + n < len(rows) and n < 0xFFFF and rows[y + n] == rows[y]:
            n += 1
        packed = bytearray((len(rows[y]) + 7) // 8)
        for x, dot in enumerate(rows[y]):
            if dot:
                packed[x // 8] |= 0x80 >> (x % 8)
        left = len(packed) - len(packed.lstrip(b"\0"))
        right = len(packed) - len(packed.rstrip(b"\0"))
        if left + right >= len(packed):
            left, right = 0, len(packed)
        out += bytes([0x3C, n & 0xFF, n >> 8, left, right]) + packed[left : len(packed) - right]
        y += n
    return bytes(out)


def label_parts(rows: list[list[int]]) -> tuple[bytes, bytes]:
    """The header with the size of the label, and its rows."""
    body = compress(rows)
    width, height = len(rows[0]), len(rows)
    header = bytes([0x3A, (width + 7) // 8, height & 0xFF, height >> 8,
                    len(body) & 0xFF, (len(body) >> 8) & 0xFF, len(body) >> 16, 5])
    return header, body


def image_rows(img) -> list[list[int]]:
    """A PIL image as rows of dots, dark ones printed, the first row first
    out, as wide as the printhead at most."""
    gray = img.convert("L")
    width = min(gray.width, HEAD)
    data = gray.tobytes()
    return [[1 if data[y * gray.width + x] < 128 else 0 for x in range(width)] for y in range(gray.height)]


def replies(data: bytes) -> list[bytes]:
    """The state replies in what the printer sent."""
    found, i = [], data.find(0x3A)
    while 0 <= i <= len(data) - 8:
        if data[i + 7] == 0x0A:
            found.append(data[i : i + 8])
            i += 8
        else:
            i += 1
        i = data.find(0x3A, i)
    return found


def errors(reply: bytes) -> list[str]:
    return [message for flag, message in ERRORS.items() if reply[1] & flag]


def state(reply: bytes) -> dict:
    """A state reply as the status action answers it."""
    return {
        "errors": errors(reply),
        "printing": bool(reply[1] & PRINTING),
        "low_battery": bool(reply[1] & LOW_BATTERY),
        # Coarse darkness set on the printer: 5-7 0, 8-10 1, 11-13 2, 14-15 3
        "darkness_level": reply[2] >> 6,
    }
