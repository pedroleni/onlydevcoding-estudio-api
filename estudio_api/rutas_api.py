from contextlib import closing
from typing import Annotated, cast

from fastapi import APIRouter, Path, Query, Request
from starlette.responses import Response

from estudio_api.config import Config
from estudio_api.decisiones import abrir_bd
from estudio_api.lectura import leer_cursos, leer_leccion, leer_lecciones
from estudio_api.medios import servir_medio
from estudio_api.modelos import Curso, Leccion, LeccionResumen

router = APIRouter(prefix="/api")
CursoId = Annotated[str, Path(pattern=r"^[a-z0-9-]{1,40}$")]
NumeroLeccion = Annotated[int, Path(ge=1, le=999)]


def _config(request: Request) -> Config:
    return cast(Config, request.app.state.config)


@router.get("/cursos", response_model=list[Curso])
def listar_cursos(request: Request) -> list[Curso]:
    return leer_cursos(_config(request))


@router.get("/cursos/{curso}/lecciones", response_model=list[LeccionResumen])
def listar_lecciones(
    request: Request,
    curso: CursoId,
) -> list[LeccionResumen] | Response:
    config = _config(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        lecciones = leer_lecciones(config, curso, bd)
    if not lecciones:
        return Response(status_code=404)
    return lecciones


@router.get("/cursos/{curso}/lecciones/{numero}", response_model=Leccion)
def detalle_leccion(
    request: Request,
    curso: CursoId,
    numero: NumeroLeccion,
) -> Leccion | Response:
    config = _config(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        leccion = leer_leccion(config, curso, numero, bd)
    if leccion is None:
        return Response(status_code=404)
    return leccion


@router.get("/medios", response_model=None)
def obtener_medio(
    request: Request,
    ruta: str = Query(default=""),
) -> Response:
    return servir_medio(
        _config(request),
        ruta,
        request.headers.get("range"),
    )
