"""Test discovery job backup Proxmox verso PBS."""

from services.pve_backup_discovery import (
    _enabled_flag,
    _parse_vmid_list,
    _resolve_vmids,
)


def test_parse_vmid_list():
    assert _parse_vmid_list("100,103,105") == [100, 103, 105]
    assert _parse_vmid_list(100) == [100]
    assert _parse_vmid_list("") == []


def test_enabled_flag():
    assert _enabled_flag({"enabled": 1}) is True
    assert _enabled_flag({"disable": 1}) is False
    assert _enabled_flag({}) is True


def test_resolve_vmids_all():
    vms = {100: {"name": "a"}, 101: {"name": "b"}}
    assert _resolve_vmids({"all": 1}, vms) == [100, 101]


def test_resolve_vmids_pool():
    vms = {
        100: {"pool": "prod"},
        101: {"pool": "test"},
        102: {"pool": "prod"},
    }
    assert _resolve_vmids({"pool": "prod"}, vms) == [100, 102]


def test_resolve_vmids_explicit():
    vms = {100: {}, 101: {}}
    assert _resolve_vmids({"vmid": "100,101"}, vms) == [100, 101]
