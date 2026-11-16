from collections.abc import Awaitable, Callable

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import Message, Receive, Scope, Send

AplicacionASGI = Callable[
    [Scope, Receive, Send],
    Awaitable[None],
]

HOSTS_PERMITIDOS = {"127.0.0.1:8000", "localhost:8000"}
RUTA_MEDIOS = "/api/medios"
CORP_SAME_SITE = (b"cross-origin-resource-policy", b"same-site")


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
        enviar = send
        if tipo_scope == "http" and scope.get("path") == RUTA_MEDIOS:

            async def enviar_con_corp(mensaje: Message) -> None:
                if mensaje["type"] == "http.response.start":
                    mensaje = dict(mensaje)
                    mensaje["headers"] = [
                        *mensaje.get("headers", []),
                        CORP_SAME_SITE,
                    ]
                await send(mensaje)

            enviar = enviar_con_corp

        if cabeceras.get("host") not in HOSTS_PERMITIDOS:
            await self._rechazar(
                scope,
                receive,
                enviar,
                mensaje="Host no permitido",
                estado=400,
            )
            return

        origen = cabeceras.get("origin")
        if origen is not None and origen != self.origen_web:
            await self._rechazar(
                scope,
                receive,
                enviar,
                mensaje="Origen no permitido",
                estado=403,
            )
            return

        if (
            tipo_scope == "http"
            and cabeceras.get("sec-fetch-site", "").casefold() == "cross-site"
        ):
            await self._rechazar(
                scope,
                receive,
                enviar,
                mensaje="Sitio de origen no permitido",
                estado=403,
            )
            return

        await self.app(scope, receive, enviar)

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
