from contextlib import closing

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from estudio_api.config import Config, cargar_config
from estudio_api.decisiones import abrir_bd
from estudio_api.rutas_api import router as router_api
from estudio_api.rutas_publicar import router as router_publicar
from estudio_api.rutas_tareas import router as router_tareas
from estudio_api.rutas_teleprompter import router as router_teleprompter
from estudio_api.seguridad import SeguridadLocalMiddleware
from estudio_api.trabajos import interrumpir_huerfanos


def crear_app(config: Config) -> FastAPI:
    with closing(abrir_bd(config.bd_ruta)) as bd:
        interrumpir_huerfanos(bd)

    # Sin /docs, /redoc ni /openapi.json: cargan JavaScript de un CDN en el
    # mismo origen que la API y podrían leer guiones y medios.
    aplicacion = FastAPI(
        title="Estudio OnlyDevCoding",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
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
        token_escritura=config.token_escritura,
    )
    aplicacion.include_router(router_api)
    aplicacion.include_router(router_publicar)
    aplicacion.include_router(router_tareas)
    aplicacion.include_router(router_teleprompter)

    @aplicacion.get("/api/salud")
    def salud() -> dict[str, bool]:
        return {"ok": True}

    return aplicacion


def crear_app_desde_entorno() -> FastAPI:
    return crear_app(cargar_config())
