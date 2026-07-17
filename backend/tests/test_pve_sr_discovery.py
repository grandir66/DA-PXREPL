"""Test discovery repliche pvesr."""

from services.pve_sr_discovery import _parse_pvesr_id, _enabled_flag


def test_parse_pvesr_id():
    assert _parse_pvesr_id("100-0") == (100, 0)
    assert _parse_pvesr_id("205-2") == (205, 2)
    assert _parse_pvesr_id("bad") == (None, None)


def test_enabled_flag():
    assert _enabled_flag({"enabled": True}) is True
    assert _enabled_flag({"disable": 0}) is True
    assert _enabled_flag({"disable": 1}) is False
