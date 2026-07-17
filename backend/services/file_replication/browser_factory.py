"""Factory browser endpoint replica file."""

from __future__ import annotations

from database import FileEndpoint, FileEndpointType
from services.file_replication.endpoint_crypto import decrypt_password
from services.file_replication.linux_browser import LinuxSshBrowser
from services.file_replication.qnap_client import QnapClient
from services.file_replication.smb_browser import SmbBrowser
from services.file_replication.synology_client import SynologyClient


def default_port(endpoint_type: FileEndpointType) -> int:
    return {
        FileEndpointType.SYNOLOGY: 5001,
        FileEndpointType.QNAP: 8080,
        FileEndpointType.LINUX: 22,
        FileEndpointType.WINDOWS: 445,
    }[endpoint_type]


def default_protocol(endpoint_type: FileEndpointType) -> str:
    return {
        FileEndpointType.SYNOLOGY: "api",
        FileEndpointType.QNAP: "api",
        FileEndpointType.LINUX: "ssh",
        FileEndpointType.WINDOWS: "smb",
    }[endpoint_type]


def get_browser(endpoint: FileEndpoint):
    password = decrypt_password(endpoint.password_enc or "")
    et = endpoint.endpoint_type
    if et == FileEndpointType.SYNOLOGY:
        verify_ssl = (endpoint.extra_config or {}).get("verify_ssl", False)
        return SynologyClient(
            endpoint.host,
            endpoint.port or 5001,
            endpoint.username,
            password,
            verify_ssl=bool(verify_ssl),
        )
    if et == FileEndpointType.QNAP:
        return QnapClient(endpoint.host, endpoint.port or 8080, endpoint.username, password)
    if et == FileEndpointType.LINUX:
        return LinuxSshBrowser(
            endpoint.host,
            endpoint.port or 22,
            endpoint.username,
            password,
            endpoint.ssh_key_path,
        )
    if et == FileEndpointType.WINDOWS:
        return SmbBrowser(
            endpoint.host,
            endpoint.port or 445,
            endpoint.username,
            password,
            endpoint.domain,
            endpoint.base_path,
        )
    raise ValueError(f"tipo endpoint non supportato: {et}")
