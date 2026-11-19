import hmac
import re
from collections.abc import Awaitable, Callable
from typing import NamedTuple

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import Receive, Scope, Send

from estudio_api.entregas import TAMANO_MAXIMO_ENTREGA

AplicacionASGI = Callable[
    [Scope, Receive, Send],
    Awaitable[None],
]

HOSTS_PERMITIDOS = {"127.0.0.1:8000", "localhost:8000"}
METODOS_LECTURA = {"GET", "HEAD", "OPTIONS"}
TAMANO_MAXIMO_CUERPO = 256 * 1024
MAXIMO_DIGITOS_CONTENT_LENGTH = 7
LIMITES_POR_RUTA: list[tuple[str, re.Pattern[str], int, int, str]] = [
    (
        "PUT",
        re.compile(
            r"^/api/cursos/[a-z0-9-]{1,40}/lecciones/"
            r"[1-9][0-9]{0,2}/grabaciones/E[0-9]{2}$"
        ),
        209_715_200,
        9,
        "Cuerpo demasiado grande",
    ),
    (
        "PUT",
        re.compile(
            r"^/api/cursos/[a-z0-9-]{1,40}/lecciones/"
            r"[1-9][0-9]{0,2}/entregas/[^/]+$"
        ),
        TAMANO_MAXIMO_ENTREGA,
        10,
        "La toma supera el límite de 4 GiB",
    ),
]


class _CuerpoDemasiadoGrande(Exception):
    pass


class _Rechazo(NamedTuple):
    mensaje: str
    estado: int


class _LimitesCuerpo(NamedTuple):
    cuerpo: int
    digitos: int
    mensaje: str


def _valores_cabecera(scope: Scope, nombre: bytes) -> list[bytes]:
    return [
        valor for clave, valor in scope.get("headers", []) if clave.lower() == nombre
    ]


def _es_escritura_http(scope: Scope) -> bool:
    return scope["type"] == "http" and scope["method"].upper() not in METODOS_LECTURA


def _limites_de_cuerpo(metodo: str, ruta: str) -> _LimitesCuerpo:
    """El primer límite de LIMITES_POR_RUTA que encaja; si ninguno, el general."""
    for metodo_limite, patron, limite, digitos, mensaje_413 in LIMITES_POR_RUTA:
        if metodo == metodo_limite and patron.fullmatch(ruta):
            return _LimitesCuerpo(limite, digitos, mensaje_413)
    return _LimitesCuerpo(
        TAMANO_MAXIMO_CUERPO, MAXIMO_DIGITOS_CONTENT_LENGTH, "Cuerpo demasiado grande"
    )


def _rechazo_de_longitud(scope: Scope, limites: _LimitesCuerpo) -> _Rechazo | None:
    """Exige un único Content-Length de dígitos ASCII dentro del límite, sin chunked."""
    if _valores_cabecera(scope, b"transfer-encoding"):
        return _Rechazo("Transfer-Encoding no permitido", 411)

    longitudes = _valores_cabecera(scope, b"content-length")
    if (
        len(longitudes) != 1
        or not longitudes[0]
        or not all(48 <= caracter <= 57 for caracter in longitudes[0])
    ):
        return _Rechazo("Falta Content-Length válido", 411)

    if len(longitudes[0]) > limites.digitos:
        return _Rechazo(limites.mensaje, 413)

    if int(longitudes[0]) > limites.cuerpo:
        return _Rechazo(limites.mensaje, 413)
    return None


class SeguridadLocalMiddleware:
    def __init__(
        self,
        app: AplicacionASGI,
        origen_web: str,
        token_escritura: str | None,
    ) -> None:
        self.app = app
        self.origen_web = origen_web
        self.token_escritura = (
            token_escritura.encode("utf-8") if token_escritura is not None else None
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        rechazo = self._rechazo_de_cabeceras(scope)
        if rechazo is not None:
            await self._rechazar(
                scope, receive, send, mensaje=rechazo.mensaje, estado=rechazo.estado
            )
            return

        if not _es_escritura_http(scope):
            await self.app(scope, receive, send)
            return

        limites = _limites_de_cuerpo(scope["method"].upper(), scope.get("path", ""))
        rechazo = _rechazo_de_longitud(scope, limites)
        if rechazo is not None:
            await self._rechazar(
                scope, receive, send, mensaje=rechazo.mensaje, estado=rechazo.estado
            )
            return

        await self._pasar_con_cuerpo_limitado(scope, receive, send, limites)

    def _rechazo_de_cabeceras(self, scope: Scope) -> _Rechazo | None:
        """Host, origen, sitio de origen y token, en este orden; None si todo vale."""
        cabeceras = Headers(scope=scope)
        if cabeceras.get("host") not in HOSTS_PERMITIDOS:
            return _Rechazo("Host no permitido", 400)

        origen = cabeceras.get("origin")
        if origen is not None and origen != self.origen_web:
            return _Rechazo("Origen no permitido", 403)

        if (
            scope["type"] == "http"
            and cabeceras.get("sec-fetch-site", "").casefold() == "cross-site"
        ):
            return _Rechazo("Sitio de origen no permitido", 403)

        requiere_token = scope["type"] == "websocket" or _es_escritura_http(scope)
        if requiere_token:
            return self._rechazo_de_token(scope)
        return None

    def _rechazo_de_token(self, scope: Scope) -> _Rechazo | None:
        if not self.token_escritura:
            return _Rechazo("Escrituras desactivadas: falta ESTUDIO_TOKEN", 503)

        tokens_recibidos = _valores_cabecera(scope, b"x-estudio-token")
        if len(tokens_recibidos) != 1 or not hmac.compare_digest(
            tokens_recibidos[0], self.token_escritura
        ):
            return _Rechazo("Token de escritura no válido", 401)
        return None

    async def _pasar_con_cuerpo_limitado(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        limites: _LimitesCuerpo,
    ) -> None:
        """Pasa la escritura a la app cortándola si el cuerpo supera lo permitido.

        ``_rechazo_de_longitud`` ya ha validado Content-Length (una sola cabecera,
        solo dígitos ASCII y dentro del límite).
        """
        longitud_declarada = int(_valores_cabecera(scope, b"content-length")[0])
        bytes_recibidos = 0

        async def recibir_limitado():
            nonlocal bytes_recibidos
            mensaje = await receive()
            if mensaje["type"] == "http.request":
                bytes_recibidos += len(mensaje.get("body", b""))
                if (
                    bytes_recibidos > limites.cuerpo
                    or bytes_recibidos > longitud_declarada
                ):
                    raise _CuerpoDemasiadoGrande
            return mensaje

        try:
            await self.app(scope, recibir_limitado, send)
        except _CuerpoDemasiadoGrande:
            await self._rechazar(
                scope,
                receive,
                send,
                mensaje=limites.mensaje,
                estado=413,
            )

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
