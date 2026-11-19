"""Ganchos verticales (reels) por grabar y temario completo de un curso."""

import sqlite3
from datetime import datetime

from pydantic import BaseModel

from estudio_api.camara import _entregados
from estudio_api.config import Config
from estudio_api.decisiones import ganchos_grabados, marcar_gancho_grabado
from estudio_api.lectura import _leer_json, _texto, datos_curso
from estudio_api.rutas import ruta_segura

ARCHIVO_TEMARIO = "TEMARIO.json"
MAX_LECCIONES_TEMARIO = 999


class GanchoReel(BaseModel):
    id: str
    titulo: str
    texto: str
    # Grabado a mano en el teleprompter o con la toma ya entregada.
    grabado: bool
    entregado: bool


class LeccionReels(BaseModel):
    numero: int
    titulo: str
    ganchos: list[GanchoReel]


class ReelsCurso(BaseModel):
    lecciones: list[LeccionReels]


class LeccionTemario(BaseModel):
    numero: int
    titulo: str
    modulo: str | None


class Temario(BaseModel):
    lecciones: list[LeccionTemario]


def _ganchos_guion(guion: dict[str, object]) -> list[tuple[str, str, str]]:
    valor = guion.get("ganchos")
    ganchos: list[tuple[str, str, str]] = []
    for datos in valor if isinstance(valor, list) else []:
        if not isinstance(datos, dict):
            continue
        identificador = datos.get("id")
        texto = datos.get("texto")
        if not isinstance(identificador, str) or not isinstance(texto, str):
            continue
        titulo = _texto(datos.get("titulo")) or identificador
        ganchos.append((identificador, titulo, texto))
    return ganchos


def leer_reels(config: Config, bd: sqlite3.Connection, curso: str) -> ReelsCurso | None:
    leido = datos_curso(config, curso)
    if leido is None:
        return None
    grabados = ganchos_grabados(bd, curso)
    lecciones: list[LeccionReels] = []
    for numero in sorted(leido[2]):
        _, _, guion, ruta_guion, _ = leido[2][numero]
        ganchos = _ganchos_guion(guion)
        if not ganchos:
            continue
        entregados = _entregados(config, numero, ruta_guion.stem)
        lecciones.append(
            LeccionReels(
                numero=numero,
                titulo=_texto(guion.get("titulo")) or f"Lección {numero}",
                ganchos=[
                    GanchoReel(
                        id=identificador,
                        titulo=titulo,
                        texto=texto,
                        grabado=(numero, identificador) in grabados
                        or identificador in entregados,
                        entregado=identificador in entregados,
                    )
                    for identificador, titulo, texto in ganchos
                ],
            )
        )
    return ReelsCurso(lecciones=lecciones)


def gancho_existe(config: Config, curso: str, numero: int, gancho: str) -> bool:
    leido = datos_curso(config, curso)
    if leido is None or numero not in leido[2]:
        return False
    return any(
        identificador == gancho
        for identificador, _, _ in _ganchos_guion(leido[2][numero][2])
    )


def guardar_gancho_grabado(
    bd: sqlite3.Connection, curso: str, numero: int, gancho: str, grabado: bool
) -> None:
    fecha = datetime.now().astimezone().replace(microsecond=0).isoformat()
    marcar_gancho_grabado(bd, curso, numero, gancho, grabado, fecha)


def leer_temario(config: Config, curso: str) -> Temario | None:
    """Lecciones previstas del curso según ``TEMARIO.json`` en su carpeta.

    Sin archivo (o con uno ilegible) el curso no tiene temario: lista vacía.
    """
    leido = datos_curso(config, curso)
    if leido is None:
        return None
    try:
        datos = _leer_json(ruta_segura(leido[0], ARCHIVO_TEMARIO))
    except ValueError:
        datos = None
    valor = datos.get("lecciones") if datos is not None else None
    lecciones: dict[int, LeccionTemario] = {}
    for entrada in valor if isinstance(valor, list) else []:
        if not isinstance(entrada, dict):
            continue
        numero = entrada.get("numero")
        titulo = entrada.get("titulo")
        if (
            not isinstance(numero, int)
            or isinstance(numero, bool)
            or not 1 <= numero <= MAX_LECCIONES_TEMARIO
            or not isinstance(titulo, str)
            or not titulo.strip()
        ):
            continue
        modulo = entrada.get("modulo")
        lecciones.setdefault(
            numero,
            LeccionTemario(
                numero=numero,
                titulo=titulo.strip(),
                modulo=modulo.strip()
                if isinstance(modulo, str) and modulo.strip()
                else None,
            ),
        )
    return Temario(lecciones=[lecciones[n] for n in sorted(lecciones)])
