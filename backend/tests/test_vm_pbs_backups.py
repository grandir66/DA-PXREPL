"""Test adapter backup PBS per endpoint VM."""

from routers.vms import _vm_backup_from_inventory_entry


def test_vm_backup_from_inventory_entry_ms_timestamp():
    row = _vm_backup_from_inventory_entry(
        {
            "volid": "PBS:backup/vm/100/2024-01-01T00:00:00Z",
            "backup_time": 1704067200000,
            "size": 12345,
            "vm_type": "qemu",
            "restore_path": "vm/100/2024-01-01T00:00:00Z",
        },
        storage_id="PBS",
    )
    assert row["backup-time"] == 1704067200
    assert row["volid"] == "PBS:backup/vm/100/2024-01-01T00:00:00Z"
    assert row["storage_id"] == "PBS"
    assert row["backup-type"] == "vm"


def test_vm_backup_from_inventory_entry_ct():
    row = _vm_backup_from_inventory_entry(
        {"backup_time": 1704067200, "vm_type": "lxc", "restore_path": "ct/200/2024-01-01T00:00:00Z"},
        storage_id="pbs-store",
    )
    assert row["backup-type"] == "lxc"
    assert row["restore_path"] == "ct/200/2024-01-01T00:00:00Z"
