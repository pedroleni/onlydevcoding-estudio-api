import os
import tempfile
import threading
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from estudio_api.config import Config
from estudio_api.lectura import _ruta_publica, datos_curso
from estudio_api.rutas import ruta_segura

TAMANO_MAXIMO_TOMA = 209_715_200
_BLOQUEO_INSTALACION = threading.Lock()


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
    carpeta_curso, carpetas, guiones = leido
    datos_guion = guiones.get(numero)
    if datos_guion is None or not carpeta_curso.is_dir():
        raise LeccionSinGuion
    carpeta = carpetas[numero][1] if numero in carpetas else datos_guion[1]
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


def _preparar_directorios(config: Config, carpeta: Path) -> tuple[Path, Path]:
    relativa = carpeta.resolve().relative_to(config.cursos_dir.resolve())
    grabaciones = _ruta_literal_segura(
        config.cursos_dir,
        *relativa.parts,
        "grabaciones",
    )
    grabaciones.mkdir(parents=True, exist_ok=True)
    grabaciones = _ruta_literal_segura(
        config.cursos_dir,
        *relativa.parts,
        "grabaciones",
    )
    tomas = _ruta_literal_segura(grabaciones, "tomas")
    tomas.mkdir(exist_ok=True)
    tomas = _ruta_literal_segura(grabaciones, "tomas")
    if not grabaciones.is_dir() or not tomas.is_dir():
        raise OSError("No se pueden preparar las carpetas de grabación")
    return grabaciones, tomas


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
    total = 0
    cabecera = bytearray()
    try:
        with tempfile.NamedTemporaryFile(
            dir=grabaciones,
            prefix=".",
            suffix=".wav.tmp",
            delete=False,
        ) as archivo:
            temporal = Path(archivo.name)
            async for trozo in cuerpo:
                if not isinstance(trozo, bytes):
                    raise WavInvalido
                total += len(trozo)
                if total > longitud or total > TAMANO_MAXIMO_TOMA:
                    raise WavInvalido
                if len(cabecera) < 12:
                    cabecera.extend(trozo[: 12 - len(cabecera)])
                archivo.write(trozo)
            archivo.flush()
            os.fsync(archivo.fileno())
        if (
            total != longitud
            or len(cabecera) < 12
            or cabecera[:4] != b"RIFF"
            or cabecera[8:12] != b"WAVE"
        ):
            raise WavInvalido
        return temporal, total
    except BaseException:
        if temporal is not None:
            temporal.unlink(missing_ok=True)
        raise


def _instalar_temporal(
    temporal: Path,
    destino: Path,
    tomas: Path,
) -> int:
    anterior: Path | None = None
    with _BLOQUEO_INSTALACION:
        if destino.is_symlink():
            raise OSError("La toma de destino no puede ser un enlace simbólico")
        if destino.exists():
            if not destino.is_file():
                raise OSError("La toma de destino no es un archivo")
            anterior = _ruta_anterior(tomas, destino.stem)
            os.replace(destino, anterior)
        instalada = False
        try:
            os.replace(temporal, destino)
            instalada = True
            _fsync_directorio(destino.parent)
        except BaseException:
            if instalada:
                os.replace(destino, temporal)
            if anterior is not None:
                os.replace(anterior, destino)
                _fsync_directorio(destino.parent)
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
    grabaciones, tomas = _preparar_directorios(config, carpeta)
    destino = _ruta_literal_segura(grabaciones, f"{escena}.wav")
    ruta_publica = _ruta_publica(config.cursos_dir, "cursos", destino)
    temporal, total = await _escribir_temporal(grabaciones, cuerpo, longitud)
    try:
        version = _instalar_temporal(temporal, destino, tomas)
        return TomaGuardada(
            escena=escena,
            ruta=ruta_publica,
            version=version,
            bytes=total,
        )
    finally:
        temporal.unlink(missing_ok=True)
