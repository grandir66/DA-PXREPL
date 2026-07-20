"""Helper per job backup PBS multi-VM."""

from __future__ import annotations

from typing import Any, Optional

from database import BackupJob, Node


def normalize_vm_targets(
    *,
    vm_targets: Optional[list[dict[str, Any]]] = None,
    source_node_id: Optional[int] = None,
    vm_id: Optional[int] = None,
    vm_type: Optional[str] = None,
    vm_name: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Ritorna lista non vuota di target VM per backup."""
    if vm_targets:
        out: list[dict[str, Any]] = []
        for row in vm_targets:
            if not isinstance(row, dict):
                continue
            vid = row.get("vm_id")
            sid = row.get("source_node_id")
            if vid is None or sid is None:
                continue
            out.append(
                {
                    "vm_id": int(vid),
                    "vm_type": row.get("vm_type") or "qemu",
                    "vm_name": row.get("vm_name"),
                    "source_node_id": int(sid),
                }
            )
        if out:
            return out
    if vm_id is not None and source_node_id is not None:
        return [
            {
                "vm_id": int(vm_id),
                "vm_type": vm_type or "qemu",
                "vm_name": vm_name,
                "source_node_id": int(source_node_id),
            }
        ]
    return []


def resolve_vm_targets(job: BackupJob) -> list[dict[str, Any]]:
    stored = job.vm_targets if isinstance(job.vm_targets, list) else None
    return normalize_vm_targets(
        vm_targets=stored,
        source_node_id=job.source_node_id,
        vm_id=job.vm_id,
        vm_type=job.vm_type,
        vm_name=job.vm_name,
    )


def job_targets_summary(targets: list[dict[str, Any]]) -> str:
    if not targets:
        return "—"
    if len(targets) == 1:
        t = targets[0]
        name = t.get("vm_name") or f"VM {t.get('vm_id')}"
        return str(name)
    ids = ", ".join(str(t["vm_id"]) for t in targets[:5])
    suffix = f" +{len(targets) - 5}" if len(targets) > 5 else ""
    return f"{len(targets)} VM ({ids}{suffix})"
