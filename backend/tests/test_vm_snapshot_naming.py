"""Test naming snapshot modulo vm_snapshot."""

from datetime import datetime

import pytest

from services.vm_snapshot.naming import (
    build_description,
    build_snapshot_name,
    parse_snapshot_name,
    validate_label,
)


def test_build_and_parse_roundtrip():
    dt = datetime(2026, 7, 22, 3, 15, 0)
    name = build_snapshot_name("daily", dt)
    assert name == "autodaily_20260722_031500"
    assert len(name) <= 40
    label, ts = parse_snapshot_name(name)
    assert label == "daily"
    assert ts == dt


def test_max_length_with_long_label():
    dt = datetime(2026, 12, 31, 23, 59, 59)
    name = build_snapshot_name("a234567890123456", dt)  # 16 char, massimo
    assert len(name) <= 40


@pytest.mark.parametrize("bad", ["Daily", "auto_x", "1daily", "a", "daily_x", "con-trattino", ""])
def test_invalid_labels_rejected(bad):
    with pytest.raises(ValueError):
        validate_label(bad)


@pytest.mark.parametrize(
    "name",
    [
        "autosnap_2026-07-22_03:15:00_daily",  # Sanoid: mai nostro
        "manuale",
        "autodaily_20260722",                  # timestamp incompleto
        "autodaily_20261322_031500",           # mese 13: data invalida
        "autoDaily_20260722_031500",           # maiuscola
        "pre-upgrade",
        "current",
    ],
)
def test_foreign_names_not_parsed(name):
    assert parse_snapshot_name(name) is None


def test_description_mentions_job():
    desc = build_description(3, "Snap prod", "daily")
    assert "job=3" in desc and "label=daily" in desc
