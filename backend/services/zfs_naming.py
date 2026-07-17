"""Normalizzazione nomi pool/dataset/storage ZFS per replica syncoid."""

from __future__ import annotations

from typing import Optional


def collapse_dash_segments(name: str) -> str:
    """Rimuove segmenti consecutivi duplicati (es. replica-replica → replica)."""
    if not name:
        return name
    parts = name.split("-")
    out: list[str] = []
    for part in parts:
        if out and out[-1].lower() == part.lower():
            continue
        out.append(part)
    return "-".join(out)


def normalize_zfs_dest_path(
    pool: Optional[str],
    subfolder: Optional[str],
) -> tuple[str, Optional[str]]:
    """
    Separa pool ZFS e sottocartella evitando ridondanze nel nome pool.

    Es.: pool=ZFS-LARGE-replica + subfolder=replica → (ZFS-LARGE, replica)
    """
    clean_pool = (pool or "").strip().strip("/")
    clean_sub = (subfolder or "").strip().strip("/") or None
    if not clean_pool or not clean_sub:
        return clean_pool, clean_sub

    # Nome storage Proxmox già suffissato (ZFS-LARGE-replica)
    if "/" not in clean_pool and clean_pool.endswith(f"-{clean_sub}"):
        root = clean_pool[: -(len(clean_sub) + 1)]
        if root:
            return root, clean_sub

    # Path dataset già include la sottocartella (ZFS-LARGE/replica)
    if clean_pool.endswith(f"/{clean_sub}"):
        root = clean_pool[: -(len(clean_sub) + 1)].rstrip("/")
        if root:
            return root, clean_sub

    return clean_pool, clean_sub


def zfs_dataset_path(pool: str, subfolder: Optional[str]) -> str:
    pool, subfolder = normalize_zfs_dest_path(pool, subfolder)
    if not pool:
        return ""
    if subfolder:
        return f"{pool}/{subfolder}"
    return pool


def derive_zfs_storage_name(storage_name: Optional[str], zfs_pool: str) -> str:
    """Nome storage Proxmox coerente con il dataset ZFS, senza suffissi duplicati."""
    if not zfs_pool:
        return collapse_dash_segments((storage_name or "").strip())

    parts = zfs_pool.split("/")
    root = parts[0]
    base = (storage_name or root).strip()
    if len(parts) <= 1 or zfs_pool == base or zfs_pool == root:
        return collapse_dash_segments(base)

    sub = "-".join(parts[1:])
    from_root = f"{root}-{sub}"
    if base in (from_root, root):
        return collapse_dash_segments(from_root if base == root else base)
    if base.endswith(f"-{sub}"):
        return collapse_dash_segments(base)
    return collapse_dash_segments(f"{base}-{sub}")


def normalize_zfs_replica_dest(
    dest_pool: Optional[str],
    dest_subfolder: Optional[str],
    dest_storage: Optional[str] = None,
) -> tuple[str, Optional[str], str, str]:
    """
    Normalizza pool, subfolder, path dataset e nome storage destinazione.

    Returns: (pool, subfolder, zfs_path, storage_name)
    """
    pool, subfolder = normalize_zfs_dest_path(dest_pool, dest_subfolder)
    zfs_path = zfs_dataset_path(pool, subfolder)
    storage = derive_zfs_storage_name(dest_storage or pool, zfs_path)
    return pool, subfolder, zfs_path, storage
