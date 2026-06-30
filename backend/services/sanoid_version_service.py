"""
Verifica versioni Sanoid/Syncoid sui nodi e confronto con upstream GitHub.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from database import Node
from services.ssh_service import ssh_service
from services.sanoid_service import sanoid_service

logger = logging.getLogger(__name__)

SANOID_REPO = "jimsalterjrs/sanoid"
GITHUB_TAGS_URL = f"https://api.github.com/repos/{SANOID_REPO}/tags"
GITHUB_LATEST_RELEASE_URL = f"https://api.github.com/repos/{SANOID_REPO}/releases/latest"

_upstream_cache: Dict[str, Any] = {"fetched_at": None, "data": None}
_CACHE_TTL_SECONDS = 3600


def normalize_version(version: Optional[str]) -> Tuple[int, ...]:
    """Estrae tuple numerica da stringa versione per confronto."""
    if not version:
        return (0,)
    match = re.search(r"(\d+(?:\.\d+)*)", str(version))
    if not match:
        return (0,)
    parts: List[int] = []
    for part in match.group(1).split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts) if parts else (0,)


def compare_versions(current: Optional[str], latest: Optional[str]) -> int:
    """
    Confronta versioni. Ritorna:
      -1 se current < latest (update disponibile)
       0 se uguali o non confrontabili
       1 se current > latest
    """
    a = normalize_version(current)
    b = normalize_version(latest)
    if a == b:
        return 0
    # Padding a pari lunghezza
    length = max(len(a), len(b))
    a = a + (0,) * (length - len(a))
    b = b + (0,) * (length - len(b))
    if a < b:
        return -1
    if a > b:
        return 1
    return 0


async def fetch_upstream_version(*, force: bool = False) -> Dict[str, Any]:
    """Ultima versione Sanoid/Syncoid da GitHub (tag/release)."""
    now = datetime.now(timezone.utc)
    cached = _upstream_cache.get("data")
    fetched_at = _upstream_cache.get("fetched_at")
    if (
        not force
        and cached
        and fetched_at
        and (now - fetched_at).total_seconds() < _CACHE_TTL_SECONDS
    ):
        return cached

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "dapx-unified-sanoid-checker",
    }

    version: Optional[str] = None
    tag: Optional[str] = None
    source = "github"

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(GITHUB_LATEST_RELEASE_URL, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                tag = data.get("tag_name") or data.get("name")
                if tag:
                    version = tag.lstrip("vV")
        except Exception as exc:
            logger.warning("GitHub releases/latest failed: %s", exc)

        if not version:
            try:
                resp = await client.get(
                    GITHUB_TAGS_URL, headers=headers, params={"per_page": 5}
                )
                if resp.status_code == 200:
                    tags = resp.json()
                    if tags:
                        tag = tags[0].get("name")
                        if tag:
                            version = tag.lstrip("vV")
            except Exception as exc:
                logger.warning("GitHub tags failed: %s", exc)

    result = {
        "version": version,
        "tag": tag,
        "package": "sanoid+syncoid",
        "source_url": f"https://github.com/{SANOID_REPO}",
        "release_url": f"https://github.com/{SANOID_REPO}/releases",
        "fetched_at": now.isoformat(),
        "source": source,
    }
    if not version:
        result["error"] = "Impossibile recuperare la versione upstream da GitHub"

    _upstream_cache["data"] = result
    _upstream_cache["fetched_at"] = now
    return result


async def probe_node_tools(node: Node, latest_version: Optional[str]) -> Dict[str, Any]:
    """Legge versioni Sanoid/Syncoid su un nodo via SSH."""
    base = {
        "node_id": node.id,
        "node_name": node.name,
        "hostname": node.hostname,
        "node_type": node.node_type,
        "is_online": node.is_online,
        "sanoid_installed": False,
        "sanoid_version": None,
        "syncoid_installed": False,
        "syncoid_version": None,
        "update_available": False,
        "status": "offline",
        "error": None,
    }

    if node.node_type not in ("pve", None, ""):
        base["status"] = "skipped"
        base["error"] = "Nodo non PVE"
        return base

    if not node.is_online:
        return base

    try:
        sanoid_ok, sanoid_ver = await ssh_service.check_sanoid_installed(
            hostname=node.hostname,
            port=node.ssh_port or 22,
            username=node.ssh_user or "root",
            key_path=node.ssh_key_path,
        )
        syncoid_ok, syncoid_ver = await ssh_service.check_syncoid_installed(
            hostname=node.hostname,
            port=node.ssh_port or 22,
            username=node.ssh_user or "root",
            key_path=node.ssh_key_path,
        )

        base["sanoid_installed"] = sanoid_ok
        base["sanoid_version"] = sanoid_ver
        base["syncoid_installed"] = syncoid_ok
        base["syncoid_version"] = syncoid_ver

        if not sanoid_ok and not syncoid_ok:
            base["status"] = "missing"
        elif latest_version and (
            (sanoid_ok and compare_versions(sanoid_ver, latest_version) < 0)
            or (syncoid_ok and compare_versions(syncoid_ver, latest_version) < 0)
            or (sanoid_ok and not syncoid_ok)
        ):
            base["update_available"] = True
            base["status"] = "outdated"
        else:
            base["status"] = "ok"

    except Exception as exc:
        base["status"] = "error"
        base["error"] = str(exc)
        logger.warning("Sanoid probe failed on %s: %s", node.name, exc)

    return base


async def get_all_nodes_tool_status(
    nodes: List[Node],
    *,
    refresh_upstream: bool = False,
) -> Dict[str, Any]:
    """Stato Sanoid/Syncoid su tutti i nodi PVE + versione upstream."""
    upstream = await fetch_upstream_version(force=refresh_upstream)
    latest = upstream.get("version")

    pve_nodes = [n for n in nodes if n.node_type in ("pve", None, "") and n.is_active]
    probes = await asyncio.gather(
        *[probe_node_tools(n, latest) for n in pve_nodes],
        return_exceptions=False,
    )

    summary = {
        "total_pve": len(pve_nodes),
        "ok": sum(1 for p in probes if p["status"] == "ok"),
        "outdated": sum(1 for p in probes if p["status"] == "outdated"),
        "missing": sum(1 for p in probes if p["status"] == "missing"),
        "offline": sum(1 for p in probes if p["status"] == "offline"),
        "errors": sum(1 for p in probes if p["status"] == "error"),
    }

    return {
        "upstream": upstream,
        "nodes": probes,
        "summary": summary,
    }


async def update_node_sanoid_syncoid(node: Node) -> Tuple[bool, str]:
    """Aggiorna/reinstalla Sanoid+Syncoid su un nodo (force)."""
    return await sanoid_service.install_sanoid(
        hostname=node.hostname,
        port=node.ssh_port or 22,
        username=node.ssh_user or "root",
        key_path=node.ssh_key_path,
        force=True,
    )
