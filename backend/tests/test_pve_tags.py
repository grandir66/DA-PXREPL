"""Test tag REPL su VM replicate."""

from services.pve_tags import REPLICATION_VM_TAG, merge_tag_in_vm_config


def test_merge_tag_new_config():
    cfg = "name: vm-test\nmemory: 2048\n"
    out = merge_tag_in_vm_config(cfg)
    assert f"tags: {REPLICATION_VM_TAG}" in out


def test_merge_tag_existing():
    cfg = "name: vm-test\ntags: backup;prod\n"
    out = merge_tag_in_vm_config(cfg)
    assert "tags: backup;prod;REPL" in out


def test_merge_tag_idempotent():
    cfg = "tags: REPL\n"
    out = merge_tag_in_vm_config(cfg)
    assert out == cfg
