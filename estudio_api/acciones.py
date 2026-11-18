import os
import re
import shutil
import sqlite3
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from estudio_api.config import Config
from estudio_api.estado import ruta_toma_voz
from estudio_api.lectura import (
    PATRON_PREVIA,
    _leer_json,
    _previas,
    carpeta_de_trabajo,
    datos_curso,
)
from estudio_api.modelos import EstadoMontaje
from estudio_api.rutas import ruta_segura
from estudio_api.teleprompter import (
    _leer_montaje,
    comando_previa,
    ruta_montaje,
    rutas_previa,
)
from estudio_api.trabajos import (
    MENSAJES_HERRAMIENTA,
    MENSAJES_PREVIA,
    MENSAJES_REMOTION,
    PROGRESO_HERRAMIENTA,
    PROGRESO_REMOTION,
    PlanTrabajo,
    Trabajo,
    ultimo_trabajo,
)

IdAccion = Literal[
    "alinear-voz",
    "preparar-montaje",
    "previa-grabacion",
    "render-leccion",
    "video-final",
    "preparar-shorts",
    "render-short",
]

PATRON_ID_SHORT = re.compile(r"^[a-z0-9-]{1,60}$")
PATRON_ID_ESCENA = re.compile(r"^E\d{2}$")
PROGRESO_NINGUNO = re.compile(r"(?!)")

SIN_GUION = "Esta lección aún no tiene guion"
SIN_MONTAJE = "Esta lección aún no tiene montaje"
SIN_MONTAJE_PARA_SHORTS = "Prepara antes el montaje de la lección"
CARPETA_NO_PREPARABLE = "No se puede preparar la carpeta del resultado"
CARPETA_PREVIA_NO_PREPARABLE = "No se puede preparar la carpeta de la vista previa"
# Acciones que leen el guion o las tomas de la lección mientras corren: si se
# cambian a la vez, el montaje sale viejo aunque el estado diga «al día».
ACCIONES_QUE_LEEN_LA_LECCION = frozenset(
    {"alinear-voz", "preparar-montaje", "preparar-shorts"}
)

ETIQUETAS: dict[IdAccion, str] = {
    "alinear-voz": "Alinear la voz",
    "preparar-montaje": "Preparar el montaje",
    "previa-grabacion": "Vista previa de grabación",
    "render-leccion": "Renderizar una versión nueva",
    "video-final": "Crear el vídeo final (−14 LUFS)",
    "preparar-shorts": "Preparar los shorts",
    "render-short": "Renderizar el short",
}
ORDEN_ACCIONES: tuple[IdAccion, ...] = tuple(ETIQUETAS)


class OpcionesAccion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    previa: str | None = None
    short: str | None = None


class EstadoAccion(BaseModel):
    id: IdAccion
    etiqueta: str
    disponible: bool
    motivo: str | None
    opciones: list[str] = Field(default_factory=list)
    ultimo: Trabajo | None
    ultimos: dict[str, Trabajo] = Field(default_factory=dict)


class AccionNoDisponible(Exception):
    def __init__(self, estado_http: int, mensaje: str) -> None:
        super().__init__(mensaje)
        self.estado_http = estado_http
        self.mensaje = mensaje


@dataclass(frozen=True)
class _Contexto:
    config: Config
    curso: str
    numero: int
    carpeta: Path
    slug: str
    guion: str | None
    datos_guion: dict[str, Any] | None


@dataclass(frozen=True)
class _Evaluacion:
    disponible: bool
    motivo: str | None = None
    estado_http: int = 409
    opciones: tuple[str, ...] = ()


def _no_disponible(
    mensaje: str,
    *,
    estado_http: int = 409,
    opciones: list[str] | tuple[str, ...] = (),
) -> _Evaluacion:
    return _Evaluacion(False, mensaje, estado_http, tuple(opciones))


def _contexto(
    config: Config,
    curso: str,
    numero: int,
) -> _Contexto | None:
    leido = datos_curso(config, curso)
    if leido is None:
        return None
    _, carpetas, guiones = leido
    if numero not in carpetas and numero not in guiones:
        return None
    carpeta = carpeta_de_trabajo(leido, numero)
    if carpeta is None:
        return None
    if numero in guiones:
        slug_declarado, _, guion, ruta_guion, _ = guiones[numero]
        slug = carpetas[numero][0] if numero in carpetas else slug_declarado
        return _Contexto(
            config=config,
            curso=curso,
            numero=numero,
            carpeta=carpeta,
            slug=slug,
            guion=ruta_guion.stem,
            datos_guion=guion,
        )
    slug = carpetas[numero][0]
    return _Contexto(
        config=config,
        curso=curso,
        numero=numero,
        carpeta=carpeta,
        slug=slug,
        guion=None,
        datos_guion=None,
    )


def _ruta_en_leccion(contexto: _Contexto, *partes: str) -> Path:
    relativa = contexto.carpeta.resolve().relative_to(
        contexto.config.cursos_dir.resolve()
    )
    return ruta_segura(contexto.config.cursos_dir, *relativa.parts, *partes)


def _destino_en_leccion(contexto: _Contexto, *partes: str) -> Path:
    """Destino dentro de la lección sin enlaces simbólicos en ningún componente.

    Las carpetas de resultado (``previa/``, ``shorts/``, ``publicar/``…) y el
    propio archivo tienen que ser rutas literales: un enlace, aunque apunte
    dentro de ``CURSOS_DIR``, llevaría el resultado a otra lección.
    """
    literal = contexto.carpeta.resolve().joinpath(*partes)
    if _ruta_en_leccion(contexto, *partes) != literal:
        raise ValueError("La ruta del resultado contiene enlaces simbólicos")
    actual = contexto.carpeta.resolve()
    for parte in partes:
        actual = actual / parte
        if actual.is_symlink():
            raise ValueError("La ruta del resultado contiene enlaces simbólicos")
    return literal


def _quitar_temporal(temporal: Path) -> None:
    """Borra lo que haya en la ruta del temporal sin seguir enlaces."""
    try:
        os.unlink(temporal)
    except FileNotFoundError:
        pass


def _crear_carpeta_real(ruta: Path) -> None:
    """Crea ``ruta`` si falta; tiene que acabar siendo un directorio, no un enlace."""
    try:
        ruta.mkdir()
    except FileExistsError:
        pass
    if not stat.S_ISDIR(os.lstat(ruta).st_mode):
        raise NotADirectoryError("La carpeta del resultado no es un directorio real")


def _preparar_en_leccion(
    contexto: _Contexto,
    carpetas: tuple[str, ...],
    temporal: Path,
) -> Callable[[], None]:
    """Crea, nivel a nivel, las carpetas literales del resultado en la lección."""

    def preparar() -> None:
        try:
            actual = contexto.carpeta.resolve()
            _crear_carpeta_real(actual)
            for parte in carpetas:
                actual = actual / parte
                _crear_carpeta_real(actual)
            _quitar_temporal(temporal)
        except (OSError, ValueError) as error:
            raise AccionNoDisponible(503, CARPETA_NO_PREPARABLE) from error

    return preparar


def _preparar_previa(
    config: Config,
    temporal: Path,
    destino: Path,
) -> Callable[[], None]:
    def preparar() -> None:
        raiz = config.estudio_dir.resolve()
        try:
            destino.parent.resolve().relative_to(raiz)
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.parent.resolve().relative_to(raiz)
            _quitar_temporal(temporal)
        except (OSError, ValueError) as error:
            raise AccionNoDisponible(503, CARPETA_PREVIA_NO_PREPARABLE) from error

    return preparar


def _ruta_toma_escena(
    config: Config,
    carpeta: Path,
    escena: dict[str, Any],
) -> Path | None:
    identificador = escena.get("id")
    if (
        not isinstance(identificador, str)
        or PATRON_ID_ESCENA.fullmatch(identificador) is None
    ):
        return None
    voz = escena.get("voz")
    archivo = voz.get("archivo") if isinstance(voz, dict) else None
    if isinstance(archivo, str):
        try:
            relativa = carpeta.resolve().relative_to(config.cursos_dir.resolve())
            toma = ruta_segura(config.cursos_dir, *relativa.parts, archivo)
        except OSError, ValueError:
            return None
        try:
            return toma if toma.is_file() else None
        except OSError:
            return None
    return ruta_toma_voz(config, carpeta, identificador)


def _alineaciones_con_toma(
    config: Config,
    guion: str,
    carpeta: Path,
    datos_guion: dict[str, Any] | None,
) -> list[tuple[str, Path, Path]]:
    escenas = datos_guion.get("escenas") if datos_guion is not None else None
    if not isinstance(escenas, list):
        return []
    resultado: list[tuple[str, Path, Path]] = []
    for escena in escenas:
        if not isinstance(escena, dict) or escena.get("modo") != "voz":
            continue
        identificador = escena.get("id")
        toma = _ruta_toma_escena(config, carpeta, escena)
        if toma is None or not isinstance(identificador, str):
            continue
        try:
            alineacion = ruta_segura(
                config.estudio_dir,
                "lecciones",
                "tomas",
                guion,
                f"{identificador}-voz.json",
            )
        except ValueError:
            continue
        resultado.append((identificador, toma, alineacion))
    return resultado


def _fecha_montaje_valido(
    config: Config,
    guion: str,
    datos_guion: dict[str, Any] | None,
) -> int | None:
    """``st_mtime_ns`` del montaje si es válido para el guion; si no, ``None``.

    Es el único criterio de «hay montaje» para el estado, la previa, el render
    y los shorts: el del teleprompter, que valida la estructura contra el guion.
    """
    if datos_guion is None:
        return None
    montaje = ruta_montaje(config, guion)
    if montaje is None:
        return None
    try:
        fecha = montaje.stat().st_mtime_ns
    except OSError:
        return None
    if _leer_montaje(montaje, datos_guion) is None:
        return None
    return fecha


def _hay_montaje(contexto: _Contexto) -> bool:
    return (
        contexto.guion is not None
        and _fecha_montaje_valido(
            contexto.config,
            contexto.guion,
            contexto.datos_guion,
        )
        is not None
    )


def estado_montaje(
    config: Config,
    guion: str,
    carpeta: Path,
    datos_guion: dict[str, Any] | None,
) -> EstadoMontaje:
    """Estado del montaje con el guion ya leído (``datos_guion``).

    ``sin_alinear`` se calcula siempre, también sin montaje; el ``estado``
    sigue el orden del plan.
    """
    sin_alinear: list[str] = []
    fechas_alineaciones: list[int] = []
    for identificador, toma, alineacion in _alineaciones_con_toma(
        config,
        guion,
        carpeta,
        datos_guion,
    ):
        try:
            fecha_toma = toma.stat().st_mtime_ns
            fecha_alineacion = alineacion.stat().st_mtime_ns
        except OSError:
            sin_alinear.append(identificador)
            continue
        if fecha_alineacion < fecha_toma:
            sin_alinear.append(identificador)
        fechas_alineaciones.append(fecha_alineacion)

    fecha_montaje = _fecha_montaje_valido(config, guion, datos_guion)
    if fecha_montaje is None:
        return EstadoMontaje(estado="sin_montaje", sin_alinear=sin_alinear)
    if sin_alinear:
        return EstadoMontaje(estado="voz_sin_alinear", sin_alinear=sin_alinear)

    try:
        ruta_guion = ruta_segura(config.estudio_dir, "lecciones", f"{guion}.json")
        guion_cambiado = ruta_guion.stat().st_mtime_ns > fecha_montaje
    except OSError, ValueError:
        guion_cambiado = False
    if guion_cambiado or any(
        fecha_alineacion > fecha_montaje for fecha_alineacion in fechas_alineaciones
    ):
        return EstadoMontaje(estado="guion_cambiado")
    return EstadoMontaje(estado="al_dia")


def _nombres_previas(contexto: _Contexto) -> list[str]:
    return [
        PurePosixPath(ruta).name for ruta in _previas(contexto.config, contexto.carpeta)
    ]


def _ids_shorts(contexto: _Contexto) -> list[str]:
    if contexto.guion is None:
        return []
    try:
        ruta = ruta_segura(
            contexto.config.estudio_dir,
            "shorts",
            f"l{contexto.numero}",
            "shorts.json",
        )
    except ValueError:
        return []
    datos = _leer_json(ruta)
    if datos is None or datos.get("leccion") != contexto.guion:
        return []
    shorts = datos.get("shorts")
    if not isinstance(shorts, list):
        return []
    ids: list[str] = []
    for short in shorts:
        identificador = short.get("id") if isinstance(short, dict) else None
        if (
            isinstance(identificador, str)
            and PATRON_ID_SHORT.fullmatch(identificador) is not None
            and identificador not in ids
        ):
            ids.append(identificador)
    return ids


def _exigir_guion(contexto: _Contexto) -> _Evaluacion | None:
    if contexto.guion is None or contexto.datos_guion is None:
        return _no_disponible(SIN_GUION)
    return None


def _evaluar_alinear_voz(
    contexto: _Contexto,
    _opciones: OpcionesAccion,
    _para_plan: bool,
) -> _Evaluacion:
    sin_guion = _exigir_guion(contexto)
    if sin_guion is not None:
        return sin_guion
    tomas = _alineaciones_con_toma(
        contexto.config,
        contexto.guion,
        contexto.carpeta,
        contexto.datos_guion,
    )
    if not tomas:
        return _no_disponible("No hay voz grabada que alinear")
    return _Evaluacion(True)


def _evaluar_preparar_montaje(
    contexto: _Contexto,
    _opciones: OpcionesAccion,
    _para_plan: bool,
) -> _Evaluacion:
    return _exigir_guion(contexto) or _Evaluacion(True)


def _evaluar_previa_grabacion(
    contexto: _Contexto,
    _opciones: OpcionesAccion,
    _para_plan: bool,
) -> _Evaluacion:
    sin_guion = _exigir_guion(contexto)
    if sin_guion is not None:
        return sin_guion
    if not _hay_montaje(contexto):
        return _no_disponible(SIN_MONTAJE)
    return _Evaluacion(True)


def _evaluar_render_leccion(
    contexto: _Contexto,
    _opciones: OpcionesAccion,
    _para_plan: bool,
) -> _Evaluacion:
    sin_guion = _exigir_guion(contexto)
    if sin_guion is not None:
        return sin_guion
    estado = estado_montaje(
        contexto.config,
        contexto.guion,
        contexto.carpeta,
        contexto.datos_guion,
    ).estado
    mensajes = {
        "sin_montaje": SIN_MONTAJE,
        "voz_sin_alinear": "Hay voz sin alinear: alinea la voz y prepara el montaje",
        "guion_cambiado": "Guion cambiado: hay que regenerar el montaje",
    }
    if estado != "al_dia":
        return _no_disponible(mensajes[estado])
    return _Evaluacion(True)


def _evaluar_video_final(
    contexto: _Contexto,
    opciones: OpcionesAccion,
    para_plan: bool,
) -> _Evaluacion:
    previas = _nombres_previas(contexto)
    if para_plan and opciones.previa not in previas:
        return _no_disponible(
            "Esa versión no existe",
            estado_http=422,
            opciones=previas,
        )
    if not previas:
        return _no_disponible(
            "Aún no hay ninguna versión renderizada",
            opciones=previas,
        )
    return _Evaluacion(True, opciones=tuple(previas))


def _evaluar_preparar_shorts(
    contexto: _Contexto,
    _opciones: OpcionesAccion,
    _para_plan: bool,
) -> _Evaluacion:
    if not _ids_shorts(contexto):
        return _no_disponible("Esta lección no tiene shorts")
    if not _hay_montaje(contexto):
        # preparar-shorts.mjs lee el montaje de la lección.
        return _no_disponible(SIN_MONTAJE_PARA_SHORTS)
    return _Evaluacion(True)


def _evaluar_render_short(
    contexto: _Contexto,
    opciones: OpcionesAccion,
    para_plan: bool,
) -> _Evaluacion:
    ids = _ids_shorts(contexto)
    if para_plan and (
        opciones.short is None
        or PATRON_ID_SHORT.fullmatch(opciones.short) is None
        or opciones.short not in ids
    ):
        return _no_disponible(
            "Ese short no existe",
            estado_http=422,
            opciones=ids,
        )
    if not ids:
        return _no_disponible("Esta lección no tiene shorts", opciones=ids)
    if para_plan:
        try:
            montaje = ruta_segura(
                contexto.config.estudio_dir,
                "public",
                "shorts",
                opciones.short,
                "montaje.json",
            )
        except ValueError:
            montaje = None
        if montaje is None or not montaje.is_file():
            return _no_disponible(
                "Prepara los shorts antes de renderizar",
                opciones=ids,
            )
    return _Evaluacion(True, opciones=tuple(ids))


_EVALUADORES = {
    "alinear-voz": _evaluar_alinear_voz,
    "preparar-montaje": _evaluar_preparar_montaje,
    "previa-grabacion": _evaluar_previa_grabacion,
    "render-leccion": _evaluar_render_leccion,
    "video-final": _evaluar_video_final,
    "preparar-shorts": _evaluar_preparar_shorts,
    "render-short": _evaluar_render_short,
}


def _evaluar(
    contexto: _Contexto,
    accion: IdAccion,
    opciones: OpcionesAccion,
    *,
    para_plan: bool,
) -> _Evaluacion:
    return _EVALUADORES[accion](contexto, opciones, para_plan)


def _binario(nombre: Literal["node", "npx"]) -> str:
    encontrado = shutil.which(nombre)
    if encontrado is None:
        raise AccionNoDisponible(
            503,
            f"No se encuentra {nombre} en el PATH de la API",
        )
    return encontrado


def _temporal_oculto(destino: Path) -> Path:
    return destino.with_name(f".{destino.stem}.generando{destino.suffix}")


def _plan_alinear_voz(contexto: _Contexto) -> PlanTrabajo:
    return PlanTrabajo(
        accion="alinear-voz",
        objetivo=None,
        comando=[
            _binario("node"),
            "herramientas/alinear-voz.mjs",
            contexto.guion,
        ],
        cwd=contexto.config.estudio_dir,
        entorno={"CURSOS_DIR": str(contexto.config.cursos_dir)},
        patron_progreso=PROGRESO_HERRAMIENTA,
        tiempo_maximo=60 * 60,
        mensajes=MENSAJES_HERRAMIENTA,
    )


def _plan_preparar_montaje(contexto: _Contexto) -> PlanTrabajo:
    return PlanTrabajo(
        accion="preparar-montaje",
        objetivo=None,
        comando=[
            _binario("node"),
            "herramientas/preparar-leccion.mjs",
            contexto.guion,
        ],
        cwd=contexto.config.estudio_dir,
        entorno={"CURSOS_DIR": str(contexto.config.cursos_dir)},
        patron_progreso=PROGRESO_HERRAMIENTA,
        tiempo_maximo=30 * 60,
        mensajes=MENSAJES_HERRAMIENTA,
    )


def _plan_previa_grabacion(contexto: _Contexto) -> PlanTrabajo:
    rutas = rutas_previa(contexto.config, contexto.guion)
    if rutas is None:
        raise AccionNoDisponible(404, "La ruta de la previa no es válida")
    temporal, destino = rutas
    return PlanTrabajo(
        accion="previa-grabacion",
        objetivo=None,
        comando=comando_previa(_binario("npx"), temporal, contexto.guion),
        cwd=contexto.config.estudio_dir,
        temporal=temporal,
        destino=destino,
        instalar="reemplazar",
        mensajes=MENSAJES_PREVIA,
        preparar=_preparar_previa(contexto.config, temporal, destino),
    )


def _plan_render_leccion(contexto: _Contexto) -> PlanTrabajo:
    versiones = [
        int(coincidencia.group(1))
        for nombre in _nombres_previas(contexto)
        if (coincidencia := PATRON_PREVIA.fullmatch(nombre)) is not None
    ]
    numero_version = max(versiones, default=0) + 1
    destino = _destino_en_leccion(
        contexto,
        "previa",
        f"previa-v{numero_version}.mp4",
    )
    temporal = _temporal_oculto(destino)
    return PlanTrabajo(
        accion="render-leccion",
        objetivo=None,
        comando=[
            _binario("npx"),
            "--no",
            "remotion",
            "render",
            "src/index.ts",
            "Leccion",
            str(temporal),
            f'--props={{"leccion":"{contexto.guion}"}}',
        ],
        cwd=contexto.config.estudio_dir,
        temporal=temporal,
        destino=destino,
        instalar="sin_pisar",
        patron_progreso=PROGRESO_REMOTION,
        tiempo_maximo=4 * 60 * 60,
        mensajes=MENSAJES_REMOTION,
        preparar=_preparar_en_leccion(contexto, ("previa",), temporal),
    )


def _plan_video_final(
    contexto: _Contexto,
    opciones: OpcionesAccion,
) -> PlanTrabajo:
    previa = _ruta_en_leccion(contexto, "previa", opciones.previa)
    destino = _destino_en_leccion(
        contexto,
        "publicar",
        "1-youtube-leccion",
        f"curso-{contexto.curso}-{contexto.numero:02d}-{contexto.slug}.mp4",
    )
    temporal = _temporal_oculto(destino)
    return PlanTrabajo(
        accion="video-final",
        objetivo=None,
        comando=[
            # -f: sin ~/.zshenv ni más configuración del usuario.
            "/bin/zsh",
            "-f",
            "herramientas/publicar/sonido-redes.sh",
            str(previa),
            str(temporal),
        ],
        cwd=contexto.config.estudio_dir,
        temporal=temporal,
        destino=destino,
        instalar="archivar",
        patron_progreso=PROGRESO_NINGUNO,
        tiempo_maximo=30 * 60,
        mensajes=MENSAJES_HERRAMIENTA,
        preparar=_preparar_en_leccion(
            contexto,
            ("publicar", "1-youtube-leccion"),
            temporal,
        ),
    )


def _plan_preparar_shorts(contexto: _Contexto) -> PlanTrabajo:
    return PlanTrabajo(
        accion="preparar-shorts",
        objetivo=None,
        comando=[
            _binario("node"),
            "herramientas/preparar-shorts.mjs",
            f"l{contexto.numero}",
        ],
        cwd=contexto.config.estudio_dir,
        patron_progreso=PROGRESO_HERRAMIENTA,
        tiempo_maximo=30 * 60,
        mensajes=MENSAJES_HERRAMIENTA,
    )


def _plan_render_short(
    contexto: _Contexto,
    opciones: OpcionesAccion,
) -> PlanTrabajo:
    destino = _destino_en_leccion(contexto, "shorts", f"{opciones.short}.mp4")
    temporal = _temporal_oculto(destino)
    return PlanTrabajo(
        accion="render-short",
        objetivo=opciones.short,
        comando=[
            _binario("npx"),
            "--no",
            "remotion",
            "render",
            "src/index.ts",
            "Short",
            str(temporal),
            f'--props={{"short":"{opciones.short}"}}',
        ],
        cwd=contexto.config.estudio_dir,
        temporal=temporal,
        destino=destino,
        instalar="archivar",
        patron_progreso=PROGRESO_REMOTION,
        tiempo_maximo=60 * 60,
        mensajes=MENSAJES_REMOTION,
        preparar=_preparar_en_leccion(contexto, ("shorts",), temporal),
    )


def plan_accion(
    config: Config,
    curso: str,
    numero: int,
    accion: IdAccion,
    opciones: OpcionesAccion,
) -> PlanTrabajo:
    contexto = _contexto(config, curso, numero)
    if contexto is None:
        raise AccionNoDisponible(404, "La lección no existe")
    evaluacion = _evaluar(contexto, accion, opciones, para_plan=True)
    if not evaluacion.disponible:
        raise AccionNoDisponible(
            evaluacion.estado_http,
            evaluacion.motivo or "La acción no está disponible",
        )
    try:
        if accion == "alinear-voz":
            return _plan_alinear_voz(contexto)
        if accion == "preparar-montaje":
            return _plan_preparar_montaje(contexto)
        if accion == "previa-grabacion":
            return _plan_previa_grabacion(contexto)
        if accion == "render-leccion":
            return _plan_render_leccion(contexto)
        if accion == "video-final":
            return _plan_video_final(contexto, opciones)
        if accion == "preparar-shorts":
            return _plan_preparar_shorts(contexto)
        return _plan_render_short(contexto, opciones)
    except ValueError as error:
        raise AccionNoDisponible(503, CARPETA_NO_PREPARABLE) from error


def estados_acciones(
    config: Config,
    bd: sqlite3.Connection,
    curso: str,
    numero: int,
) -> list[EstadoAccion] | None:
    contexto = _contexto(config, curso, numero)
    if contexto is None:
        return None
    estados: list[EstadoAccion] = []
    for accion in ORDEN_ACCIONES:
        evaluacion = _evaluar(
            contexto,
            accion,
            OpcionesAccion(),
            para_plan=False,
        )
        ultimo = ultimo_trabajo(bd, accion, curso, numero)
        ultimos: dict[str, Trabajo] = {}
        if accion == "render-short":
            for objetivo in evaluacion.opciones:
                trabajo = ultimo_trabajo(
                    bd,
                    accion,
                    curso,
                    numero,
                    objetivo,
                )
                if trabajo is not None:
                    ultimos[objetivo] = trabajo
            ultimo = max(ultimos.values(), key=lambda trabajo: trabajo.id, default=None)
        estados.append(
            EstadoAccion(
                id=accion,
                etiqueta=ETIQUETAS[accion],
                disponible=evaluacion.disponible,
                motivo=evaluacion.motivo,
                opciones=list(evaluacion.opciones),
                ultimo=ultimo,
                ultimos=ultimos,
            )
        )
    return estados
