"""Capacità per endpoint e selezione engine (auto | direct_rsync | rclone_smb)."""

from __future__ import annotations

from database import FileEndpoint, FileEndpointType

ENGINE_DIRECT = "direct_rsync"
ENGINE_RCLONE = "rclone_smb"

_SSH_CAPABLE = (FileEndpointType.SYNOLOGY, FileEndpointType.QNAP, FileEndpointType.LINUX)
_SMB_CAPABLE = (FileEndpointType.SYNOLOGY, FileEndpointType.QNAP, FileEndpointType.WINDOWS)


def _has_ssh_credentials(ep: FileEndpoint) -> bool:
    return bool(ep.ssh_key_path) or bool(ep.password_enc)


def resolve_capabilities(ep: FileEndpoint) -> dict:
    """Capacità derivate da tipo + config. reasons spiega ogni capacità mancante."""
    reasons: dict[str, str] = {}

    rsync_source = ep.endpoint_type in _SSH_CAPABLE and _has_ssh_credentials(ep)
    if ep.endpoint_type not in _SSH_CAPABLE:
        reasons["rsync_source"] = "Il tipo endpoint non supporta rsync via SSH (solo SMB)."
    elif not _has_ssh_credentials(ep):
        reasons["rsync_source"] = "Mancano credenziali SSH (chiave o password)."

    extra = ep.extra_config or {}
    has_module = bool(extra.get("rsync_module"))
    rsync_dest = ep.endpoint_type in _SSH_CAPABLE and has_module
    if ep.endpoint_type not in _SSH_CAPABLE:
        reasons["rsync_dest"] = "Il tipo endpoint non può fare da destinazione rsync."
    elif not has_module:
        reasons["rsync_dest"] = (
            "Modulo rsync non configurato: attiva il servizio rsync sul NAS "
            "e imposta modulo/utente/password nell'endpoint."
        )

    smb = ep.endpoint_type in _SMB_CAPABLE
    if not smb:
        reasons["smb"] = "Endpoint senza share SMB."

    return {
        "rsync_source": rsync_source,
        "rsync_dest": rsync_dest,
        "smb": smb,
        "reasons": reasons,
    }


def resolve_engine(sync_method: str, source: FileEndpoint, dest: FileEndpoint) -> tuple[str, str]:
    """Risolve l'engine effettivo. Solleva ValueError se un metodo forzato non è supportato."""
    src_caps = resolve_capabilities(source)
    dst_caps = resolve_capabilities(dest)
    direct_ok = src_caps["rsync_source"] and dst_caps["rsync_dest"]
    rclone_ok = src_caps["smb"] and dst_caps["smb"]

    if sync_method == ENGINE_DIRECT:
        if not direct_ok:
            missing = []
            if not src_caps["rsync_source"]:
                missing.append(f"sorgente: {src_caps['reasons'].get('rsync_source', 'non idonea')}")
            if not dst_caps["rsync_dest"]:
                missing.append(f"destinazione: {dst_caps['reasons'].get('rsync_dest', 'non idonea')}")
            raise ValueError("Motore diretto rsync non disponibile — " + "; ".join(missing))
        return ENGINE_DIRECT, "Motore diretto rsync forzato dall'utente."

    if sync_method == ENGINE_RCLONE:
        if not rclone_ok:
            raise ValueError("Motore rclone SMB non disponibile: sorgente o destinazione senza SMB.")
        return ENGINE_RCLONE, "Motore rclone SMB forzato dall'utente."

    # auto
    if direct_ok:
        return ENGINE_DIRECT, (
            "Diretto rsync: i dati viaggiano dalla sorgente alla destinazione senza passare da dapx."
        )
    if rclone_ok:
        why = (
            src_caps["reasons"].get("rsync_source")
            or dst_caps["reasons"].get("rsync_dest")
            or "prerequisiti rsync mancanti"
        )
        return ENGINE_RCLONE, f"rclone SMB (fallback): {why}"
    raise ValueError(
        "Nessun motore disponibile per questa coppia di endpoint: configurare SSH/rsync o SMB."
    )
