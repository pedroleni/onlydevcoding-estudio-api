import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from estudio_api.config import Config
from estudio_api.decisiones import estados, portadas_elegidas
from estudio_api.estado import REDES
from estudio_api.lectura import carpeta_leccion, leer_leccion
from estudio_api.modelos import EstadoRed, Pieza
from estudio_api.publicacion import (
    LecturaPublicacion,
    PiezaPublicacion,
    Red,
    TextosRed,
    clave_pieza,
    leer_publicacion,
    portadas_candidatas,
    ruta_publica_publicar,
)

TipoPieza = Literal["leccion", "reel", "short"]


class RedVista(BaseModel):
    red: Red
    textos: TextosRed | None = None
    estado: EstadoRed


class PiezaVista(BaseModel):
    id: str
    tipo: TipoPieza
    titulo: str
    video: str | None = None
    duracion: str | None = None
    fecha_propuesta: str | None = None
    portadas: list[str] = Field(default_factory=list)
    portada_elegida: str | None = None
    redes: list[RedVista] = Field(default_factory=list)


class VistaPublicacion(BaseModel):
    curso: str
    numero: int
    piezas: list[PiezaVista] = Field(default_factory=list)
    despues_de_publicar: list[str] = Field(default_factory=list)
    notas: str | None = None
    error: str | None = None
    guia: str | None = None
    aviso: str | None = None


@dataclass(frozen=True)
class _ContextoPieza:
    config: Config
    carpeta: Path | None
    elegidas: Mapping[str, str]
    estados_guardados: Mapping[tuple[str, str], EstadoRed]


def _tipo_pieza(identificador: str) -> TipoPieza:
    if identificador == "leccion":
        return "leccion"
    if identificador.startswith("reel-salida"):
        return "reel"
    return "short"


def _ruta_json(
    config: Config,
    carpeta: Path | None,
    relativa: str | None,
) -> str | None:
    if carpeta is None or relativa is None:
        return None
    return ruta_publica_publicar(config, carpeta, relativa)


def _textos_vista(
    config: Config,
    carpeta: Path | None,
    datos: PiezaPublicacion | None,
    red: Red,
) -> TextosRed | None:
    textos = datos.redes.get(red) if datos is not None else None
    if textos is None or textos.video is None:
        return textos
    return textos.model_copy(
        update={"video": _ruta_json(config, carpeta, textos.video)}
    )


def _construir_pieza(
    contexto: _ContextoPieza,
    identificador: str,
    disco: Pieza | None,
    datos: PiezaPublicacion | None,
) -> PiezaVista:
    portadas = portadas_candidatas(
        contexto.config,
        contexto.carpeta,
        list(disco.portadas) if disco is not None else [],
        datos,
    )
    elegida = contexto.elegidas.get(identificador)

    video_json = _ruta_json(
        contexto.config,
        contexto.carpeta,
        datos.video if datos else None,
    )
    if datos is not None and datos.titulo and datos.titulo.strip():
        titulo = datos.titulo
    elif disco is not None:
        titulo = disco.titulo
    else:
        titulo = identificador.replace("-", " ").capitalize()

    redes = [
        RedVista(
            red=red,
            textos=_textos_vista(contexto.config, contexto.carpeta, datos, red),
            estado=contexto.estados_guardados.get(
                (identificador, red),
                EstadoRed(estado="pendiente"),
            ),
        )
        for red in REDES
    ]
    return PiezaVista(
        id=identificador,
        tipo=disco.tipo if disco is not None else _tipo_pieza(identificador),
        titulo=titulo,
        video=video_json or (disco.video if disco else None),
        duracion=datos.duracion if datos is not None else None,
        fecha_propuesta=datos.fecha_propuesta if datos is not None else None,
        portadas=portadas,
        portada_elegida=elegida if elegida in portadas else None,
        redes=redes,
    )


def construir_vista_publicacion(
    config: Config,
    curso: str,
    numero: int,
    bd: sqlite3.Connection,
) -> VistaPublicacion | None:
    leccion = leer_leccion(config, curso, numero)
    if leccion is None:
        return None

    carpeta = carpeta_leccion(config, curso, numero)
    lectura: LecturaPublicacion = leer_publicacion(config, carpeta)
    publicacion = lectura.publicacion
    piezas_disco = {pieza.id: pieza for pieza in leccion.piezas}
    piezas_json = publicacion.piezas if publicacion is not None else {}
    identificadores = sorted(set(piezas_disco) | set(piezas_json), key=clave_pieza)
    elegidas = portadas_elegidas(bd, curso, numero)
    estados_guardados = estados(bd, curso, numero)
    contexto_pieza = _ContextoPieza(config, carpeta, elegidas, estados_guardados)

    return VistaPublicacion(
        curso=curso,
        numero=numero,
        piezas=[
            _construir_pieza(
                contexto_pieza,
                identificador,
                piezas_disco.get(identificador),
                piezas_json.get(identificador),
            )
            for identificador in identificadores
        ],
        despues_de_publicar=(
            publicacion.despues_de_publicar if publicacion is not None else []
        ),
        notas=publicacion.notas if publicacion is not None else None,
        error=lectura.error,
        guia=None,
        aviso=None,
    )
