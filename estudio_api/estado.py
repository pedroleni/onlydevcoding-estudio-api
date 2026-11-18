from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from estudio_api.config import Config
from estudio_api.modelos import Avance, EstadoLeccion, EstadoRed
from estudio_api.rutas import ruta_segura

if TYPE_CHECKING:
    from estudio_api.publicacion import Publicacion

PATRON_ID_CURSO = re.compile(r"^[a-z0-9-]{1,40}$")
PATRON_ID_GUION = re.compile(r"^[a-z0-9-]{1,40}-\d{2,3}$")
PATRON_PREVIA = re.compile(r"^previa-v(\d+)\.mp4$", re.IGNORECASE)
REDES = ("youtube", "instagram", "tiktok", "linkedin")


def publicado_por_red(
    publicacion: Publicacion | None,
    estados: Mapping[tuple[str, str], EstadoRed],
) -> dict[str, bool]:
    previstas: dict[str, list[tuple[str, str]]] = {red: [] for red in REDES}
    if publicacion is None:
        previstas["youtube"].append(("leccion", "youtube"))
    else:
        from estudio_api.publicacion import textos_red_vacios

        for pieza, datos in publicacion.piezas.items():
            for red, textos in datos.redes.items():
                if not textos_red_vacios(textos):
                    previstas[red].append((pieza, red))

    return {
        red: bool(pares)
        and all(
            estados.get(par) is not None and estados[par].estado == "publicado"
            for par in pares
        )
        for red, pares in previstas.items()
    }


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


def ruta_toma_voz(
    config: Config,
    carpeta: Path | None,
    escena: str | None,
) -> Path | None:
    if escena is None:
        return None
    try:
        ruta = _ruta_de_leccion(config, carpeta, "grabaciones", f"{escena}.wav")
    except ValueError:
        return None
    return ruta if _es_archivo(ruta) else None


def voz_grabada(config: Config, carpeta: Path | None, escena: str | None) -> bool:
    return ruta_toma_voz(config, carpeta, escena) is not None


def camara_grabada(
    config: Config,
    identificador_guion: str | None,
    carpeta: Path | None,
    escena: str | None,
) -> bool:
    """Toma de cámara de la IA en la lección o del estudio con el nombre real del guion."""
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
        identificador_guion is None
        or PATRON_ID_GUION.fullmatch(identificador_guion) is None
    ):
        return False
    try:
        toma_estudio = ruta_segura(
            config.estudio_dir,
            "public",
            "grabaciones",
            identificador_guion,
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
            # Un temporal oculto (``.….generando.mp4``) no es el vídeo final.
            if not nombre.startswith(".") and nombre.lower().endswith(".mp4")
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


def _numero_y_curso_validos(curso: str, numero: int) -> bool:
    return (
        not isinstance(numero, bool)
        and 1 <= numero <= 999
        and PATRON_ID_CURSO.fullmatch(curso) is not None
    )


def calcular_estado(
    config: Config,
    curso: str,
    numero: int,
    carpeta: Path | None,
    guion: dict[str, Any] | None,
    *,
    publicacion: Publicacion | None = None,
    estados_publicacion: Mapping[tuple[str, str], EstadoRed] | None = None,
    miniatura: str | None = None,
    identificador_guion: str | None = None,
) -> EstadoLeccion:
    escenas_voz = _escenas(guion, "voz")
    escenas_camara = _escenas(guion, "camara")
    if identificador_guion is None and _numero_y_curso_validos(curso, numero):
        identificador_guion = f"{curso}-{numero:02d}"
    return EstadoLeccion(
        guion=guion is not None,
        voz=Avance(
            hechas=sum(voz_grabada(config, carpeta, escena) for escena in escenas_voz),
            total=len(escenas_voz),
        ),
        camara=Avance(
            hechas=sum(
                camara_grabada(config, identificador_guion, carpeta, escena)
                for escena in escenas_camara
            ),
            total=len(escenas_camara),
        ),
        video_final=_hay_video_final(config, carpeta),
        miniatura=miniatura,
        previa=_ultima_previa(config, carpeta),
        publicado=publicado_por_red(publicacion, estados_publicacion or {}),
    )
