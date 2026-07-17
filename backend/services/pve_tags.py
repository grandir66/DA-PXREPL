"""Tag Proxmox per VM replicate."""

from __future__ import annotations

import re
import shlex
from typing import Optional

REPLICATION_VM_TAG = "REPL"


def merge_tag_in_vm_config(config_content: str, tag: str = REPLICATION_VM_TAG) -> str:
    """Aggiunge un tag alla config VM/CT senza rimuovere quelli esistenti."""
    if not config_content:
        return f"tags: {tag}\n"
    tag_pattern = re.compile(r"^tags:\s*(.*)$", re.MULTILINE)
    match = tag_pattern.search(config_content)
    if not match:
        return config_content.rstrip() + f"\ntags: {tag}\n"
    existing = [t.strip() for t in match.group(1).split(";") if t.strip()]
    if tag in existing:
        return config_content
    existing.append(tag)
    return tag_pattern.sub(f"tags: {';'.join(existing)}", config_content)


def parse_tags_from_config_line(line: str) -> list[str]:
    if not line.startswith("tags:"):
        return []
    raw = line.split(":", 1)[1].strip()
    return [t.strip() for t in raw.split(";") if t.strip()]


async def ensure_vm_replication_tag(
    ssh_service,
    *,
    hostname: str,
    vmid: int,
    vm_type: str = "qemu",
    tag: str = REPLICATION_VM_TAG,
    port: int = 22,
    username: str = "root",
    key_path: str = "/root/.ssh/id_rsa",
) -> tuple[bool, str]:
    """
    Assegna il tag REPL a una VM/CT su Proxmox (crea il tag al primo utilizzo).
    Non rimuove tag esistenti.
    """
    cli = "qm" if vm_type == "qemu" else "pct"
    cfg = await ssh_service.execute(
        hostname=hostname,
        command=f"{cli} config {int(vmid)} 2>/dev/null | grep '^tags:' || true",
        port=port,
        username=username,
        key_path=key_path,
        timeout=20,
    )
    current: list[str] = []
    if cfg.success and cfg.stdout.strip():
        current = parse_tags_from_config_line(cfg.stdout.strip().splitlines()[0])
    if tag in current:
        return True, f"Tag {tag} già presente su VM {vmid}"
    current.append(tag)
    merged = ";".join(current)
    result = await ssh_service.execute(
        hostname=hostname,
        command=f"{cli} set {int(vmid)} --tags {shlex.quote(merged)}",
        port=port,
        username=username,
        key_path=key_path,
        timeout=20,
    )
    if result.success:
        return True, f"Tag {tag} assegnato a VM {vmid}"
    err = (result.stderr or result.stdout or "errore sconosciuto").strip()
    return False, f"Impossibile assegnare tag {tag}: {err[:200]}"
