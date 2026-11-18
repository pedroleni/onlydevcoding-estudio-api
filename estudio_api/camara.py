import re
import stat
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from pydantic import BaseModel

from estudio_api.config import Config
from estudio_api.estado import _ruta_de_leccion
from estudio_api.lectura import (
    _leer_json,
    _ruta_publica,
    _texto,
    carpeta_de_trabajo,
    datos_curso,
)
from estudio_api.rutas import ruta_segura

PATRON_ID_ESCENA = re.compile(r"^E\d{2}$")
PATRON_ID_TOMA = re.compile(r"^[0-9A-F]{8}$")


class EscenaCamara(BaseModel):
    id: str
    titulo: str
    video: str | None
    version: int | None
    original: str | None
    mejorada: bool


class GanchoCamara(BaseModel):
    id: str
    titulo: str
    toma: str | None
    video: str | None
    version: int | None
    color: bool


class TomasCamara(BaseModel):
    escenas: list[EscenaCamara]
    ganchos: list[GanchoCamara]


def _mtime_archivo_regular(ruta: Path) -> int | None:
    """``st_mtime_ns`` si la ruta es un archivo regular (no un enlace)."""
    try:
        datos = ruta.lstat()
    except OSError:
        return None
    return datos.st_mtime_ns if stat.S_ISREG(datos.st_mode) else None


def _video_publico(config: Config, *partes: str) -> tuple[str, int] | None:
    try:
        ruta = ruta_segura(config.estudio_dir, *partes)
        version = _mtime_archivo_regular(ruta)
        if version is None or ruta.suffix != ".mov":
            return None
        return _ruta_publica(config.estudio_dir, "estudio", ruta), version
    except OSError, ValueError:
        return None


def _nombre_original(toma: object) -> str | None:
    if not isinstance(toma, dict):
        return None
    original = toma.get("original")
    if not isinstance(original, str):
        return None
    nombre = PurePosixPath(PureWindowsPath(original).as_posix()).name
    if nombre in {"", ".", ".."}:
        return None
    return nombre


def _entregados(config: Config, numero: int, guion: str) -> dict[str, str]:
    try:
        shorts = _leer_json(
            ruta_segura(config.estudio_dir, "shorts", f"l{numero}", "shorts.json")
        )
    except OSError, ValueError:
        return {}
    if shorts is None or shorts.get("leccion") != guion:
        return {}
    valor = shorts.get("ganchosEntregados")
    if not isinstance(valor, dict):
        return {}
    return {
        gancho: toma
        for gancho, toma in valor.items()
        if isinstance(gancho, str)
        and isinstance(toma, str)
        and PATRON_ID_TOMA.fullmatch(toma) is not None
    }


def _mejorada(
    config: Config,
    carpeta: Path | None,
    identificador: str,
    version_publica: int | None,
) -> bool:
    """La copia de ``mejorar-toma`` es de la toma que se ve ahora.

    Colocar otra toma sustituye el vídeo público pero deja la copia vieja en
    ``grabaciones/videos/ia/``: solo cuenta si no es anterior al vídeo público.
    """
    if carpeta is None or version_publica is None:
        return False
    partes = ("grabaciones", "videos", "ia", f"{identificador}.mov")
    ruta = _ruta_de_leccion(config, carpeta, *partes)
    if ruta is None or ruta != carpeta.resolve().joinpath(*partes):
        return False
    version = _mtime_archivo_regular(ruta)
    return version is not None and version >= version_publica


def _color_vigente(config: Config, numero: int, toma: str, version_mov: int) -> bool:
    try:
        ruta = ruta_segura(
            config.estudio_dir, "shorts", f"l{numero}", "tomas", f"{toma}.color"
        )
    except ValueError:
        return False
    version = _mtime_archivo_regular(ruta)
    return version is not None and version >= version_mov


def _escenas(
    config: Config,
    guion_id: str,
    carpeta: Path | None,
    guion: dict[str, Any],
) -> list[EscenaCamara]:
    valor = guion.get("escenas")
    escenas: list[EscenaCamara] = []
    for datos in valor if isinstance(valor, list) else []:
        if not isinstance(datos, dict) or datos.get("modo") != "camara":
            continue
        identificador = datos.get("id")
        if (
            not isinstance(identificador, str)
            or PATRON_ID_ESCENA.fullmatch(identificador) is None
        ):
            continue
        video = _video_publico(
            config, "public", "grabaciones", guion_id, f"{identificador}.mov"
        )
        escenas.append(
            EscenaCamara(
                id=identificador,
                titulo=_texto(datos.get("titulo")) or identificador,
                video=video[0] if video else None,
                version=video[1] if video else None,
                original=_nombre_original(datos.get("toma")),
                mejorada=_mejorada(
                    config, carpeta, identificador, video[1] if video else None
                ),
            )
        )
    return escenas


def _ganchos(
    config: Config,
    numero: int,
    guion_id: str,
    guion: dict[str, Any],
) -> list[GanchoCamara]:
    entregados = _entregados(config, numero, guion_id)
    valor = guion.get("ganchos")
    ganchos: list[GanchoCamara] = []
    for datos in valor if isinstance(valor, list) else []:
        if not isinstance(datos, dict) or not isinstance(datos.get("id"), str):
            continue
        identificador = datos["id"]
        titulo = datos.get("titulo")
        if not isinstance(titulo, str) or not titulo:
            titulo = _texto(datos.get("texto")) or identificador
        toma = entregados.get(identificador)
        video = (
            _video_publico(
                config, "public", "shorts", f"l{numero}", "tomas", f"{toma}.mov"
            )
            if toma is not None
            else None
        )
        ganchos.append(
            GanchoCamara(
                id=identificador,
                titulo=titulo,
                toma=toma,
                video=video[0] if video else None,
                version=video[1] if video else None,
                color=toma is not None
                and video is not None
                and _color_vigente(config, numero, toma, video[1]),
            )
        )
    return ganchos


def leer_camara(config: Config, curso: str, numero: int) -> TomasCamara | None:
    leido = datos_curso(config, curso)
    if leido is None:
        return None
    datos_guion = leido[2].get(numero)
    if datos_guion is None:
        return None
    guion = datos_guion[2]
    guion_id = datos_guion[3].stem
    carpeta = carpeta_de_trabajo(leido, numero)
    return TomasCamara(
        escenas=_escenas(config, guion_id, carpeta, guion),
        ganchos=_ganchos(config, numero, guion_id, guion),
    )
