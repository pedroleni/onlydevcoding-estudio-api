from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from estudio_api.config import Config, cargar_config
from estudio_api.rutas_api import router as router_api
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
    aplicacion.include_router(router_api)

    @aplicacion.get("/api/salud")
    def salud() -> dict[str, bool]:
        return {"ok": True}

    return aplicacion


def crear_app_desde_entorno() -> FastAPI:
    return crear_app(cargar_config())
