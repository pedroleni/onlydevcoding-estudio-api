import json
import threading
from contextlib import closing
from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Path, Request
from pydantic import BaseModel, ConfigDict
from starlette.responses import Response

from estudio_api.config import Config
from estudio_api.decisiones import (
    abrir_bd,
    elegir_portada,
    fijar_estado,
)
from estudio_api.escritura import escribir_atomico
from estudio_api.guia import regenerar_guia
from estudio_api.lectura import carpeta_leccion, leer_cursos, leer_leccion
from estudio_api.modelos import EstadoRed
from estudio_api.publicacion import (
    PATRON_ID_PIEZA,
    PiezaPublicacion,
    Publicacion,
    Red,
    TextosRed,
    _raiz_publicar,
    leer_publicacion,
    ruta_publica_publicar,
    ruta_relativa_publicar,
    validar_textos,
)
from estudio_api.rutas import ruta_segura
from estudio_api.rutas_api import CursoId, NumeroLeccion
from estudio_api.vista_publicacion import VistaPublicacion, construir_vista_publicacion

router = APIRouter(prefix="/api")
_BLOQUEO_CAMBIO_TEXTOS = threading.Lock()
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


@router.put(
    "/cursos/{curso}/lecciones/{numero}/publicacion/piezas/{pieza}/redes/{red}/textos",
    response_model=VistaPublicacion,
)
def cambiar_textos(
    request: Request,
    textos: TextosRed,
    curso: CursoId,
    numero: NumeroLeccion,
    pieza: PiezaId,
    red: RedId,
) -> VistaPublicacion | Response:
    try:
        validar_textos(red, textos)
    except ValueError as error:
        mensaje_validacion = str(error)
        raise HTTPException(status_code=422, detail=mensaje_validacion) from error

    config = _config(request)
    carpeta = carpeta_leccion(config, curso, numero)
    if carpeta is None:
        return Response(status_code=404)
    publicar = _raiz_publicar(config, carpeta)
    if publicar is None:
        raise HTTPException(
            status_code=409,
            detail="La carpeta publicar no es válida",
        )
    if not publicar.is_dir():
        raise HTTPException(
            status_code=409,
            detail="La lección no tiene carpeta publicar",
        )
    try:
        ruta_json = ruta_segura(publicar, "publicacion.json")
    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail="La carpeta publicar no es válida",
        ) from error
    if (
        textos.video is not None
        and ruta_publica_publicar(config, carpeta, textos.video) is None
    ):
        raise HTTPException(
            status_code=422,
            detail="El vídeo debe ser un archivo válido dentro de publicar",
        )

    with _BLOQUEO_CAMBIO_TEXTOS:
        lectura = leer_publicacion(config, carpeta, filtrar=False)
        if lectura.error is not None:
            raise HTTPException(
                status_code=409,
                detail="Arregla publicacion.json antes de editar desde la app",
            )

        publicacion = lectura.publicacion or Publicacion(version=1, piezas={})
        leccion = leer_leccion(config, curso, numero)
        if leccion is None:
            return Response(status_code=404)
        piezas_existentes = {elemento.id for elemento in leccion.piezas}
        piezas_existentes.update(publicacion.piezas)
        if pieza not in piezas_existentes:
            return Response(status_code=404)

        publicacion = publicacion.model_copy(deep=True)
        pieza_publicacion = publicacion.piezas.setdefault(pieza, PiezaPublicacion())
        pieza_publicacion.redes[red] = textos
        contenido = (
            json.dumps(
                publicacion.model_dump(
                    mode="json",
                    exclude_none=True,
                    exclude_defaults=True,
                ),
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        escribir_atomico(ruta_json, contenido)

        with closing(abrir_bd(config.bd_ruta)) as bd:
            resultado = construir_vista_publicacion(config, curso, numero, bd)
        assert resultado is not None
        portadas_validas = {
            elemento.id: relativa
            for elemento in resultado.piezas
            if elemento.portada_elegida is not None
            and (
                relativa := ruta_relativa_publicar(
                    config,
                    carpeta,
                    elemento.portada_elegida,
                )
            )
            is not None
        }
        titulos_piezas = {elemento.id: elemento.titulo for elemento in resultado.piezas}
        curso_nombre = next(
            (
                elemento.nombre
                for elemento in leer_cursos(config)
                if elemento.id == curso
            ),
            curso,
        )
        resultado.aviso = regenerar_guia(
            config,
            carpeta,
            numero,
            curso_nombre,
            publicacion,
            portadas_validas,
            titulos_piezas,
        )
        return resultado
