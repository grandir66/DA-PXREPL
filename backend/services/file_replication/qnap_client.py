"""Client QNAP QTS / QuTS hero File Station."""

from __future__ import annotations

import base64
import logging
import xml.etree.ElementTree as ET
from typing import Any, Optional

import httpx

from services.file_replication.connection_errors import format_connection_error
from services.file_replication.path_utils import is_excluded_name, sanitize_path
from services.file_replication_schemas import BrowseEntryOut, ConnectionTestResult

logger = logging.getLogger(__name__)

DEFAULT_EXCLUDE_PRESETS = ["nas_snapshots", "system_files"]


def _encode_qnap_password(password: str) -> str:
    """QNAP authLogin.cgi richiede pwd base64 (File Station API v5)."""
    return base64.b64encode(password.encode("utf-8")).decode("ascii")


def _parse_auth_response(text: str) -> ET.Element:
    try:
        return ET.fromstring(text)
    except ET.ParseError as exc:
        raise RuntimeError("Risposta QNAP non valida") from exc


def _auth_failure_message(root: ET.Element) -> str:
    err = root.findtext("errorValue") or "?"
    need_2sv = root.findtext("need_2sv")
    if need_2sv == "1":
        return (
            "Autenticazione QNAP fallita: account con verifica in 2 passaggi (2FA). "
            "Usa un utente dedicato senza 2FA oppure disabilita 2FA per questo account."
        )
    if err == "-1":
        return (
            "Autenticazione QNAP fallita: username o password errati, oppure account "
            "bloccato/scaduto. Verifica le credenziali sul pannello QNAP e reinserisci la password nell'endpoint."
        )
    return f"Autenticazione QNAP fallita (errorValue={err})"


def _qnap_base_url(host: str, port: int, use_https: bool) -> str:
    """Porta 443 = HTTPS (stunnel QNAP), 8080 = HTTP di default."""
    if port == 443 or use_https:
        scheme = "https"
    else:
        scheme = "http"
    return f"{scheme}://{host}:{port}"


def _qnap_https_fallback_url(host: str) -> Optional[str]:
    """Fallback tipico QuTS/QTS: HTTPS su 443 se HTTP :8080 non risponde."""
    return f"https://{host}:443"


class QnapClient:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        verify_ssl: bool = False,
        use_https: bool = False,
    ):
        self.host = host
        self.port = port or 8080
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self.use_https = use_https or self.port == 443
        self._sid: Optional[str] = None
        self._base = _qnap_base_url(host, self.port, self.use_https)

    async def _http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(verify=self.verify_ssl, timeout=30.0)

    async def _post(self, path: str, data: dict[str, str]) -> httpx.Response:
        urls = [f"{self._base}{path}"]
        fallback = _qnap_https_fallback_url(self.host)
        if fallback and not self._base.startswith("https://") and f"{fallback}{path}" not in urls:
            urls.append(f"{fallback}{path}")

        last_exc: Exception | None = None
        for url in urls:
            try:
                async with await self._http_client() as client:
                    resp = await client.post(url, data=data)
                    resp.raise_for_status()
                    if url != urls[0]:
                        self._base = url.rsplit(path, 1)[0]
                        logger.info("QNAP fallback attivo: %s", self._base)
                    return resp
            except httpx.HTTPError as exc:
                last_exc = exc
                logger.debug("QNAP POST %s failed: %s", url, exc)
        raise RuntimeError(format_connection_error(self.host, self.port, last_exc or RuntimeError("connessione QNAP fallita")))

    async def _get(self, path: str, params: dict[str, Any]) -> httpx.Response:
        try:
            async with await self._http_client() as client:
                resp = await client.get(f"{self._base}{path}", params=params)
                resp.raise_for_status()
                return resp
        except httpx.HTTPError as exc:
            raise RuntimeError(format_connection_error(self.host, self.port, exc)) from exc

    async def login(self) -> str:
        attempts = (
            ("base64", _encode_qnap_password(self.password)),
            ("plain", self.password),
        )
        last_root: ET.Element | None = None
        for mode, pwd in attempts:
            resp = await self._post(
                "/cgi-bin/authLogin.cgi",
                {"user": self.username, "pwd": pwd},
            )
            root = _parse_auth_response(resp.text)
            if root.findtext("authPassed") == "1":
                sid = root.findtext("authSid")
                if not sid:
                    raise RuntimeError("SID QNAP mancante")
                self._sid = sid
                if mode == "plain":
                    logger.debug("QNAP login riuscito con password plain (legacy)")
                return sid
            last_root = root
            logger.debug("QNAP login %s failed errorValue=%s", mode, root.findtext("errorValue"))

        raise RuntimeError(_auth_failure_message(last_root) if last_root is not None else "Autenticazione QNAP fallita")

    async def logout(self) -> None:
        if not self._sid:
            return
        try:
            await self._get("/cgi-bin/authLogout.cgi", {"sid": self._sid})
        except Exception as exc:
            logger.debug("QNAP logout: %s", exc)
        finally:
            self._sid = None

    async def get_firmware_version(self) -> str:
        try:
            resp = await self._get("/cgi-bin/sys/sysRequest.cgi", {"subfunc": "firm_get"})
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
                message=f"Connessione QNAP OK ({self._base}) — {len(shares)} voci visibili",
                details={"firmware": version, "entry_count": len(shares), "base_url": self._base},
            )
        except Exception as exc:
            logger.warning("QNAP test_connection failed: %s", exc)
            return ConnectionTestResult(success=False, message=str(exc))

    async def _file_station(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._sid:
            await self.login()
        params = {**params, "sid": self._sid}
        resp = await self._get("/cgi-bin/filemanager/utilRequest.cgi", params)
        try:
            data = resp.json()
        except ValueError as exc:
            raise RuntimeError("Risposta File Station QNAP non JSON") from exc
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
