"""Test helper target backup PBS multi-VM."""

from services.backup_job_targets import normalize_vm_targets, resolve_vm_targets, job_targets_summary


class _Job:
    vm_id = 100
    vm_type = "qemu"
    vm_name = "A"
    source_node_id = 1
    vm_targets = None


def test_normalize_legacy_single():
    t = normalize_vm_targets(source_node_id=1, vm_id=100, vm_name="X")
    assert len(t) == 1
    assert t[0]["vm_id"] == 100


def test_normalize_multi():
    t = normalize_vm_targets(
        vm_targets=[
            {"vm_id": 100, "source_node_id": 1, "vm_type": "qemu"},
            {"vm_id": 101, "source_node_id": 2, "vm_type": "lxc", "vm_name": "B"},
        ]
    )
    assert len(t) == 2
    assert t[1]["vm_name"] == "B"


def test_resolve_from_vm_targets():
    j = _Job()
    j.vm_targets = [{"vm_id": 200, "source_node_id": 3, "vm_type": "qemu"}]
    assert resolve_vm_targets(j)[0]["vm_id"] == 200


def test_summary_multi():
    s = job_targets_summary(
        [{"vm_id": 1}, {"vm_id": 2}, {"vm_id": 3}]
    )
    assert "3 VM" in s
