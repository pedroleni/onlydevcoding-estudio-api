import contextlib
import os
import stat
import tempfile
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from estudio_api.config import Config
from estudio_api.lectura import _ruta_publica, carpeta_de_trabajo, datos_curso
from estudio_api.rutas import ruta_segura

TAMANO_MAXIMO_TOMA = 209_715_200
_BLOQUEO_INSTALACION = threading.Lock()
_MAXIMA_EDAD_TEMPORAL = 24 * 60 * 60


class TomaGuardada(BaseModel):
    escena: str
    ruta: str
    version: int
    bytes: int


class LeccionSinGuion(Exception):
    pass


class EscenaNoExiste(Exception):
    pass


class EscenaNoEsVoz(Exception):
    pass


class WavInvalido(Exception):
    pass


@dataclass(frozen=True)
class _DirectoriosToma:
    grabaciones: Path
    tomas: Path
    creados: tuple[Path, ...]


def _ahora_local() -> datetime:
    return datetime.now()


def _carpeta_y_guion(
    config: Config,
    curso: str,
    numero: int,
) -> tuple[Path, dict[str, Any]]:
    leido = datos_curso(config, curso)
    if leido is None:
        raise LeccionSinGuion
    carpeta_curso, _, guiones = leido
    datos_guion = guiones.get(numero)
    if datos_guion is None or not carpeta_curso.is_dir():
        raise LeccionSinGuion
    carpeta = carpeta_de_trabajo(leido, numero)
    if carpeta is None:
        raise LeccionSinGuion
    return carpeta, datos_guion[2]


def _validar_escena(guion: dict[str, Any], escena: str) -> None:
    escenas = guion.get("escenas")
    if not isinstance(escenas, list):
        raise EscenaNoExiste
    datos_escena = next(
        (
            candidata
            for candidata in escenas
            if isinstance(candidata, dict) and candidata.get("id") == escena
        ),
        None,
    )
    if datos_escena is None:
        raise EscenaNoExiste
    if datos_escena.get("modo") != "voz":
        raise EscenaNoEsVoz


def _ruta_literal_segura(raiz: Path, *partes: str) -> Path:
    literal = raiz.resolve().joinpath(*partes)
    segura = ruta_segura(raiz, *partes)
    if literal.is_symlink() or segura != literal:
        raise OSError("La ruta de grabación no puede contener enlaces simbólicos")
    return segura


def _crear_directorio(ruta: Path) -> bool:
    try:
        ruta.mkdir()
    except FileExistsError:
        return False
    return True


def _borrar_directorios_vacios(directorios: tuple[Path, ...]) -> None:
    for directorio in reversed(directorios):
        with contextlib.suppress(OSError):
            directorio.rmdir()


def _limpiar_temporales_antiguos(grabaciones: Path) -> None:
    limite = time.time() - _MAXIMA_EDAD_TEMPORAL
    for temporal in grabaciones.glob(".*.wav.tmp"):
        try:
            metadatos = temporal.stat(follow_symlinks=False)
            if stat.S_ISREG(metadatos.st_mode) and metadatos.st_mtime < limite:
                temporal.unlink()
        except FileNotFoundError:
            continue


def _preparar_directorios(config: Config, carpeta: Path) -> _DirectoriosToma:
    relativa = carpeta.resolve().relative_to(config.cursos_dir.resolve())
    carpeta = _ruta_literal_segura(config.cursos_dir, *relativa.parts)
    creados: list[Path] = []
    try:
        if _crear_directorio(carpeta):
            creados.append(carpeta)
        if not carpeta.is_dir():
            raise OSError("La carpeta de la lección no es un directorio")

        grabaciones = _ruta_literal_segura(carpeta, "grabaciones")
        if _crear_directorio(grabaciones):
            creados.append(grabaciones)
        grabaciones = _ruta_literal_segura(carpeta, "grabaciones")
        if not grabaciones.is_dir():
            raise OSError("La carpeta de grabaciones no es un directorio")

        tomas = _ruta_literal_segura(grabaciones, "tomas")
        if _crear_directorio(tomas):
            creados.append(tomas)
        tomas = _ruta_literal_segura(grabaciones, "tomas")
        if not tomas.is_dir():
            raise OSError("La carpeta de tomas no es un directorio")

        _limpiar_temporales_antiguos(grabaciones)
        return _DirectoriosToma(grabaciones, tomas, tuple(creados))
    except BaseException:
        _borrar_directorios_vacios(tuple(creados))
        raise


def _ruta_anterior(tomas: Path, escena: str) -> Path:
    marca = _ahora_local().strftime("%Y%m%dT%H%M%S%f")
    base = f"{escena}-{marca}"
    indice = 1
    while True:
        sufijo = "" if indice == 1 else f"-{indice}"
        candidata = _ruta_literal_segura(tomas, f"{base}{sufijo}.wav")
        if not candidata.exists():
            return candidata
        indice += 1


def _fsync_directorio(directorio: Path) -> None:
    descriptor = os.open(
        directorio,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


async def _escribir_temporal(
    grabaciones: Path,
    cuerpo: AsyncIterator[bytes],
    longitud: int,
) -> tuple[Path, int]:
    temporal: Path | None = None
    descriptor: int | None = None
    total = 0
    cabecera = bytearray()
    try:
        descriptor, nombre_temporal = await run_in_threadpool(
            tempfile.mkstemp,
            ".wav.tmp",
            ".",
            grabaciones,
        )
        temporal = Path(nombre_temporal)
        async for trozo in cuerpo:
            if not isinstance(trozo, bytes):
                raise WavInvalido
            total += len(trozo)
            if total > longitud or total > TAMANO_MAXIMO_TOMA:
                raise WavInvalido
            if len(cabecera) < 12:
                cabecera.extend(trozo[: 12 - len(cabecera)])
            await run_in_threadpool(_escribir_trozo, descriptor, trozo)
        try:
            await run_in_threadpool(_sincronizar_y_cerrar, descriptor)
        finally:
            descriptor = None
        if (
            total != longitud
            or len(cabecera) < 12
            or cabecera[:4] != b"RIFF"
            or cabecera[8:12] != b"WAVE"
        ):
            raise WavInvalido
        return temporal, total
    except BaseException:
        await run_in_threadpool(_cerrar_y_borrar_temporal, descriptor, temporal)
        raise


def _escribir_trozo(descriptor: int, trozo: bytes) -> None:
    pendiente = memoryview(trozo)
    while pendiente:
        escritos = os.write(descriptor, pendiente)
        if escritos <= 0:
            raise OSError("No se ha podido escribir la toma")
        pendiente = pendiente[escritos:]


def _sincronizar_y_cerrar(descriptor: int) -> None:
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _cerrar_y_borrar_temporal(
    descriptor: int | None,
    temporal: Path | None,
) -> None:
    if descriptor is not None:
        with contextlib.suppress(OSError):
            os.close(descriptor)
    if temporal is not None:
        temporal.unlink(missing_ok=True)


def _instalar_temporal(
    temporal: Path,
    destino: Path,
    tomas: Path,
) -> int:
    anterior: Path | None = None
    with _BLOQUEO_INSTALACION:
        if destino.is_symlink():
            raise OSError("La toma de destino no puede ser un enlace simbólico")
        instalada = False
        try:
            if destino.exists():
                if not destino.is_file():
                    raise OSError("La toma de destino no es un archivo")
                anterior = _ruta_anterior(tomas, destino.stem)
                os.replace(destino, anterior)
                _fsync_directorio(tomas)
            os.replace(temporal, destino)
            instalada = True
            _fsync_directorio(destino.parent)
        except BaseException:
            if instalada:
                os.replace(destino, temporal)
            if anterior is not None and anterior.exists():
                os.replace(anterior, destino)
                _fsync_directorio(destino.parent)
                _fsync_directorio(tomas)
            raise
        return destino.stat().st_mtime_ns


async def guardar_toma(
    config: Config,
    curso: str,
    numero: int,
    escena: str,
    cuerpo: AsyncIterator[bytes],
    longitud: int,
) -> TomaGuardada:
    if not 0 <= longitud <= TAMANO_MAXIMO_TOMA:
        raise WavInvalido
    carpeta, guion = _carpeta_y_guion(config, curso, numero)
    _validar_escena(guion, escena)
    directorios = await run_in_threadpool(_preparar_directorios, config, carpeta)
    grabaciones = directorios.grabaciones
    destino = _ruta_literal_segura(grabaciones, f"{escena}.wav")
    ruta_publica = _ruta_publica(config.cursos_dir, "cursos", destino)
    temporal: Path | None = None
    try:
        temporal, total = await _escribir_temporal(grabaciones, cuerpo, longitud)
        version = await run_in_threadpool(
            _instalar_temporal,
            temporal,
            destino,
            directorios.tomas,
        )
        return TomaGuardada(
            escena=escena,
            ruta=ruta_publica,
            version=version,
            bytes=total,
        )
    except BaseException:
        if temporal is not None:
            await run_in_threadpool(temporal.unlink, True)
            temporal = None
        await run_in_threadpool(
            _borrar_directorios_vacios,
            directorios.creados,
        )
        raise
    finally:
        if temporal is not None:
            await run_in_threadpool(temporal.unlink, True)
