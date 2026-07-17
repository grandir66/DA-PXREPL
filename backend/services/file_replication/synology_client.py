"""Client Synology DSM File Station."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

import httpx

from services.file_replication.connection_errors import format_connection_error
from services.file_replication.path_utils import is_excluded_name, sanitize_path
from services.file_replication_schemas import BrowseEntryOut, ConnectionTestResult

logger = logging.getLogger(__name__)

DEFAULT_EXCLUDE_PRESETS = ["nas_snapshots", "system_files"]
_SESSION_TTL_SEC = 900
_SESSION_RETRY_CODES = {106, 107, 119}

_session_cache: dict[str, tuple[str, Optional[str], float]] = {}
_session_locks: dict[str, asyncio.Lock] = {}


def _session_key(host: str, port: int, username: str) -> str:
    return f"{host}:{port}:{username}"


def _session_lock(key: str) -> asyncio.Lock:
    if key not in _session_locks:
        _session_locks[key] = asyncio.Lock()
    return _session_locks[key]


def _clear_session_cache(key: str) -> None:
    _session_cache.pop(key, None)


def _synology_error_message(code: int | str) -> str:
    messages = {
        106: "Sessione Synology scaduta",
        107: "Sessione Synology interrotta (login duplicato)",
        119: "Sessione Synology non valida (SID scaduto)",
    }
    try:
        icode = int(code)
    except (TypeError, ValueError):
        return f"Synology API error {code}"
    base = messages.get(icode, f"Synology API error {icode}")
    if icode in _SESSION_RETRY_CODES:
        return f"{base} — riprova ad espandere la cartella"
    return base


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
        self._synotoken: Optional[str] = None
        self._base = _synology_base_url(host, self.port)
        self._session_key = _session_key(host, self.port, username)

    def _auth_headers(self) -> dict[str, str]:
        if self._synotoken:
            return {"X-SYNO-TOKEN": self._synotoken}
        return {}

    async def _api_get(
        self,
        path: str,
        params: dict[str, Any],
        *,
        retry_auth: bool = True,
    ) -> dict[str, Any]:
        req_params = dict(params)
        if self._sid:
            req_params["_sid"] = self._sid

        try:
            async with httpx.AsyncClient(verify=self.verify_ssl, timeout=30.0) as client:
                resp = await client.get(
                    f"{self._base}{path}",
                    params=req_params,
                    headers=self._auth_headers(),
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(format_connection_error(self.host, self.port, exc)) from exc

        if data.get("success"):
            return data

        err = data.get("error", {})
        code = err.get("code", "unknown")
        if retry_auth and code in _SESSION_RETRY_CODES:
            logger.info("Synology session %s on %s — re-login", code, self.host)
            await self._invalidate_session()
            await self.login(force=True)
            return await self._api_get(path, params, retry_auth=False)

        raise RuntimeError(_synology_error_message(code))

    async def _invalidate_session(self) -> None:
        self._sid = None
        self._synotoken = None
        _clear_session_cache(self._session_key)

    async def _ensure_session(self) -> None:
        cached = _session_cache.get(self._session_key)
        if cached and cached[2] > time.time():
            self._sid, self._synotoken, _ = cached
            return
        await self.login(force=True)

    async def login(self, *, force: bool = False) -> str:
        lock = _session_lock(self._session_key)
        async with lock:
            if not force:
                cached = _session_cache.get(self._session_key)
                if cached and cached[2] > time.time():
                    self._sid, self._synotoken, _ = cached
                    return self._sid

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
                    "enable_syno_token": "yes",
                },
                retry_auth=False,
            )
            payload = data.get("data") or {}
            self._sid = payload["sid"]
            self._synotoken = payload.get("synotoken")
            _session_cache[self._session_key] = (
                self._sid,
                self._synotoken,
                time.time() + _SESSION_TTL_SEC,
            )
            return self._sid

    async def logout(self) -> None:
        sid = self._sid
        if not sid:
            return
        try:
            await self._api_get(
                "/webapi/auth.cgi",
                {
                    "api": "SYNO.API.Auth",
                    "version": "7",
                    "method": "logout",
                    "session": "FileStation",
                    "_sid": sid,
                },
                retry_auth=False,
            )
        except Exception as exc:
            logger.debug("Synology logout: %s", exc)
        finally:
            await self._invalidate_session()

    async def test_connection(self) -> ConnectionTestResult:
        try:
            await self._ensure_session()
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
        await self._ensure_session()

        if path in ("/", ""):
            data = await self._api_get(
                "/webapi/entry.cgi",
                {
                    "api": "SYNO.FileStation.List",
                    "version": "2",
                    "method": "list_share",
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
