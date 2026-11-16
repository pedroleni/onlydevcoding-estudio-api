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
        tipo_scope = scope["type"]
        if tipo_scope not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        cabeceras = Headers(scope=scope)
        if cabeceras.get("host") not in HOSTS_PERMITIDOS:
            await self._rechazar(
                scope,
                receive,
                send,
                mensaje="Host no permitido",
                estado=400,
            )
            return

        origen = cabeceras.get("origin")
        if origen is not None and origen != self.origen_web:
            await self._rechazar(
                scope,
                receive,
                send,
                mensaje="Origen no permitido",
                estado=403,
            )
            return

        await self.app(scope, receive, send)

    @staticmethod
    async def _rechazar(
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        mensaje: str,
        estado: int,
    ) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return

        respuesta = PlainTextResponse(mensaje, status_code=estado)
        await respuesta(scope, receive, send)
