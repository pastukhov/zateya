"""Validate the USB-only OTA partition candidate against 8 MiB flash."""

import csv
from pathlib import Path


TABLE = Path(__file__).resolve().parents[2] / "firmware/partitions.ota.csv"


def test_ota_layout_has_two_aligned_non_overlapping_slots():
    with TABLE.open() as source:
        rows = [row for row in csv.reader(line for line in source if not line.startswith("#"))
                if row and row[0].strip()]
    parts = {row[0].strip(): (int(row[3].strip(), 0), int(row[4].strip(), 0))
             for row in rows}
    assert set(parts) == {"nvs", "phy_init", "otadata", "ota_0", "ota_1"}
    assert parts["nvs"] == (0x9000, 0x6000)
    assert parts["phy_init"] == (0xF000, 0x1000)
    assert parts["otadata"] == (0x10000, 0x2000)
    assert parts["ota_0"][1] == parts["ota_1"][1] == 0x300000
    spans = sorted((start, start + size, name) for name, (start, size) in parts.items())
    for start, end, name in spans:
        assert start % (0x10000 if name.startswith("ota_") else 0x1000) == 0
        assert end <= 0x800000
    assert all(left[1] <= right[0] for left, right in zip(spans, spans[1:]))
