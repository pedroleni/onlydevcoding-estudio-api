import sqlite3
from contextlib import closing
from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Path, Query, Request, status
from starlette.responses import Response

from estudio_api.config import Config
from estudio_api.decisiones import abrir_bd
from estudio_api.lectura import (
    curso_en_disco,
    leer_cursos,
    leer_leccion,
    leer_lecciones,
)
from estudio_api.medios import servir_medio
from estudio_api.modelos import Curso, Leccion, LeccionResumen
from estudio_api.tareas import (
    CursoApp,
    borrar_curso_app,
    crear_curso_app,
    cursos_app,
)

router = APIRouter(prefix="/api")
CursoId = Annotated[str, Path(pattern=r"^[a-z0-9-]{1,40}$")]
NumeroLeccion = Annotated[int, Path(ge=1, le=999)]


def _config(request: Request) -> Config:
    return cast(Config, request.app.state.config)


@router.get("/cursos", response_model=list[Curso])
def listar_cursos(request: Request) -> list[Curso]:
    config = _config(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        return leer_cursos(config, bd)


@router.post("/cursos", response_model=Curso, status_code=status.HTTP_201_CREATED)
def dar_de_alta_curso(request: Request, curso: CursoApp) -> Curso:
    config = _config(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        if curso_en_disco(config, curso.id) or curso.id in {
            existente.id for existente in cursos_app(bd)
        }:
            raise HTTPException(status_code=409, detail="El curso ya existe")
        try:
            crear_curso_app(bd, curso)
        except sqlite3.IntegrityError as error:
            raise HTTPException(status_code=409, detail="El curso ya existe") from error
    return Curso(
        id=curso.id,
        nombre=curso.nombre,
        carpeta=None,
        lecciones=0,
        en_disco=False,
    )


@router.delete("/cursos/{curso}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_curso(request: Request, curso: CursoId) -> Response:
    config = _config(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        resultado = borrar_curso_app(bd, curso)
    if resultado == "no_existe":
        raise HTTPException(status_code=404, detail="El curso no existe")
    if resultado == "en_uso":
        raise HTTPException(status_code=409, detail="El curso tiene tareas")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/cursos/{curso}/lecciones", response_model=list[LeccionResumen])
def listar_lecciones(
    request: Request,
    curso: CursoId,
) -> list[LeccionResumen] | Response:
    config = _config(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        existe_en_app = curso in {existente.id for existente in cursos_app(bd)}
        if not curso_en_disco(config, curso) and not existe_en_app:
            return Response(status_code=404)
        lecciones = leer_lecciones(config, curso, bd)
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
