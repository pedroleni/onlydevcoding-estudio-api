import json
import re
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from estudio_api.config import Config
from estudio_api.modelos import (
    Curso,
    Escena,
    EstadoLeccion,
    Leccion,
    LeccionResumen,
    Pieza,
)
from estudio_api.rutas import ruta_segura

PATRON_ID_CURSO = re.compile(r"^[a-z0-9-]{1,40}$")
PATRON_CARPETA_LECCION = re.compile(r"^(\d{2})-(.+)$")
PATRON_PREVIA = re.compile(r"^previa-v(\d+)\.mp4$", re.IGNORECASE)
PATRON_SHORT = re.compile(r"^short-(\d+)(?:-.+)?\.mp4$", re.IGNORECASE)


def _entradas_seguras(raiz: Path, directorio: Path) -> list[Path]:
    if not directorio.is_dir():
        return []

    entradas: list[Path] = []
    try:
        nombres = sorted(entrada.name for entrada in directorio.iterdir())
    except OSError:
        return []

    raiz_resuelta = raiz.resolve()
    for nombre in nombres:
        try:
            relativa = directorio.resolve().relative_to(raiz_resuelta)
            entradas.append(ruta_segura(raiz_resuelta, *relativa.parts, nombre))
        except OSError, ValueError:
            continue
    return entradas


def _leer_json(ruta: Path) -> dict[str, Any] | None:
    try:
        with ruta.open(encoding="utf-8") as archivo:
            datos = json.load(archivo)
    except OSError, UnicodeError, json.JSONDecodeError:
        return None
    return datos if isinstance(datos, dict) else None


def _texto(valor: object, defecto: str = "") -> str:
    return valor if isinstance(valor, str) else defecto


def _ruta_publica(raiz: Path, prefijo: str, ruta: Path) -> str:
    raiz_resuelta = raiz.resolve()
    relativa = ruta.resolve().relative_to(raiz_resuelta)
    segura = ruta_segura(raiz_resuelta, *relativa.parts)
    return PurePosixPath(
        prefijo,
        *segura.relative_to(raiz_resuelta).parts,
    ).as_posix()


def _subruta(raiz: Path, directorio: Path, *partes: str) -> Path:
    relativa = directorio.resolve().relative_to(raiz.resolve())
    return ruta_segura(raiz, *relativa.parts, *partes)


def _carpetas_leccion(raiz: Path, carpeta_curso: Path) -> dict[int, tuple[str, Path]]:
    carpetas: dict[int, tuple[str, Path]] = {}
    for ruta in _entradas_seguras(raiz, carpeta_curso):
        coincidencia = PATRON_CARPETA_LECCION.fullmatch(ruta.name)
        if not ruta.is_dir() or coincidencia is None:
            continue
        numero = int(coincidencia.group(1))
        if 1 <= numero <= 999:
            carpetas.setdefault(numero, (coincidencia.group(2), ruta))
    return carpetas


def _cursos_en_disco(
    config: Config,
) -> list[tuple[str, Path, dict[int, tuple[str, Path]]]]:
    cursos: list[tuple[str, Path, dict[int, tuple[str, Path]]]] = []
    for carpeta in _entradas_seguras(config.cursos_dir, config.cursos_dir.resolve()):
        identificador = carpeta.name.lower()
        if not carpeta.is_dir() or PATRON_ID_CURSO.fullmatch(identificador) is None:
            continue
        lecciones = _carpetas_leccion(config.cursos_dir, carpeta)
        if lecciones:
            cursos.append((identificador, carpeta, lecciones))
    return sorted(cursos, key=lambda curso: curso[0])


def _carpeta_desde_guion(
    config: Config,
    datos: dict[str, Any],
    nombre_curso: str,
    numero: int,
) -> tuple[str, Path] | None:
    carpeta = datos.get("carpeta")
    if not isinstance(carpeta, str):
        return None

    ruta_posix = PurePosixPath(carpeta)
    if ruta_posix.is_absolute() or len(ruta_posix.parts) != 2:
        return None
    if any(parte in {"", ".", ".."} for parte in ruta_posix.parts):
        return None
    if ruta_posix.parts[0].lower() != nombre_curso.lower():
        return None

    coincidencia = PATRON_CARPETA_LECCION.fullmatch(ruta_posix.parts[1])
    if coincidencia is None or int(coincidencia.group(1)) != numero:
        return None
    try:
        ruta = ruta_segura(config.cursos_dir, *ruta_posix.parts)
    except ValueError:
        return None
    return coincidencia.group(2), ruta


def _guiones_curso(
    config: Config,
    identificador: str,
    nombre_curso: str,
) -> dict[int, tuple[str, Path, dict[str, Any]]]:
    try:
        directorio = ruta_segura(config.estudio_dir, "lecciones")
    except ValueError:
        return {}

    patron = re.compile(rf"^{re.escape(identificador)}-(\d{{2,3}})\.json$")
    guiones: dict[int, tuple[str, Path, dict[str, Any]]] = {}
    for ruta in _entradas_seguras(config.estudio_dir, directorio):
        coincidencia = patron.fullmatch(ruta.name)
        if not ruta.is_file() or coincidencia is None:
            continue
        numero = int(coincidencia.group(1))
        if not 1 <= numero <= 999:
            continue
        datos = _leer_json(ruta)
        if datos is None:
            continue
        carpeta = _carpeta_desde_guion(config, datos, nombre_curso, numero)
        if carpeta is None:
            continue
        slug, ruta_carpeta = carpeta
        guiones.setdefault(numero, (slug, ruta_carpeta, datos))
    return guiones


def _datos_curso(
    config: Config,
    curso: str,
) -> (
    tuple[
        Path,
        dict[int, tuple[str, Path]],
        dict[int, tuple[str, Path, dict[str, Any]]],
    ]
    | None
):
    if PATRON_ID_CURSO.fullmatch(curso) is None:
        return None
    encontrado = next(
        (datos for datos in _cursos_en_disco(config) if datos[0] == curso),
        None,
    )
    if encontrado is None:
        return None
    _, carpeta_curso, carpetas = encontrado
    guiones = _guiones_curso(config, curso, carpeta_curso.name)
    return carpeta_curso, carpetas, guiones


def _titulo_desde_slug(slug: str) -> str:
    return slug.replace("-", " ").capitalize()


def leer_cursos(config: Config) -> list[Curso]:
    cursos: list[Curso] = []
    for identificador, carpeta, carpetas in _cursos_en_disco(config):
        guiones = _guiones_curso(config, identificador, carpeta.name)
        primer_guion = guiones[min(guiones)][2] if guiones else None
        nombre = _texto(primer_guion.get("ficha")) if primer_guion else ""
        cursos.append(
            Curso(
                id=identificador,
                nombre=nombre or carpeta.name,
                carpeta=_ruta_publica(config.cursos_dir, "cursos", carpeta),
                lecciones=len(set(carpetas) | set(guiones)),
            )
        )
    return cursos


def leer_lecciones(config: Config, curso: str) -> list[LeccionResumen]:
    datos_curso = _datos_curso(config, curso)
    if datos_curso is None:
        return []
    _, carpetas, guiones = datos_curso

    lecciones: list[LeccionResumen] = []
    for numero in sorted(set(carpetas) | set(guiones)):
        slug = guiones[numero][0] if numero in guiones else carpetas[numero][0]
        guion = guiones[numero][2] if numero in guiones else None
        titulo = _texto(guion.get("titulo")) if guion else ""
        lecciones.append(
            LeccionResumen(
                curso=curso,
                numero=numero,
                slug=slug,
                titulo=titulo or _titulo_desde_slug(slug),
                estado=EstadoLeccion(),
            )
        )
    return lecciones


def _tiempos_montaje(
    config: Config,
    curso: str,
    numero: int,
) -> tuple[dict[str, tuple[float, float]], float | None]:
    try:
        ruta = ruta_segura(
            config.estudio_dir,
            "public",
            "lecciones",
            f"{curso}-{numero:02d}",
            "montaje.json",
        )
    except ValueError:
        return {}, None
    datos = _leer_json(ruta)
    if datos is None:
        return {}, None
    fps = datos.get("fps")
    if not isinstance(fps, (int, float)) or isinstance(fps, bool) or fps <= 0:
        return {}, None

    tiempos: dict[str, tuple[float, float]] = {}
    acumulada = 0.0
    escenas = datos.get("escenas")
    if isinstance(escenas, list):
        for escena in escenas:
            if not isinstance(escena, dict):
                continue
            duracion = escena.get("duracion")
            if (
                not isinstance(duracion, (int, float))
                or isinstance(duracion, bool)
                or duracion < 0
            ):
                continue
            identificador = escena.get("id")
            if isinstance(identificador, str):
                tiempos[identificador] = (acumulada / fps, duracion / fps)
            acumulada += duracion

    duracion_total = datos.get("duracion")
    if (
        isinstance(duracion_total, (int, float))
        and not isinstance(duracion_total, bool)
        and duracion_total >= 0
    ):
        return tiempos, duracion_total / fps
    return tiempos, acumulada / fps if escenas else None


def _escenas(
    guion: dict[str, Any] | None,
    tiempos: dict[str, tuple[float, float]],
) -> list[Escena]:
    if guion is None or not isinstance(guion.get("escenas"), list):
        return []

    resultado: list[Escena] = []
    for datos in guion["escenas"]:
        if not isinstance(datos, dict):
            continue
        identificador = _texto(datos.get("id"))
        modo = datos.get("modo")
        if not identificador or modo not in {"voz", "camara", "animacion"}:
            continue
        cues = datos.get("cues")
        textos = []
        if isinstance(cues, list):
            textos = [
                cue["texto"]
                for cue in cues
                if isinstance(cue, dict) and isinstance(cue.get("texto"), str)
            ]
        inicio, duracion = tiempos.get(identificador, (None, None))
        resultado.append(
            Escena(
                id=identificador,
                modo=modo,
                tipo=_texto(datos.get("tipo")),
                titulo=_texto(datos.get("titulo")),
                textos=textos,
                inicio_s=inicio,
                duracion_s=duracion,
            )
        )
    return resultado


def _archivos_directos(
    raiz: Path,
    directorio: Path,
    predicado: Callable[[str], bool],
) -> list[Path]:
    return [
        ruta
        for ruta in _entradas_seguras(raiz, directorio)
        if ruta.is_file() and predicado(ruta.name)
    ]


def _es_anterior(nombre: str) -> bool:
    return Path(nombre).stem.lower().endswith("-anterior")


def _longitud_prefijo_comun(izquierda: str, derecha: str) -> int:
    longitud = 0
    for caracter_izquierdo, caracter_derecho in zip(
        izquierda.casefold(), derecha.casefold(), strict=False
    ):
        if caracter_izquierdo != caracter_derecho:
            break
        longitud += 1
    return longitud


def _previas(config: Config, carpeta: Path | None) -> list[str]:
    if carpeta is None:
        return []
    try:
        directorio = _subruta(config.cursos_dir, carpeta, "previa")
    except ValueError:
        return []
    archivos = _archivos_directos(
        config.cursos_dir,
        directorio,
        lambda nombre: PATRON_PREVIA.fullmatch(nombre) is not None,
    )
    archivos.sort(key=lambda ruta: int(PATRON_PREVIA.fullmatch(ruta.name).group(1)))
    return [_ruta_publica(config.cursos_dir, "cursos", ruta) for ruta in archivos]


def _piezas(
    config: Config,
    carpeta: Path | None,
    titulo_leccion: str,
) -> list[Pieza]:
    video_leccion: str | None = None
    portadas_leccion: list[str] = []
    if carpeta is None:
        return [Pieza(id="leccion", tipo="leccion", titulo=titulo_leccion)]

    relativa = carpeta.relative_to(config.cursos_dir.resolve())
    try:
        youtube = ruta_segura(
            config.cursos_dir,
            *relativa.parts,
            "publicar",
            "1-youtube-leccion",
        )
        verticales = ruta_segura(
            config.cursos_dir,
            *relativa.parts,
            "publicar",
            "2-shorts-y-reels",
        )
    except ValueError:
        return [Pieza(id="leccion", tipo="leccion", titulo=titulo_leccion)]

    videos_leccion = _archivos_directos(
        config.cursos_dir,
        youtube,
        lambda nombre: nombre.lower().endswith(".mp4") and not _es_anterior(nombre),
    )
    if videos_leccion:
        video_leccion = _ruta_publica(config.cursos_dir, "cursos", videos_leccion[0])
    miniaturas = _archivos_directos(
        config.cursos_dir,
        youtube,
        lambda nombre: (
            nombre.lower().startswith("miniatura-")
            and nombre.lower().endswith(".jpg")
            and not _es_anterior(nombre)
        ),
    )
    portadas_leccion = [
        _ruta_publica(config.cursos_dir, "cursos", ruta) for ruta in miniaturas
    ]
    piezas = [
        Pieza(
            id="leccion",
            tipo="leccion",
            titulo=titulo_leccion,
            video=video_leccion,
            portadas=portadas_leccion,
        )
    ]

    reels = _archivos_directos(
        config.cursos_dir,
        verticales,
        lambda nombre: (
            nombre.lower().startswith("reel-")
            and nombre.lower().endswith(".mp4")
            and not _es_anterior(nombre)
        ),
    )
    portadas_reels = _archivos_directos(
        config.cursos_dir,
        verticales,
        lambda nombre: (
            nombre.lower().startswith("portada-reel-")
            and nombre.lower().endswith(".jpg")
            and "-anterior" not in Path(nombre).stem.lower()
        ),
    )
    portadas_por_reel: dict[Path, list[Path]] = {reel: [] for reel in reels}
    if len(reels) == 1:
        portadas_por_reel[reels[0]] = portadas_reels
    elif reels:
        for portada in portadas_reels:
            nombre_portada = portada.stem[len("portada-") :]
            reel = max(
                reels,
                key=lambda candidato: _longitud_prefijo_comun(
                    nombre_portada, candidato.stem
                ),
            )
            portadas_por_reel[reel].append(portada)

    for ruta in reels:
        piezas.append(
            Pieza(
                id=ruta.stem,
                tipo="reel",
                titulo=ruta.stem.replace("-", " ").capitalize(),
                video=_ruta_publica(config.cursos_dir, "cursos", ruta),
                portadas=[
                    _ruta_publica(config.cursos_dir, "cursos", portada)
                    for portada in portadas_por_reel[ruta]
                ],
            )
        )

    shorts: list[tuple[int, Path]] = []
    for ruta in _archivos_directos(
        config.cursos_dir,
        verticales,
        lambda nombre: (
            PATRON_SHORT.fullmatch(nombre) is not None and not _es_anterior(nombre)
        ),
    ):
        coincidencia = PATRON_SHORT.fullmatch(ruta.name)
        shorts.append((int(coincidencia.group(1)), ruta))
    shorts.sort(key=lambda elemento: (elemento[0], elemento[1].name))

    try:
        opciones = _subruta(
            config.cursos_dir,
            verticales,
            "portadas-opciones",
        )
    except ValueError:
        opciones = verticales
    for numero, ruta in shorts:
        prefijo = f"portada-short-{numero}-"
        portadas = _archivos_directos(
            config.cursos_dir,
            verticales,
            lambda nombre, prefijo=prefijo: (
                nombre.lower().startswith(prefijo)
                and nombre.lower().endswith(".jpg")
                and not _es_anterior(nombre)
            ),
        )
        if opciones != verticales:
            portadas.extend(
                _archivos_directos(
                    config.cursos_dir,
                    opciones,
                    lambda nombre, prefijo=prefijo: (
                        nombre.lower().startswith(prefijo)
                        and nombre.lower().endswith(".jpg")
                        and not _es_anterior(nombre)
                    ),
                )
            )
        piezas.append(
            Pieza(
                id=f"short-{numero}",
                tipo="short",
                titulo=f"Short {numero}",
                video=_ruta_publica(config.cursos_dir, "cursos", ruta),
                portadas=[
                    _ruta_publica(config.cursos_dir, "cursos", portada)
                    for portada in portadas
                ],
            )
        )
    return piezas


def leer_leccion(config: Config, curso: str, numero: int) -> Leccion | None:
    if isinstance(numero, bool) or not 1 <= numero <= 999:
        return None
    datos_curso = _datos_curso(config, curso)
    if datos_curso is None:
        return None
    _, carpetas, guiones = datos_curso
    if numero not in carpetas and numero not in guiones:
        return None

    slug = guiones[numero][0] if numero in guiones else carpetas[numero][0]
    carpeta = carpetas[numero][1] if numero in carpetas else None
    guion = guiones[numero][2] if numero in guiones else None
    titulo = _texto(guion.get("titulo")) if guion else ""
    titulo = titulo or _titulo_desde_slug(slug)
    tiempos, duracion = _tiempos_montaje(config, curso, numero)
    return Leccion(
        curso=curso,
        numero=numero,
        slug=slug,
        titulo=titulo,
        estado=EstadoLeccion(),
        subtitulo=_texto(guion.get("subtitulo")) if guion else "",
        escenas=_escenas(guion, tiempos),
        piezas=_piezas(config, carpeta, titulo),
        previas=_previas(config, carpeta),
        duracion_s=duracion,
    )
