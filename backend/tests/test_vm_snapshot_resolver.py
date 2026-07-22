"""Test apply_selectors (funzione pura) del resolver vm_snapshot."""

from services.vm_snapshot.resolver import apply_selectors

INDEX = [
    {"node_id": 1, "node_name": "px1", "vmid": 100, "name": "web01", "vm_type": "qemu",
     "status": "running", "tags": ["prod", "web"], "has_pvesr": False},
    {"node_id": 1, "node_name": "px1", "vmid": 101, "name": "db01", "vm_type": "qemu",
     "status": "running", "tags": ["prod", "db"], "has_pvesr": True},
    {"node_id": 2, "node_name": "px2", "vmid": 200, "name": "test01", "vm_type": "lxc",
     "status": "stopped", "tags": ["test"], "has_pvesr": False},
    {"node_id": 2, "node_name": "px2", "vmid": 201, "name": "web02", "vm_type": "qemu",
     "status": "running", "tags": ["prod"], "has_pvesr": False},
]


def _vmids(result):
    return sorted((vm["node_id"], vm["vmid"]) for vm in result)


def test_static_targets_only():
    result = apply_selectors(INDEX, [{"node_id": 1, "vmid": 100}], {})
    assert _vmids(result) == [(1, 100)]
    assert result[0]["source"] == "static"


def test_tag_selector():
    result = apply_selectors(INDEX, [], {"tags": ["prod"]})
    assert _vmids(result) == [(1, 100), (1, 101), (2, 201)]
    assert all(vm["source"] == "selector" for vm in result)


def test_tag_and_node_selector_are_anded():
    result = apply_selectors(INDEX, [], {"tags": ["prod"], "node_ids": [2]})
    assert _vmids(result) == [(2, 201)]


def test_node_selector_alone():
    result = apply_selectors(INDEX, [], {"node_ids": [2]})
    assert _vmids(result) == [(2, 200), (2, 201)]


def test_union_static_and_selector_with_dedup():
    result = apply_selectors(
        INDEX,
        [{"node_id": 1, "vmid": 100}, {"node_id": 2, "vmid": 200}],
        {"tags": ["prod"]},
    )
    assert _vmids(result) == [(1, 100), (1, 101), (2, 200), (2, 201)]
    by_key = {(vm["node_id"], vm["vmid"]): vm for vm in result}
    assert by_key[(1, 100)]["source"] == "static"  # statico vince sul selettore
    assert by_key[(2, 201)]["source"] == "selector"


def test_exclude_vmids():
    result = apply_selectors(INDEX, [], {"tags": ["prod"], "exclude_vmids": [101]})
    assert _vmids(result) == [(1, 100), (2, 201)]


def test_exclude_also_removes_static():
    result = apply_selectors(INDEX, [{"node_id": 1, "vmid": 100}], {"exclude_vmids": [100]})
    assert result == []


def test_static_target_missing_from_index_is_warning():
    result = apply_selectors(INDEX, [{"node_id": 9, "vmid": 999, "name": "ghost"}], {})
    assert len(result) == 1
    assert result[0]["warning"] == "not_found"
    assert result[0]["name"] == "ghost"


def test_no_selectors_no_targets_empty():
    assert apply_selectors(INDEX, [], {}) == []
