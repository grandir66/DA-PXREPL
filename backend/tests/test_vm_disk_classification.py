"""Test classificazione dischi VM (ISO/cloudinit vs replicabili)."""

from services.proxmox_service import (
    classify_vm_disk,
    disable_optical_media_in_config,
    vm_disk_config_line,
)


def test_classify_zfs_disk():
    meta = classify_vm_disk("scsi0", "vm-100-disk-0,size=32G", "scsi0: ZFS-LARGE:vm-100-disk-0,size=32G")
    assert meta["replicable"] is True
    assert meta["is_iso"] is False


def test_classify_iso_cdrom():
    line = "ide2: local:iso/debian-12.iso,media=cdrom"
    meta = classify_vm_disk("ide2", "iso/debian-12.iso,media=cdrom", line)
    assert meta["replicable"] is False
    assert meta["is_iso"] is True


def test_classify_cloudinit():
    meta = classify_vm_disk("ide0", "local-zfs:vm-100-cloudinit,media=cdrom")
    assert meta["replicable"] is False
    assert meta["kind"] == "cloudinit"


def test_classify_empty_cdrom():
    meta = classify_vm_disk("ide3", "none,media=cdrom", "ide3: none,media=cdrom")
    assert meta["replicable"] is False
    assert meta["kind"] == "empty"


def test_vm_disk_config_line_extract():
    config = "boot: order=scsi0\nide2: local:iso/x.iso,media=cdrom\nscsi0: zfs:vm-1-disk-0\n"
    assert vm_disk_config_line(config, "ide2") == "ide2: local:iso/x.iso,media=cdrom"


def test_disable_optical_media_in_config():
    config = (
        "scsi0: ZFS-LARGE:vm-100-disk-0,size=32G\n"
        "ide2: NAS:iso/install.iso,media=cdrom\n"
    )
    out = disable_optical_media_in_config(config)
    assert "ide2: none,media=cdrom" in out
    assert "scsi0: ZFS-LARGE:vm-100-disk-0" in out
