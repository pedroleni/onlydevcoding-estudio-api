from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.types import Receive, Scope, Send

from estudio_api.config import Config, cargar_config
from estudio_api.seguridad import SeguridadLocalMiddleware


def crear_app(config: Config) -> FastAPI:
    aplicacion = FastAPI(title="Estudio OnlyDevCoding")
    aplicacion.state.config = config
    aplicacion.add_middleware(
        CORSMiddleware,
        allow_origins=[config.origen_web],
        allow_methods=["GET"],
        allow_headers=[],
    )
    aplicacion.add_middleware(
        SeguridadLocalMiddleware,
        origen_web=config.origen_web,
    )

    @aplicacion.get("/api/salud")
    def salud() -> dict[str, bool]:
        return {"ok": True}

    return aplicacion


class _AplicacionPerezosa:
    def __init__(self) -> None:
        self._aplicacion: FastAPI | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._aplicacion is None:
            self._aplicacion = crear_app(cargar_config())
        await self._aplicacion(scope, receive, send)


app = _AplicacionPerezosa()
