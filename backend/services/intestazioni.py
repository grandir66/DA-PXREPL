"""Intestazioni di sicurezza su ogni risposta (rilievo A11 del 25/11/2026).

La pagina non si lascia incorniciare da altri siti, il browser non indovina i
tipi dei file e, in https, ricorda di tornare in https.
"""

from __future__ import annotations

_FISSE = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"same-origin"),
    (b"content-security-policy", b"frame-ancestors 'none'"),
)
_HSTS = (b"strict-transport-security", b"max-age=31536000")


class IntestazioniSicurezza:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        https = scope.get("scheme") == "https"

        async def invia(msg):
            if msg["type"] == "http.response.start":
                presenti = {k.lower() for k, _ in msg.get("headers", [])}
                nuove = list(msg.get("headers", []))
                for k, v in _FISSE + ((_HSTS,) if https else ()):
                    if k not in presenti:
                        nuove.append((k, v))
                msg = {**msg, "headers": nuove}
            await send(msg)

        await self.app(scope, receive, invia)
