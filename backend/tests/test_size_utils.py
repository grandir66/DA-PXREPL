"""Test utility dimensioni trasferimento."""

from services.size_utils import (
    format_bytes_human,
    parse_transfer_size_to_bytes,
    sum_transferred_values,
)


def test_parse_transfer_sizes():
    assert parse_transfer_size_to_bytes("1.5G") == int(1.5 * 1024**3)
    assert parse_transfer_size_to_bytes("128M") == 128 * 1024**2
    assert parse_transfer_size_to_bytes("10.5 GiB") == int(10.5 * 1024**3)
    assert parse_transfer_size_to_bytes("") == 0
    assert parse_transfer_size_to_bytes("invalid") == 0


def test_format_bytes_human():
    assert format_bytes_human(0) == "0 B"
    assert format_bytes_human(1024) == "1.0 KB"
    assert format_bytes_human(1024**3) == "1.0 GB"


def test_sum_transferred_values():
    total = sum_transferred_values(["1G", "512M", None, ""])
    assert "1." in total or total.endswith("GB")
