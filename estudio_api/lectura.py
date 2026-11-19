import json
import math
import os
import re
import sqlite3
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from estudio_api.config import Config
from estudio_api.decisiones import estados, portadas_elegidas
from estudio_api.estado import ContextoEstado, calcular_estado
from estudio_api.modelos import (
    Curso,
    Escena,
    Leccion,
    LeccionResumen,
    Pieza,
)
from estudio_api.previas import PATRON_PREVIA
from estudio_api.rutas import ruta_segura
from estudio_api.tareas import cursos_app

PATRON_ID_CURSO = re.compile(r"^[a-z0-9-]{1,40}$")
PATRON_CARPETA_LECCION = re.compile(r"^(\d{2,3})-(.+)$")
PATRON_SHORT = re.compile(r"^short-(\d+)(?:-.+)?\.mp4$", re.IGNORECASE)
EXTENSIONES_IMAGEN = frozenset({".jpg", ".jpeg", ".png", ".webp"})
MAX_TAMANO_JSON = 5 * 1024 * 1024
FPS_MINIMOS = 1.0
FPS_MAXIMOS = 1000.0
MAX_DURACION_SEGUNDOS = 24 * 60 * 60


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


def _leer_json_y_bytes(ruta: Path) -> tuple[dict[str, Any], bytes] | None:
    try:
        with ruta.open("rb") as archivo:
            if os.fstat(archivo.fileno()).st_size > MAX_TAMANO_JSON:
                return None
            contenido = archivo.read()
            if len(contenido) > MAX_TAMANO_JSON:
                return None
        datos = json.loads(contenido.decode("utf-8"))
    except OSError, UnicodeError, RecursionError, ValueError:
        return None
    return (datos, contenido) if isinstance(datos, dict) else None


def _leer_json(ruta: Path) -> dict[str, Any] | None:
    lectura = _leer_json_y_bytes(ruta)
    return lectura[0] if lectura is not None else None


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


def ids_cursos_en_disco(config: Config) -> set[str]:
    """Cursos de disco con el mismo criterio que el listado: carpeta con lecciones."""
    return {identificador for identificador, _, _ in _cursos_en_disco(config)}


def curso_existe(config: Config, bd: sqlite3.Connection, curso: str) -> bool:
    """El mismo criterio que el listado: curso de disco con lecciones o dado de alta en la app."""
    return curso in ids_cursos_en_disco(config) or any(
        existente.id == curso for existente in cursos_app(bd)
    )


def curso_en_disco(config: Config, curso: str) -> bool:
    if PATRON_ID_CURSO.fullmatch(curso) is None:
        return False
    return any(
        carpeta.is_dir() and carpeta.name.lower() == curso
        for carpeta in _entradas_seguras(
            config.cursos_dir,
            config.cursos_dir.resolve(),
        )
    )


def _datos_carpeta_desde_guion(
    datos: dict[str, Any],
    nombre_curso: str,
    numero: int,
) -> tuple[PurePosixPath, re.Match[str]] | None:
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
    return ruta_posix, coincidencia


def _carpeta_desde_guion(
    config: Config,
    datos: dict[str, Any],
    nombre_curso: str,
    numero: int,
) -> tuple[str, Path] | None:
    datos_carpeta = _datos_carpeta_desde_guion(datos, nombre_curso, numero)
    if datos_carpeta is None:
        return None
    ruta_posix, coincidencia = datos_carpeta
    try:
        ruta = ruta_segura(config.cursos_dir, *ruta_posix.parts)
    except ValueError:
        return None
    return coincidencia.group(2), ruta


def _guiones_curso(
    config: Config,
    identificador: str,
    nombre_curso: str,
) -> dict[int, tuple[str, Path, dict[str, Any], Path, bytes]]:
    try:
        directorio = ruta_segura(config.estudio_dir, "lecciones")
    except ValueError:
        return {}

    patron = re.compile(rf"^{re.escape(identificador)}-(\d{{2,3}})\.json$")
    guiones: dict[int, tuple[str, Path, dict[str, Any], Path, bytes]] = {}
    for ruta in _entradas_seguras(config.estudio_dir, directorio):
        coincidencia = patron.fullmatch(ruta.name)
        if not ruta.is_file() or coincidencia is None:
            continue
        numero = int(coincidencia.group(1))
        if not 1 <= numero <= 999:
            continue
        lectura = _leer_json_y_bytes(ruta)
        if lectura is None:
            continue
        datos, contenido = lectura
        carpeta = _carpeta_desde_guion(config, datos, nombre_curso, numero)
        if carpeta is None:
            continue
        slug, ruta_carpeta = carpeta
        guiones.setdefault(numero, (slug, ruta_carpeta, datos, ruta, contenido))
    return guiones


def _datos_curso(
    config: Config,
    curso: str,
) -> (
    tuple[
        Path,
        dict[int, tuple[str, Path]],
        dict[int, tuple[str, Path, dict[str, Any], Path, bytes]],
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


# Lectura completa de un curso (carpetas y guiones), reutilizable dentro de una petición.
datos_curso = _datos_curso
_SIN_DATOS: Any = object()


def carpeta_de_trabajo(
    leido: (
        tuple[
            Path,
            dict[int, tuple[str, Path]],
            dict[int, tuple[str, Path, dict[str, Any], Path, bytes]],
        ]
        | None
    ),
    numero: int,
) -> Path | None:
    """Carpeta única de una lección para tomas, teleprompter y ficha.

    Gana la carpeta de disco; si no existe, la que declara el guion (ya
    validada por ``datos_curso``). Sin curso en ``datos_curso`` no hay carpeta.
    """
    if leido is None:
        return None
    _, carpetas, guiones = leido
    if numero in carpetas:
        return carpetas[numero][1]
    if numero in guiones:
        return guiones[numero][1]
    return None


def carpeta_leccion(config: Config, curso: str, numero: int) -> Path | None:
    if isinstance(numero, bool) or not 1 <= numero <= 999:
        return None
    leido = _datos_curso(config, curso)
    if leido is None:
        return None
    _, carpetas, _ = leido
    datos_carpeta = carpetas.get(numero)
    return datos_carpeta[1] if datos_carpeta is not None else None


def _titulo_desde_slug(slug: str) -> str:
    return slug.replace("-", " ").capitalize()


def leer_cursos(
    config: Config,
    bd: sqlite3.Connection | None = None,
) -> list[Curso]:
    cursos_disco: list[Curso] = []
    for identificador, carpeta, carpetas in _cursos_en_disco(config):
        guiones = _guiones_curso(config, identificador, carpeta.name)
        primer_guion = guiones[min(guiones)][2] if guiones else None
        nombre = _texto(primer_guion.get("ficha")) if primer_guion else ""
        cursos_disco.append(
            Curso(
                id=identificador,
                nombre=nombre or carpeta.name,
                carpeta=_ruta_publica(config.cursos_dir, "cursos", carpeta),
                lecciones=len(set(carpetas) | set(guiones)),
                en_disco=True,
            )
        )
    if bd is None:
        return cursos_disco

    cursos_registrados = cursos_app(bd)
    ids_disco = {curso.id for curso in cursos_disco}
    entradas_raiz = {
        ruta.name.lower(): ruta
        for ruta in _entradas_seguras(config.cursos_dir, config.cursos_dir.resolve())
        if ruta.is_dir() and PATRON_ID_CURSO.fullmatch(ruta.name.lower()) is not None
    }
    cursos_solo_app: list[Curso] = []
    for registrado in cursos_registrados:
        if registrado.id in ids_disco:
            continue
        carpeta = entradas_raiz.get(registrado.id)
        if carpeta is not None:
            cursos_disco.append(
                Curso(
                    id=registrado.id,
                    nombre=registrado.nombre,
                    carpeta=_ruta_publica(config.cursos_dir, "cursos", carpeta),
                    lecciones=0,
                    en_disco=True,
                )
            )
            ids_disco.add(registrado.id)
            continue
        cursos_solo_app.append(
            Curso(
                id=registrado.id,
                nombre=registrado.nombre,
                carpeta=None,
                lecciones=0,
                en_disco=False,
            )
        )
    cursos_disco.sort(key=lambda curso: curso.id)
    return [*cursos_disco, *cursos_solo_app]


def leer_lecciones(
    config: Config,
    curso: str,
    bd: sqlite3.Connection | None = None,
    datos: Any = _SIN_DATOS,
) -> list[LeccionResumen]:
    leido = _datos_curso(config, curso) if datos is _SIN_DATOS else datos
    if leido is None:
        return []
    _, carpetas, guiones = leido

    lecciones: list[LeccionResumen] = []
    for numero in sorted(set(carpetas) | set(guiones)):
        slug = guiones[numero][0] if numero in guiones else carpetas[numero][0]
        carpeta = carpetas[numero][1] if numero in carpetas else None
        guion = guiones[numero][2] if numero in guiones else None
        identificador_guion = guiones[numero][3].stem if numero in guiones else None
        titulo = _texto(guion.get("titulo")) if guion else ""
        titulo = titulo or _titulo_desde_slug(slug)
        piezas = _piezas(config, carpeta, titulo)
        publicacion, estados_publicacion, miniatura = _decisiones_publicacion(
            config,
            curso,
            numero,
            carpeta,
            piezas,
            bd,
        )
        lecciones.append(
            LeccionResumen(
                curso=curso,
                numero=numero,
                slug=slug,
                titulo=titulo,
                estado=calcular_estado(
                    config,
                    curso,
                    numero,
                    carpeta_de_trabajo(leido, numero),
                    guion,
                    ContextoEstado(
                        publicacion=publicacion,
                        estados_publicacion=estados_publicacion,
                        miniatura=miniatura,
                        identificador_guion=identificador_guion,
                    ),
                ),
            )
        )
    return lecciones


def _tiempos_de_escenas(
    valor_escenas: object,
    fps: float,
) -> tuple[dict[str, tuple[float, float]], float, bool]:
    tiempos: dict[str, tuple[float, float]] = {}
    acumulada_s = 0.0
    linea_tiempo_valida = True
    if not isinstance(valor_escenas, list):
        return tiempos, acumulada_s, linea_tiempo_valida

    for escena in valor_escenas:
        if not isinstance(escena, dict):
            continue
        duracion_s = _duracion_en_segundos(escena.get("duracion"), fps)
        if duracion_s is None:
            linea_tiempo_valida = False
            continue
        identificador = escena.get("id")
        if linea_tiempo_valida and isinstance(identificador, str):
            tiempos[identificador] = (acumulada_s, duracion_s)
        if linea_tiempo_valida:
            acumulada_s += duracion_s
            if not math.isfinite(acumulada_s) or acumulada_s > MAX_DURACION_SEGUNDOS:
                linea_tiempo_valida = False
    return tiempos, acumulada_s, linea_tiempo_valida


def _tiempos_montaje(
    config: Config,
    identificador_guion: str,
) -> tuple[dict[str, tuple[float, float]], float | None]:
    try:
        ruta = ruta_segura(
            config.estudio_dir,
            "public",
            "lecciones",
            identificador_guion,
            "montaje.json",
        )
    except ValueError:
        return {}, None
    datos = _leer_json(ruta)
    if datos is None:
        return {}, None
    fps = _numero_finito_positivo(
        datos.get("fps"),
        minimo=FPS_MINIMOS,
        maximo=FPS_MAXIMOS,
    )
    if fps is None:
        return {}, None

    escenas = datos.get("escenas")
    tiempos, acumulada_s, linea_tiempo_valida = _tiempos_de_escenas(escenas, fps)

    if "duracion" in datos:
        return tiempos, _duracion_en_segundos(datos["duracion"], fps)
    if isinstance(escenas, list) and escenas and linea_tiempo_valida:
        return tiempos, acumulada_s
    return tiempos, None


def _numero_finito_positivo(
    valor: object,
    *,
    minimo: float = 0.0,
    maximo: float | None = None,
) -> float | None:
    if not isinstance(valor, (int, float)) or isinstance(valor, bool):
        return None
    try:
        numero = float(valor)
    except OverflowError, ValueError:
        return None
    if not math.isfinite(numero) or numero <= 0 or numero < minimo:
        return None
    if maximo is not None and numero > maximo:
        return None
    return numero


def _duracion_en_segundos(valor: object, fps: float) -> float | None:
    fotogramas = _numero_finito_positivo(valor)
    if fotogramas is None:
        return None
    segundos = fotogramas / fps
    if not math.isfinite(segundos) or segundos <= 0 or segundos > MAX_DURACION_SEGUNDOS:
        return None
    return segundos


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
    # Los nombres que empiezan por «.» (como los temporales ``.….generando.mp4``)
    # no son vídeos, previas, shorts ni piezas.
    return [
        ruta
        for ruta in _entradas_seguras(raiz, directorio)
        if not ruta.name.startswith(".") and ruta.is_file() and predicado(ruta.name)
    ]


def _es_imagen(nombre: str) -> bool:
    return Path(nombre).suffix.lower() in EXTENSIONES_IMAGEN


def _imagenes_directas(
    raiz: Path,
    directorio: Path,
    predicado: Callable[[str], bool] = lambda _nombre: True,
) -> list[Path]:
    imagenes = _archivos_directos(
        raiz,
        directorio,
        lambda nombre: _es_imagen(nombre) and predicado(nombre),
    )
    return sorted(imagenes, key=lambda ruta: (ruta.name.casefold(), ruta.name))


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

    def clave(ruta: Path) -> tuple[int, bool, str, str]:
        coincidencia = PATRON_PREVIA.fullmatch(ruta.name)
        assert coincidencia is not None
        return (
            int(coincidencia.group(1)),
            coincidencia.group(2) is not None,
            ruta.name.casefold(),
            ruta.name,
        )

    archivos.sort(key=clave)
    return [_ruta_publica(config.cursos_dir, "cursos", ruta) for ruta in archivos]


def _titulos_publicados(config: Config, carpeta: Path | None) -> dict[str, str]:
    """Títulos por id de pieza de publicar/publicacion.json; vacío si no es legible."""
    if carpeta is None:
        return {}
    try:
        relativa = carpeta.relative_to(config.cursos_dir.resolve())
        ruta = ruta_segura(
            config.cursos_dir, *relativa.parts, "publicar", "publicacion.json"
        )
    except ValueError:
        return {}
    datos = _leer_json(ruta)
    piezas = datos.get("piezas") if datos is not None else None
    if not isinstance(piezas, dict):
        return {}
    titulos: dict[str, str] = {}
    for identificador, pieza in piezas.items():
        titulo = pieza.get("titulo") if isinstance(pieza, dict) else None
        if isinstance(titulo, str) and titulo.strip():
            titulos[identificador] = titulo
    return titulos


def _piezas(
    config: Config,
    carpeta: Path | None,
    titulo_leccion: str,
) -> list[Pieza]:
    titulos = _titulos_publicados(config, carpeta)
    return [
        pieza.model_copy(update={"titulo": titulos.get(pieza.id, pieza.titulo)})
        for pieza in _piezas_de_disco(config, carpeta, titulo_leccion)
    ]


def _pieza_leccion_de_disco(
    config: Config,
    youtube: Path,
    titulo_leccion: str,
) -> Pieza:
    video_leccion: str | None = None
    videos_leccion = _archivos_directos(
        config.cursos_dir,
        youtube,
        lambda nombre: nombre.lower().endswith(".mp4") and not _es_anterior(nombre),
    )
    if videos_leccion:
        video_leccion = _ruta_publica(config.cursos_dir, "cursos", videos_leccion[0])
    miniaturas = _imagenes_directas(
        config.cursos_dir,
        youtube,
        lambda nombre: (
            nombre.lower().startswith("miniatura-") and not _es_anterior(nombre)
        ),
    )
    try:
        opciones_miniatura = _subruta(
            config.cursos_dir,
            youtube,
            "opciones-miniatura",
        )
    except ValueError:
        opciones_miniatura = youtube
    if opciones_miniatura != youtube:
        miniaturas.extend(_imagenes_directas(config.cursos_dir, opciones_miniatura))
    return Pieza(
        id="leccion",
        tipo="leccion",
        titulo=titulo_leccion,
        video=video_leccion,
        portadas=[
            _ruta_publica(config.cursos_dir, "cursos", ruta) for ruta in miniaturas
        ],
    )


def _repartir_portadas_reels(
    reels: list[Path],
    portadas: list[Path],
) -> dict[Path, list[Path]]:
    portadas_por_reel: dict[Path, list[Path]] = {reel: [] for reel in reels}
    if len(reels) == 1:
        portadas_por_reel[reels[0]] = portadas
    elif reels:
        for portada in portadas:
            nombre_portada = portada.stem[len("portada-") :]
            reel = max(
                reels,
                key=lambda candidato: _longitud_prefijo_comun(
                    nombre_portada, candidato.stem
                ),
            )
            portadas_por_reel[reel].append(portada)
    return portadas_por_reel


def _piezas_reels_de_disco(
    config: Config,
    verticales: Path,
) -> tuple[list[Pieza], Path]:

    reels = _archivos_directos(
        config.cursos_dir,
        verticales,
        lambda nombre: (
            nombre.lower().startswith("reel-")
            and nombre.lower().endswith(".mp4")
            and not _es_anterior(nombre)
        ),
    )
    portadas_reels = _imagenes_directas(
        config.cursos_dir,
        verticales,
        lambda nombre: (
            nombre.lower().startswith("portada-reel-")
            and "-anterior" not in Path(nombre).stem.lower()
        ),
    )
    try:
        opciones_compartidas = _subruta(
            config.cursos_dir,
            verticales,
            "portadas-opciones",
        )
    except ValueError:
        opciones_compartidas = verticales
    if opciones_compartidas != verticales:
        portadas_reels.extend(
            _imagenes_directas(
                config.cursos_dir,
                opciones_compartidas,
                lambda nombre: nombre.lower().startswith("portada-reel"),
            )
        )
    portadas_por_reel = _repartir_portadas_reels(reels, portadas_reels)

    piezas: list[Pieza] = []
    for indice, ruta in enumerate(reels, start=1):
        piezas.append(
            Pieza(
                id=("reel-salida" if len(reels) == 1 else f"reel-salida-{indice}"),
                tipo="reel",
                titulo=ruta.stem.replace("-", " ").capitalize(),
                video=_ruta_publica(config.cursos_dir, "cursos", ruta),
                portadas=[
                    _ruta_publica(config.cursos_dir, "cursos", portada)
                    for portada in portadas_por_reel[ruta]
                ],
            )
        )
    return piezas, opciones_compartidas


def _piezas_shorts_de_disco(
    config: Config,
    verticales: Path,
    opciones_compartidas: Path,
) -> list[Pieza]:
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

    piezas: list[Pieza] = []
    for numero, ruta in shorts:
        prefijo = f"portada-short-{numero}-"
        portadas = _imagenes_directas(
            config.cursos_dir,
            verticales,
            lambda nombre, prefijo=prefijo: (
                nombre.lower().startswith(prefijo) and not _es_anterior(nombre)
            ),
        )
        for sufijo in ("opciones", "poses", "verticales"):
            try:
                carpeta_opciones = _subruta(
                    config.cursos_dir,
                    verticales,
                    f"portadas-short-{numero}-{sufijo}",
                )
            except ValueError:
                continue
            portadas.extend(_imagenes_directas(config.cursos_dir, carpeta_opciones))
        if opciones_compartidas != verticales:
            portadas.extend(
                _imagenes_directas(
                    config.cursos_dir,
                    opciones_compartidas,
                    lambda nombre, prefijo=prefijo: nombre.lower().startswith(prefijo),
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


def _piezas_de_disco(
    config: Config,
    carpeta: Path | None,
    titulo_leccion: str,
) -> list[Pieza]:
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

    pieza_leccion = _pieza_leccion_de_disco(config, youtube, titulo_leccion)
    piezas_reels, opciones_compartidas = _piezas_reels_de_disco(
        config,
        verticales,
    )
    piezas_shorts = _piezas_shorts_de_disco(
        config,
        verticales,
        opciones_compartidas,
    )
    return [pieza_leccion, *piezas_reels, *piezas_shorts]


def _decisiones_publicacion(
    config: Config,
    curso: str,
    numero: int,
    carpeta: Path | None,
    piezas: list[Pieza],
    bd: sqlite3.Connection | None,
):
    if bd is None:
        return None, {}, None

    # Importación local para evitar el ciclo publicacion -> lectura -> estado.
    from estudio_api.publicacion import leer_publicacion, portadas_candidatas

    lectura = leer_publicacion(config, carpeta)
    publicacion = lectura.publicacion
    estados_guardados = estados(bd, curso, numero)
    elegidas = portadas_elegidas(bd, curso, numero)

    portadas_disco = next(
        (list(pieza.portadas) for pieza in piezas if pieza.id == "leccion"),
        [],
    )
    pieza_publicacion = (
        publicacion.piezas.get("leccion") if publicacion is not None else None
    )
    candidatas = portadas_candidatas(
        config,
        carpeta,
        portadas_disco,
        pieza_publicacion,
    )
    elegida = elegidas.get("leccion")
    miniatura = elegida if elegida in candidatas else None
    return publicacion, estados_guardados, miniatura


def leer_leccion(
    config: Config,
    curso: str,
    numero: int,
    bd: sqlite3.Connection | None = None,
    datos: Any = _SIN_DATOS,
) -> Leccion | None:
    if isinstance(numero, bool) or not 1 <= numero <= 999:
        return None
    leido = _datos_curso(config, curso) if datos is _SIN_DATOS else datos
    if leido is None:
        return None
    _, carpetas, guiones = leido
    if numero not in carpetas and numero not in guiones:
        return None

    slug = guiones[numero][0] if numero in guiones else carpetas[numero][0]
    carpeta = carpetas[numero][1] if numero in carpetas else None
    guion = guiones[numero][2] if numero in guiones else None
    titulo = _texto(guion.get("titulo")) if guion else ""
    titulo = titulo or _titulo_desde_slug(slug)
    identificador_guion = (
        guiones[numero][3].stem if numero in guiones else f"{curso}-{numero:02d}"
    )
    tiempos, duracion = _tiempos_montaje(config, identificador_guion)
    piezas = _piezas(config, carpeta, titulo)
    publicacion, estados_publicacion, miniatura = _decisiones_publicacion(
        config,
        curso,
        numero,
        carpeta,
        piezas,
        bd,
    )
    montaje = None
    if numero in guiones:
        # Importación local: acciones consume las primitivas de lectura para
        # construir el catálogo y no debe crear un ciclo al cargar el módulo.
        from estudio_api.acciones import estado_montaje

        montaje = estado_montaje(
            config,
            identificador_guion,
            carpeta_de_trabajo(leido, numero),
            guiones[numero][2],
        )
    return Leccion(
        curso=curso,
        numero=numero,
        slug=slug,
        titulo=titulo,
        estado=calcular_estado(
            config,
            curso,
            numero,
            carpeta_de_trabajo(leido, numero),
            guion,
            ContextoEstado(
                publicacion=publicacion,
                estados_publicacion=estados_publicacion,
                miniatura=miniatura,
                identificador_guion=(
                    guiones[numero][3].stem if numero in guiones else None
                ),
            ),
        ),
        subtitulo=_texto(guion.get("subtitulo")) if guion else "",
        escenas=_escenas(guion, tiempos),
        piezas=piezas,
        previas=_previas(config, carpeta),
        duracion_s=duracion,
        montaje=montaje,
    )
