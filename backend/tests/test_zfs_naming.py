"""Test normalizzazione nomi ZFS replica."""

from services.zfs_naming import (
    collapse_dash_segments,
    derive_zfs_storage_name,
    normalize_zfs_dest_path,
    normalize_zfs_replica_dest,
)


def test_collapse_dash_segments():
    assert collapse_dash_segments("ZFS-LARGE-replica-replica") == "ZFS-LARGE-replica"
    assert collapse_dash_segments("replica-replica-dr") == "replica-dr"


def test_normalize_dest_path_storage_suffix():
    pool, sub = normalize_zfs_dest_path("ZFS-LARGE-replica", "replica")
    assert pool == "ZFS-LARGE"
    assert sub == "replica"


def test_derive_storage_no_double_suffix():
    assert derive_zfs_storage_name("ZFS-LARGE-replica", "ZFS-LARGE/replica") == "ZFS-LARGE-replica"


def test_normalize_replica_dest_full():
    pool, sub, path, storage = normalize_zfs_replica_dest(
        "ZFS-LARGE-replica", "replica", "ZFS-LARGE-replica"
    )
    assert pool == "ZFS-LARGE"
    assert sub == "replica"
    assert path == "ZFS-LARGE/replica"
    assert storage == "ZFS-LARGE-replica"


def test_nested_subfolder():
    assert derive_zfs_storage_name("ZFS-LARGE", "ZFS-LARGE/replica/dr") == "ZFS-LARGE-replica-dr"
