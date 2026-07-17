"""Client QNAP QTS / QuTS hero File Station."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Any, Optional

import httpx

from services.file_replication.path_utils import is_excluded_name, sanitize_path
from services.file_replication_schemas import BrowseEntryOut, ConnectionTestResult

logger = logging.getLogger(__name__)

DEFAULT_EXCLUDE_PRESETS = ["nas_snapshots", "system_files"]


class QnapClient:
    def __init__(self, host: str, port: int, username: str, password: str):
        self.host = host
        self.port = port or 8080
        self.username = username
        self.password = password
        self._sid: Optional[str] = None
        self._base = f"http://{host}:{self.port}"

    async def login(self) -> str:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._base}/cgi-bin/authLogin.cgi",
                data={"user": self.username, "pwd": self.password},
            )
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            auth_passed = root.findtext("authPassed")
            if auth_passed != "1":
                raise RuntimeError("Autenticazione QNAP fallita")
            sid = root.findtext("authSid")
            if not sid:
                raise RuntimeError("SID QNAP mancante")
            self._sid = sid
            return sid

    async def logout(self) -> None:
        if not self._sid:
            return
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                await client.get(
                    f"{self._base}/cgi-bin/authLogout.cgi",
                    params={"sid": self._sid},
                )
        except Exception as exc:
            logger.debug("QNAP logout: %s", exc)
        finally:
            self._sid = None

    async def get_firmware_version(self) -> str:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(f"{self._base}/cgi-bin/sys/sysRequest.cgi", params={"subfunc": "firm_get"})
                if resp.status_code == 200 and "hero" in resp.text.lower():
                    return "QuTS hero"
        except Exception:
            pass
        return "unknown"

    async def test_connection(self) -> ConnectionTestResult:
        try:
            await self.login()
            version = await self.get_firmware_version()
            shares = await self.list_children("/")
            await self.logout()
            return ConnectionTestResult(
                success=True,
                message=f"Connessione QNAP OK — {len(shares)} voci visibili",
                details={"firmware": version, "entry_count": len(shares)},
            )
        except Exception as exc:
            logger.warning("QNAP test_connection failed: %s", exc)
            return ConnectionTestResult(success=False, message=str(exc))

    async def _file_station(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._sid:
            await self.login()
        params = {**params, "sid": self._sid}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self._base}/cgi-bin/filemanager/utilRequest.cgi",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != 1:
                raise RuntimeError(data.get("detail") or "Errore File Station QNAP")
            return data

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
            data = await self._file_station({"func": "get_tree", "node": "share_root"})
            nodes = data.get("datas") or []
            entries: list[BrowseEntryOut] = []
            for node in nodes:
                name = node.get("text") or node.get("filename") or ""
                if not name:
                    continue
                share_path = f"/{name}"
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

        folder = path if path.startswith("/") else f"/{path}"
        data = await self._file_station(
            {
                "func": "get_list",
                "path": folder,
                "limit": 500,
                "start": 0,
                "sort": "filename",
                "dir": "ASC",
            }
        )
        items = data.get("datas") or []
        entries = []
        for item in items:
            name = item.get("filename") or item.get("name") or ""
            if not name:
                continue
            is_dir = item.get("isfolder") in (True, 1, "1")
            item_path = f"{folder.rstrip('/')}/{name}"
            excluded = is_excluded_name(name, presets)
            size_raw = item.get("filesize") or item.get("size")
            size = int(size_raw) if size_raw not in (None, "") and not is_dir else None
            entries.append(
                BrowseEntryOut(
                    name=name,
                    path=item_path,
                    is_dir=is_dir,
                    is_excluded=excluded,
                    selectable=not excluded,
                    size=size,
                )
            )
        return sorted(entries, key=lambda e: (not e.is_dir, e.name.lower()))
