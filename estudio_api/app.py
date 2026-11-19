from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, closing

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from estudio_api.config import Config, cargar_config
from estudio_api.decisiones import abrir_bd
from estudio_api.rutas_acciones import router as router_acciones
from estudio_api.rutas_api import router as router_api
from estudio_api.rutas_entregas import router as router_entregas
from estudio_api.rutas_publicar import router as router_publicar
from estudio_api.rutas_reels import router as router_reels
from estudio_api.rutas_tareas import router as router_tareas
from estudio_api.rutas_teleprompter import router as router_teleprompter
from estudio_api.seguridad import SeguridadLocalMiddleware
from estudio_api.trabajos import apagar_trabajos, interrumpir_huerfanos


def crear_app(config: Config) -> FastAPI:
    with closing(abrir_bd(config.bd_ruta)) as bd:
        interrumpir_huerfanos(bd)

    @asynccontextmanager
    async def ciclo_de_vida(_aplicacion: FastAPI) -> AsyncIterator[None]:
        yield
        # El render va en su propia sesión y Ctrl-C ya no le llega: se para aquí.
        apagar_trabajos(config.bd_ruta)

    # Sin /docs, /redoc ni /openapi.json: cargan JavaScript de un CDN en el
    # mismo origen que la API y podrían leer guiones y medios.
    aplicacion = FastAPI(
        title="Estudio OnlyDevCoding",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=ciclo_de_vida,
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
    aplicacion.include_router(router_acciones)
    aplicacion.include_router(router_publicar)
    aplicacion.include_router(router_tareas)
    aplicacion.include_router(router_teleprompter)
    aplicacion.include_router(router_entregas)
    aplicacion.include_router(router_reels)

    @aplicacion.get("/api/salud")
    def salud() -> dict[str, bool]:
        return {"ok": True}

    return aplicacion


def crear_app_desde_entorno() -> FastAPI:
    return crear_app(cargar_config())
