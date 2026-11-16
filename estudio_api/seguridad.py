from collections.abc import Awaitable, Callable

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import Receive, Scope, Send

AplicacionASGI = Callable[
    [Scope, Receive, Send],
    Awaitable[None],
]

HOSTS_PERMITIDOS = {"127.0.0.1:8000", "localhost:8000"}


class SeguridadLocalMiddleware:
    def __init__(self, app: AplicacionASGI, origen_web: str) -> None:
        self.app = app
        self.origen_web = origen_web

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        cabeceras = Headers(scope=scope)
        if cabeceras.get("host") not in HOSTS_PERMITIDOS:
            respuesta = PlainTextResponse("Host no permitido", status_code=400)
            await respuesta(scope, receive, send)
            return

        origen = cabeceras.get("origin")
        if origen is not None and origen != self.origen_web:
            respuesta = PlainTextResponse("Origen no permitido", status_code=403)
            await respuesta(scope, receive, send)
            return

        await self.app(scope, receive, send)
