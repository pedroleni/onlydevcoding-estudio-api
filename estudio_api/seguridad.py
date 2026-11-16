import hmac
from collections.abc import Awaitable, Callable

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import Receive, Scope, Send

AplicacionASGI = Callable[
    [Scope, Receive, Send],
    Awaitable[None],
]

HOSTS_PERMITIDOS = {"127.0.0.1:8000", "localhost:8000"}
METODOS_LECTURA = {"GET", "HEAD", "OPTIONS"}
TAMANO_MAXIMO_CUERPO = 256 * 1024


class SeguridadLocalMiddleware:
    def __init__(
        self,
        app: AplicacionASGI,
        origen_web: str,
        token_escritura: str | None,
    ) -> None:
        self.app = app
        self.origen_web = origen_web
        self.token_escritura = token_escritura

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

        if (
            tipo_scope == "http"
            and cabeceras.get("sec-fetch-site", "").casefold() == "cross-site"
        ):
            await self._rechazar(
                scope,
                receive,
                send,
                mensaje="Sitio de origen no permitido",
                estado=403,
            )
            return

        if tipo_scope == "http" and scope["method"].upper() not in METODOS_LECTURA:
            if not self.token_escritura:
                await self._rechazar(
                    scope,
                    receive,
                    send,
                    mensaje="Escrituras desactivadas: falta ESTUDIO_TOKEN",
                    estado=503,
                )
                return

            token_recibido = cabeceras.get("x-estudio-token")
            if token_recibido is None or not hmac.compare_digest(
                token_recibido,
                self.token_escritura,
            ):
                await self._rechazar(
                    scope,
                    receive,
                    send,
                    mensaje="Token de escritura no válido",
                    estado=401,
                )
                return

            longitudes = cabeceras.getlist("content-length")
            if (
                len(longitudes) != 1
                or not longitudes[0].isascii()
                or not longitudes[0].isdecimal()
            ):
                await self._rechazar(
                    scope,
                    receive,
                    send,
                    mensaje="Falta Content-Length válido",
                    estado=411,
                )
                return

            if int(longitudes[0]) > TAMANO_MAXIMO_CUERPO:
                await self._rechazar(
                    scope,
                    receive,
                    send,
                    mensaje="Cuerpo demasiado grande",
                    estado=413,
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
