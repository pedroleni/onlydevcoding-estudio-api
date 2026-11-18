import sqlite3
from collections.abc import Collection
from contextlib import closing
from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Path, Query, Request, status
from starlette.responses import Response

from estudio_api.config import Config
from estudio_api.decisiones import abrir_bd
from estudio_api.lectura import (
    curso_en_disco,
    curso_existe,
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
)
from estudio_api.trabajos import hay_trabajo_en_leccion

router = APIRouter(prefix="/api")
CursoId = Annotated[str, Path(pattern=r"^[a-z0-9-]{1,40}$")]
NumeroLeccion = Annotated[int, Path(ge=1, le=999)]
TrabajoId = Annotated[int, Path(ge=1, le=2**63 - 1)]


LECCION_OCUPADA = (
    "No se puede cambiar mientras se prepara esta lección. "
    "Espera a que termine el trabajo."
)


def config_peticion(request: Request) -> Config:
    """Configuración de la app que atiende la petición (común a los routers)."""
    return cast(Config, request.app.state.config)


def exigir_leccion_libre(
    config: Config,
    curso: str,
    numero: int,
    acciones: Collection[str],
) -> None:
    """409 si alguna de ``acciones`` está en marcha en la lección."""
    with closing(abrir_bd(config.bd_ruta)) as bd:
        ocupada = hay_trabajo_en_leccion(bd, curso, numero, acciones)
    if ocupada:
        raise HTTPException(status_code=409, detail=LECCION_OCUPADA)


@router.get("/cursos", response_model=list[Curso])
def listar_cursos(request: Request) -> list[Curso]:
    config = config_peticion(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        return leer_cursos(config, bd)


@router.post("/cursos", response_model=Curso, status_code=status.HTTP_201_CREATED)
def dar_de_alta_curso(request: Request, curso: CursoApp) -> Curso:
    config = config_peticion(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        if curso_existe(config, bd, curso.id):
            raise HTTPException(status_code=409, detail="El curso ya existe")
        try:
            crear_curso_app(bd, curso)
        except sqlite3.IntegrityError as error:
            raise HTTPException(status_code=409, detail="El curso ya existe") from error
    # Si ya había una carpeta vacía con ese id, el listado la mostrará como curso de disco.
    return Curso(
        id=curso.id,
        nombre=curso.nombre,
        carpeta=None,
        lecciones=0,
        en_disco=curso_en_disco(config, curso.id),
    )


@router.delete("/cursos/{curso}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_curso(request: Request, curso: CursoId) -> Response:
    config = config_peticion(request)
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
    config = config_peticion(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        if not curso_existe(config, bd, curso):
            return Response(status_code=404)
        lecciones = leer_lecciones(config, curso, bd)
    return lecciones


@router.get("/cursos/{curso}/lecciones/{numero}", response_model=Leccion)
def detalle_leccion(
    request: Request,
    curso: CursoId,
    numero: NumeroLeccion,
) -> Leccion | Response:
    config = config_peticion(request)
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
        config_peticion(request),
        ruta,
        request.headers.get("range"),
    )
