"""Test schedule helpers condivisi."""

import pytest

from services.schedule_helpers import resolve_schedule_pair


def test_resolve_schedule_pair_from_config():
    cron, cfg = resolve_schedule_pair(None, {"kind": "daily", "time": "02:00"})
    assert cron is not None
    assert cfg["kind"] == "daily"


def test_resolve_schedule_pair_from_cron():
    cron, cfg = resolve_schedule_pair("0 2 * * *", None)
    assert cron == "0 2 * * *"
    assert cfg is not None


def test_resolve_schedule_pair_manual():
    cron, cfg = resolve_schedule_pair("", None)
    assert cron is None
    assert cfg["kind"] == "manual"


def test_resolve_schedule_pair_invalid_config():
    with pytest.raises(Exception):
        resolve_schedule_pair(None, {"kind": "invalid_kind_xyz"})
