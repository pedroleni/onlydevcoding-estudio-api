import re
from pathlib import Path, PurePosixPath
from typing import Any

from estudio_api.config import Config
from estudio_api.modelos import Avance, EstadoLeccion
from estudio_api.rutas import ruta_segura

PATRON_ID_CURSO = re.compile(r"^[a-z0-9-]{1,40}$")
PATRON_PREVIA = re.compile(r"^previa-v(\d+)\.mp4$", re.IGNORECASE)
REDES = ("youtube", "instagram", "tiktok", "linkedin")


def _ruta_de_leccion(
    config: Config,
    carpeta: Path | None,
    *partes: str,
) -> Path | None:
    if carpeta is None:
        return None
    try:
        relativa = carpeta.resolve().relative_to(config.cursos_dir.resolve())
        return ruta_segura(config.cursos_dir, *relativa.parts, *partes)
    except OSError, ValueError:
        return None


def _es_archivo(ruta: Path | None) -> bool:
    if ruta is None:
        return False
    try:
        return ruta.is_file()
    except OSError:
        return False


def _escenas(guion: dict[str, Any] | None, modo: str) -> list[str | None]:
    if guion is None or not isinstance(guion.get("escenas"), list):
        return []
    return [
        escena.get("id") if isinstance(escena.get("id"), str) else None
        for escena in guion["escenas"]
        if isinstance(escena, dict) and escena.get("modo") == modo
    ]


def _voz_grabada(config: Config, carpeta: Path | None, escena: str | None) -> bool:
    if escena is None:
        return False
    try:
        ruta = _ruta_de_leccion(config, carpeta, "grabaciones", f"{escena}.wav")
    except ValueError:
        return False
    return _es_archivo(ruta)


def _camara_grabada(
    config: Config,
    curso: str,
    numero: int,
    carpeta: Path | None,
    escena: str | None,
) -> bool:
    if escena is None:
        return False

    toma_ia = _ruta_de_leccion(
        config,
        carpeta,
        "grabaciones",
        "videos",
        "ia",
        f"{escena}.mov",
    )
    if _es_archivo(toma_ia):
        return True

    if (
        isinstance(numero, bool)
        or not 1 <= numero <= 999
        or PATRON_ID_CURSO.fullmatch(curso) is None
    ):
        return False
    try:
        toma_estudio = ruta_segura(
            config.estudio_dir,
            "public",
            "grabaciones",
            f"{curso}-{numero:02d}",
            f"{escena}.mov",
        )
    except ValueError:
        return False
    return _es_archivo(toma_estudio)


def _hay_video_final(config: Config, carpeta: Path | None) -> bool:
    directorio = _ruta_de_leccion(
        config,
        carpeta,
        "publicar",
        "1-youtube-leccion",
    )
    if directorio is None or not directorio.is_dir():
        return False
    try:
        nombres = (entrada.name for entrada in directorio.iterdir())
        return any(
            _es_archivo(
                _ruta_de_leccion(
                    config,
                    carpeta,
                    "publicar",
                    "1-youtube-leccion",
                    nombre,
                )
            )
            for nombre in nombres
            if nombre.lower().endswith(".mp4")
        )
    except OSError:
        return False


def _ultima_previa(config: Config, carpeta: Path | None) -> str | None:
    directorio = _ruta_de_leccion(config, carpeta, "previa")
    if directorio is None or not directorio.is_dir():
        return None

    versiones: list[tuple[int, Path]] = []
    try:
        for entrada in directorio.iterdir():
            coincidencia = PATRON_PREVIA.fullmatch(entrada.name)
            if coincidencia is None:
                continue
            ruta = _ruta_de_leccion(config, carpeta, "previa", entrada.name)
            if _es_archivo(ruta):
                versiones.append((int(coincidencia.group(1)), ruta))
    except OSError:
        return None
    if not versiones:
        return None

    ultima = max(versiones, key=lambda version: version[0])[1]
    relativa = ultima.relative_to(config.cursos_dir.resolve())
    segura = ruta_segura(config.cursos_dir, *relativa.parts)
    return PurePosixPath(
        "cursos", *segura.relative_to(config.cursos_dir.resolve()).parts
    ).as_posix()


def calcular_estado(
    config: Config,
    curso: str,
    numero: int,
    carpeta: Path | None,
    guion: dict[str, Any] | None,
) -> EstadoLeccion:
    escenas_voz = _escenas(guion, "voz")
    escenas_camara = _escenas(guion, "camara")
    return EstadoLeccion(
        guion=guion is not None,
        voz=Avance(
            hechas=sum(_voz_grabada(config, carpeta, escena) for escena in escenas_voz),
            total=len(escenas_voz),
        ),
        camara=Avance(
            hechas=sum(
                _camara_grabada(config, curso, numero, carpeta, escena)
                for escena in escenas_camara
            ),
            total=len(escenas_camara),
        ),
        video_final=_hay_video_final(config, carpeta),
        miniatura=None,
        previa=_ultima_previa(config, carpeta),
        publicado={red: False for red in REDES},
    )
