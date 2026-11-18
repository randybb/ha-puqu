"""Protocol checks (needs Pillow), against the bytes that printed on a P1L over RFCOMM and BLE.

    python tests/test_protocol.py
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "custom_components" / "puqu"))
from PIL import Image  # noqa: E402

from protocol import compress, errors, image_rows, label_parts, replies, state  # noqa: E402

assert compress([[0] * 400]) == bytes([60, 1, 0, 0, 50])
row = [0] * 400
row[0] = 1
assert compress([row, row]) == bytes([60, 2, 0, 0, 49, 0x80])
header, body = label_parts([row] * 240)
assert header == bytes([58, 50, 240, 0, len(body), 0, 0, 5])

# A P1L ready, then printing, then a reply cut by the BLE notification
assert replies(bytes.fromhex("3a0094003c3c000a3a0894003b3c000a3a00")) == [
    bytes.fromhex("3a0094003c3c000a"), bytes.fromhex("3a0894003b3c000a")]
assert state(bytes.fromhex("3a0094003c3c000a")) == {
    "errors": [], "printing": False, "low_battery": False, "darkness_level": 2}
assert errors(bytes([58, 0xC0, 0x14, 0, 60, 60, 0, 10])) == [
    "The printer has no labels", "The cover of the printer is open"]
# Dark dots printed, cut to the 48 mm of the printhead
img = Image.new("1", (400, 3), 1)
img.putpixel((0, 1), 0)
rows = image_rows(img)
assert len(rows[0]) == 384 and rows[1][0] == 1 and sum(map(sum, rows)) == 1
# Home Assistant refuses name patterns in the first 3 characters, and with
# them its whole Bluetooth
import json  # noqa: E402

manifest = json.loads((Path(__file__).parents[1] / "custom_components" / "puqu" / "manifest.json").read_text())
for matcher in manifest["bluetooth"]:
    assert not set(matcher.get("local_name", "xxx")[:3]) & set("*?["), matcher
print("ok")
