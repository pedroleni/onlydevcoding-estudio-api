import hashlib
import math
import sqlite3
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, Field

from estudio_api.config import Config
from estudio_api.estado import camara_grabada, voz_grabada
from estudio_api.lectura import _leer_json, datos_curso, ruta_guion
from estudio_api.rutas import ruta_segura
from estudio_api.trabajos import Trabajo, ultimo_trabajo


class CueTeleprompter(BaseModel):
    texto: str
    pausa: float = Field(default=0, ge=0, le=30)


class EscenaTeleprompter(BaseModel):
    id: str
    modo: Literal["voz", "camara"]
    titulo: str
    cues: list[CueTeleprompter]
    puntos: list[str]
    grabada: bool
    toma: str | None
    version_toma: int | None


class MontajeEscena(BaseModel):
    id: str
    modo: Literal["voz", "camara", "animacion"]
    inicio: int
    duracion: int
    cues: list[int]


class Montaje(BaseModel):
    fps: float
    duracion: int
    escenas: list[MontajeEscena]


class EstadoPrevia(BaseModel):
    ruta: str | None
    existe: bool
    desactualizada: bool
    version: int | None
    trabajo: Trabajo | None


class Teleprompter(BaseModel):
    curso: str
    numero: int
    guion: str
    titulo: str
    version: str
    escenas: list[EscenaTeleprompter]
    montaje: Montaje | None
    previa: EstadoPrevia


def comando_previa(npx: str, temporal: Path, guion: str) -> list[str]:
    return [
        npx,
        "remotion",
        "render",
        "src/index.ts",
        "Leccion",
        str(temporal),
        f'--props={{"leccion":"{guion}"}}',
        "--scale=0.5",
        "--muted",
        "--crf=30",
    ]


def ruta_montaje(config: Config, guion: str) -> Path | None:
    try:
        return ruta_segura(
            config.estudio_dir,
            "public",
            "lecciones",
            guion,
            "montaje.json",
        )
    except ValueError:
        return None


def rutas_previa(config: Config, guion: str) -> tuple[Path, Path] | None:
    try:
        directorio = ruta_segura(
            config.estudio_dir,
            "out",
            "previas-grabacion",
        )
        destino = ruta_segura(directorio, f"{guion}.mp4")
        temporal = ruta_segura(directorio, f"{guion}.generando.mp4")
    except ValueError:
        return None
    return temporal, destino


def _texto(valor: object) -> str:
    return valor if isinstance(valor, str) else ""


def _lista_textos(valor: object) -> list[str]:
    if not isinstance(valor, list):
        return []
    return [elemento for elemento in valor if isinstance(elemento, str)]


def _pausa(valor: object) -> float:
    if not isinstance(valor, (int, float)) or isinstance(valor, bool):
        return 0.0
    try:
        pausa = float(valor)
    except OverflowError, ValueError:
        return 0.0
    if not math.isfinite(pausa):
        return 0.0
    return min(30.0, max(0.0, pausa))


def _cues(valor: object) -> list[CueTeleprompter]:
    if not isinstance(valor, list):
        return []
    return [
        CueTeleprompter(
            texto=cue["texto"],
            pausa=_pausa(cue.get("pausa")),
        )
        for cue in valor
        if isinstance(cue, dict) and isinstance(cue.get("texto"), str)
    ]


def _ruta_toma(
    config: Config,
    carpeta: Path,
    escena: str,
) -> tuple[Path, str] | None:
    try:
        relativa = carpeta.resolve().relative_to(config.cursos_dir.resolve())
        ruta = ruta_segura(
            config.cursos_dir,
            *relativa.parts,
            "grabaciones",
            f"{escena}.wav",
        )
        publica = PurePosixPath(
            "cursos",
            *ruta.relative_to(config.cursos_dir.resolve()).parts,
        ).as_posix()
    except OSError, ValueError:
        return None
    return ruta, publica


def _escenas_teleprompter(
    config: Config,
    curso: str,
    numero: int,
    carpeta: Path,
    guion: dict[str, Any],
) -> list[EscenaTeleprompter]:
    valor_escenas = guion.get("escenas")
    if not isinstance(valor_escenas, list):
        return []

    escenas: list[EscenaTeleprompter] = []
    for datos in valor_escenas:
        if not isinstance(datos, dict) or datos.get("modo") not in {"voz", "camara"}:
            continue
        identificador = datos.get("id")
        if not isinstance(identificador, str):
            continue
        modo = datos["modo"]
        toma: str | None = None
        version_toma: int | None = None
        if modo == "voz":
            grabada = voz_grabada(config, carpeta, identificador)
            if grabada and (rutas := _ruta_toma(config, carpeta, identificador)):
                ruta, toma_publica = rutas
                try:
                    version_toma = ruta.stat().st_mtime_ns
                    toma = toma_publica
                except OSError:
                    grabada = False
        else:
            grabada = camara_grabada(
                config,
                curso,
                numero,
                carpeta,
                identificador,
            )
        escenas.append(
            EscenaTeleprompter(
                id=identificador,
                modo=modo,
                titulo=_texto(datos.get("titulo")),
                cues=_cues(datos.get("cues")),
                puntos=_lista_textos(datos.get("puntos")),
                grabada=grabada,
                toma=toma,
                version_toma=version_toma,
            )
        )
    return escenas


def _entero_no_negativo(valor: object) -> int | None:
    if not isinstance(valor, int) or isinstance(valor, bool) or valor < 0:
        return None
    return valor


def _leer_montaje(
    ruta: Path | None,
    guion: dict[str, Any],
) -> Montaje | None:
    if ruta is None:
        return None
    datos = _leer_json(ruta)
    if datos is None:
        return None
    fps = datos.get("fps")
    if not isinstance(fps, (int, float)) or isinstance(fps, bool):
        return None
    fps = float(fps)
    duracion_total = _entero_no_negativo(datos.get("duracion"))
    datos_escenas = datos.get("escenas")
    if not math.isfinite(fps) or fps <= 0 or duracion_total is None:
        return None
    if not isinstance(datos_escenas, list):
        return None

    modos = {
        escena.get("id"): escena.get("modo")
        for escena in guion.get("escenas", [])
        if isinstance(escena, dict)
        and isinstance(escena.get("id"), str)
        and escena.get("modo") in {"voz", "camara", "animacion"}
    }
    inicio = 0
    escenas: list[MontajeEscena] = []
    for datos_escena in datos_escenas:
        if not isinstance(datos_escena, dict):
            return None
        identificador = datos_escena.get("id")
        duracion = _entero_no_negativo(datos_escena.get("duracion"))
        modo = modos.get(identificador)
        if not isinstance(identificador, str) or duracion is None or modo is None:
            return None
        datos_cues = datos_escena.get("cues", [])
        if not isinstance(datos_cues, list):
            return None
        cues: list[int] = []
        for cue in datos_cues:
            if not isinstance(cue, dict):
                return None
            desde = cue.get("desde", 0)
            if desde is None:
                desde = 0
            desde_entero = _entero_no_negativo(desde)
            if desde_entero is None:
                return None
            cues.append(desde_entero)
        escenas.append(
            MontajeEscena(
                id=identificador,
                modo=modo,
                inicio=inicio,
                duracion=duracion,
                cues=cues,
            )
        )
        inicio += duracion
    return Montaje(fps=fps, duracion=duracion_total, escenas=escenas)


def _estado_previa(
    config: Config,
    bd: sqlite3.Connection,
    curso: str,
    numero: int,
    guion: str,
    montaje: Path | None,
) -> EstadoPrevia:
    rutas = rutas_previa(config, guion)
    destino = rutas[1] if rutas is not None else None
    existe = False
    version: int | None = None
    desactualizada = False
    ruta_publica: str | None = None
    if destino is not None:
        try:
            datos_previa = destino.stat()
            existe = destino.is_file()
            if existe:
                version = datos_previa.st_mtime_ns
                ruta_publica = f"estudio/out/previas-grabacion/{guion}.mp4"
                if montaje is not None:
                    desactualizada = montaje.stat().st_mtime_ns > version
        except OSError:
            pass
    return EstadoPrevia(
        ruta=ruta_publica,
        existe=existe,
        desactualizada=desactualizada,
        version=version,
        trabajo=ultimo_trabajo(bd, "previa-grabacion", curso, numero),
    )


def leer_teleprompter(
    config: Config,
    bd: sqlite3.Connection,
    curso: str,
    numero: int,
) -> Teleprompter | None:
    leido = datos_curso(config, curso)
    if leido is None:
        return None
    datos_guion = leido[2].get(numero)
    if datos_guion is None:
        return None
    _, carpeta, guion = datos_guion
    ruta_archivo_guion = ruta_guion(config, curso, numero, leido)
    if ruta_archivo_guion is None:
        return None
    try:
        bytes_guion = ruta_archivo_guion.read_bytes()
    except OSError:
        return None

    identificador_guion = f"{curso}-{numero:02d}"
    montaje_ruta = ruta_montaje(config, identificador_guion)
    return Teleprompter(
        curso=curso,
        numero=numero,
        guion=identificador_guion,
        titulo=_texto(guion.get("titulo")),
        version=hashlib.sha256(bytes_guion).hexdigest(),
        escenas=_escenas_teleprompter(
            config,
            curso,
            numero,
            carpeta,
            guion,
        ),
        montaje=_leer_montaje(montaje_ruta, guion),
        previa=_estado_previa(
            config,
            bd,
            curso,
            numero,
            identificador_guion,
            montaje_ruta,
        ),
    )
