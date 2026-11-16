from contextlib import closing
from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Path, Request
from pydantic import BaseModel, ConfigDict
from starlette.responses import Response

from estudio_api.config import Config
from estudio_api.decisiones import abrir_bd, elegir_portada, fijar_estado
from estudio_api.modelos import EstadoRed
from estudio_api.publicacion import PATRON_ID_PIEZA, Red
from estudio_api.rutas_api import CursoId, NumeroLeccion
from estudio_api.vista_publicacion import VistaPublicacion, construir_vista_publicacion

router = APIRouter(prefix="/api")
PiezaId = Annotated[str, Path(pattern=PATRON_ID_PIEZA.pattern)]
RedId = Annotated[Red, Path()]


class EleccionPortada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ruta: str


def _config(request: Request) -> Config:
    return cast(Config, request.app.state.config)


@router.get(
    "/cursos/{curso}/lecciones/{numero}/publicacion",
    response_model=VistaPublicacion,
)
def obtener_publicacion(
    request: Request,
    curso: CursoId,
    numero: NumeroLeccion,
) -> VistaPublicacion | Response:
    config = _config(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        vista = construir_vista_publicacion(config, curso, numero, bd)
    if vista is None:
        return Response(status_code=404)
    return vista


@router.put(
    "/cursos/{curso}/lecciones/{numero}/publicacion/piezas/{pieza}/portada",
    response_model=VistaPublicacion,
)
def cambiar_portada(
    request: Request,
    eleccion: EleccionPortada,
    curso: CursoId,
    numero: NumeroLeccion,
    pieza: PiezaId,
) -> VistaPublicacion | Response:
    config = _config(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        vista = construir_vista_publicacion(config, curso, numero, bd)
        if vista is None:
            return Response(status_code=404)
        pieza_vista = next(
            (elemento for elemento in vista.piezas if elemento.id == pieza),
            None,
        )
        if pieza_vista is None:
            return Response(status_code=404)
        if eleccion.ruta not in pieza_vista.portadas:
            raise HTTPException(status_code=422, detail="La portada no es candidata")
        elegir_portada(bd, curso, numero, pieza, eleccion.ruta)
        resultado = construir_vista_publicacion(config, curso, numero, bd)
    assert resultado is not None
    return resultado


@router.put(
    "/cursos/{curso}/lecciones/{numero}/publicacion/piezas/{pieza}/redes/{red}/estado",
    response_model=VistaPublicacion,
)
def cambiar_estado(
    request: Request,
    nuevo_estado: EstadoRed,
    curso: CursoId,
    numero: NumeroLeccion,
    pieza: PiezaId,
    red: RedId,
) -> VistaPublicacion | Response:
    config = _config(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        vista = construir_vista_publicacion(config, curso, numero, bd)
        if vista is None:
            return Response(status_code=404)
        if all(elemento.id != pieza for elemento in vista.piezas):
            return Response(status_code=404)
        fijar_estado(bd, curso, numero, pieza, red, nuevo_estado)
        resultado = construir_vista_publicacion(config, curso, numero, bd)
    assert resultado is not None
    return resultado
