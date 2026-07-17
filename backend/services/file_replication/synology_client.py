"""Client Synology DSM File Station."""

from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import quote

import httpx

from services.file_replication.connection_errors import format_connection_error
from services.file_replication.path_utils import is_excluded_name, sanitize_path
from services.file_replication_schemas import BrowseEntryOut, ConnectionTestResult

logger = logging.getLogger(__name__)

DEFAULT_EXCLUDE_PRESETS = ["nas_snapshots", "system_files"]


def _synology_base_url(host: str, port: int) -> str:
    """Porta 5000 = HTTP DSM, 5001 (default) = HTTPS."""
    scheme = "http" if port == 5000 else "https"
    return f"{scheme}://{host}:{port}"


class SynologyClient:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        verify_ssl: bool = False,
    ):
        self.host = host
        self.port = port or 5001
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self._sid: Optional[str] = None
        self._base = _synology_base_url(host, self.port)

    async def _api_get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(verify=self.verify_ssl, timeout=30.0) as client:
                resp = await client.get(f"{self._base}{path}", params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(format_connection_error(self.host, self.port, exc)) from exc
        if not data.get("success"):
            err = data.get("error", {})
            code = err.get("code", "unknown")
            raise RuntimeError(f"Synology API error {code}")
        return data

    async def login(self) -> str:
        data = await self._api_get(
            "/webapi/auth.cgi",
            {
                "api": "SYNO.API.Auth",
                "version": "7",
                "method": "login",
                "account": self.username,
                "passwd": self.password,
                "session": "FileStation",
                "format": "sid",
            },
        )
        self._sid = data["data"]["sid"]
        return self._sid

    async def logout(self) -> None:
        if not self._sid:
            return
        try:
            await self._api_get(
                "/webapi/auth.cgi",
                {
                    "api": "SYNO.API.Auth",
                    "version": "7",
                    "method": "logout",
                    "session": "FileStation",
                    "_sid": self._sid,
                },
            )
        except Exception as exc:
            logger.debug("Synology logout: %s", exc)
        finally:
            self._sid = None

    async def test_connection(self) -> ConnectionTestResult:
        try:
            await self.login()
            shares = await self.list_children("/")
            await self.logout()
            return ConnectionTestResult(
                success=True,
                message=f"Connessione OK — {len(shares)} share visibili",
                details={"share_count": len(shares)},
            )
        except Exception as exc:
            logger.warning("Synology test_connection failed: %s", exc)
            return ConnectionTestResult(success=False, message=str(exc))

    async def list_children(
        self,
        path: str,
        exclude_presets: Optional[list[str]] = None,
    ) -> list[BrowseEntryOut]:
        presets = exclude_presets or DEFAULT_EXCLUDE_PRESETS
        path = sanitize_path(path)
        if not self._sid:
            await self.login()

        if path in ("/", ""):
            data = await self._api_get(
                "/webapi/entry.cgi",
                {
                    "api": "SYNO.FileStation.List",
                    "version": "2",
                    "method": "list_share",
                    "_sid": self._sid,
                },
            )
            shares = data.get("data", {}).get("shares", [])
            entries: list[BrowseEntryOut] = []
            for share in shares:
                name = share.get("name", "")
                share_path = share.get("path") or f"/{name}"
                excluded = is_excluded_name(name, presets)
                entries.append(
                    BrowseEntryOut(
                        name=name,
                        path=share_path,
                        is_dir=True,
                        is_excluded=excluded,
                        selectable=not excluded,
                    )
                )
            return sorted(entries, key=lambda e: e.name.lower())

        folder_path = path
        data = await self._api_get(
            "/webapi/entry.cgi",
            {
                "api": "SYNO.FileStation.List",
                "version": "2",
                "method": "list",
                "folder_path": folder_path,
                "additional": '["size"]',
                "_sid": self._sid,
            },
        )
        files = data.get("data", {}).get("files", [])
        entries = []
        for item in files:
            name = item.get("name", "")
            is_dir = item.get("isdir", False)
            item_path = f"{folder_path.rstrip('/')}/{name}"
            excluded = is_excluded_name(name, presets)
            size = None
            additional = item.get("additional") or {}
            if isinstance(additional, dict):
                size = additional.get("size")
            entries.append(
                BrowseEntryOut(
                    name=name,
                    path=item_path,
                    is_dir=is_dir,
                    is_excluded=excluded,
                    selectable=not excluded,
                    size=size if not is_dir else None,
                )
            )
        return sorted(entries, key=lambda e: (not e.is_dir, e.name.lower()))
