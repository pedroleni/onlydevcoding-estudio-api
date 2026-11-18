from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import stat
import tempfile
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from estudio_api.config import Config
from estudio_api.entregas import carpeta_entregas, listar_entregas
from estudio_api.guion_textos import (
    ConflictoEscrituraGuion,
    cerrojo_escritura_guion,
    escribir_json_versionado,
    version_json,
)
from estudio_api.lectura import MAX_TAMANO_JSON, datos_curso
from estudio_api.propuesta import (
    Candidato,
    Propuesta,
    TomaPropuesta,
    destinos_guion,
    leer_propuesta,
)
from estudio_api.rutas import ruta_segura
from estudio_api.trabajos import (
    TrabajoEnMarcha,
    instalar_archivando,
    ocupar_sin_trabajo,
)

logger = logging.getLogger(__name__)

ERROR_COLOCACION = "No se han podido colocar las tomas"
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


class Asignacion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    archivo: str = Field(min_length=1, max_length=120)
    destino: str | None = Field(default=None, max_length=100)


class TomaColocada(BaseModel):
    archivo: str
    destino: str


class ResultadoColocar(BaseModel):
    colocadas: list[TomaColocada]
    ganchos: int


class ColocacionNoValida(Exception):
    def __init__(self, estado_http: int, mensaje: str) -> None:
        super().__init__(mensaje)
        self.estado_http = estado_http
        self.mensaje = mensaje


@dataclass(frozen=True)
class _PlanToma:
    toma: TomaPropuesta
    destino: str
    candidato: Candidato | None
    id_vertical: str | None
    texto_vertical: str | None


def id_toma_vertical(archivo: str) -> str:
    if archivo.startswith("Facetune") and len(archivo) >= 16:
        candidato = archivo[8:16]
        if all(caracter in "0123456789abcdefABCDEF" for caracter in candidato):
            return candidato.upper()
    return hashlib.sha256(archivo.encode()).hexdigest()[:8].upper()


def _lstat_o_none(ruta: Path) -> os.stat_result | None:
    try:
        return os.lstat(ruta)
    except FileNotFoundError:
        return None


def _ruta_literal(raiz: Path, *partes: str) -> Path:
    raiz = raiz.resolve()
    literal = raiz.joinpath(*partes)
    if ruta_segura(raiz, *partes) != literal:
        raise OSError("La ruta de colocación contiene enlaces simbólicos")
    actual = raiz
    for parte in partes:
        actual /= parte
        datos = _lstat_o_none(actual)
        if datos is not None and stat.S_ISLNK(datos.st_mode):
            raise OSError("La ruta de colocación contiene enlaces simbólicos")
    return literal


def _exigir_directorio_o_ausente(ruta: Path) -> None:
    datos = _lstat_o_none(ruta)
    if datos is not None and not stat.S_ISDIR(datos.st_mode):
        raise OSError("La carpeta de colocación no es un directorio real")


def _exigir_archivo_regular(ruta: Path) -> None:
    datos = os.lstat(ruta)
    if not stat.S_ISREG(datos.st_mode):
        raise OSError("La entrada de colocación no es un archivo regular")


def _exigir_destino_regular_o_ausente(ruta: Path) -> None:
    datos = _lstat_o_none(ruta)
    if datos is not None and not stat.S_ISREG(datos.st_mode):
        raise OSError("El destino de colocación no es un archivo regular")
    anteriores = ruta.parent / "anteriores"
    datos_anteriores = _lstat_o_none(anteriores)
    if datos_anteriores is not None and not stat.S_ISDIR(datos_anteriores.st_mode):
        raise OSError("La carpeta de anteriores no es un directorio real")


def _leer_shorts(
    ruta: Path, guion: str, numero: int
) -> tuple[dict[str, Any], str | None]:
    version, contenido = version_json(ruta)
    if contenido is None:
        return (
            {
                "leccion": guion,
                "numero": numero,
                "tomas": {},
                "ganchosEntregados": {},
                "frases": {},
                "shorts": [],
            },
            version,
        )
    if len(contenido) > MAX_TAMANO_JSON:
        raise OSError("shorts.json es demasiado grande")
    datos = json.loads(contenido.decode("utf-8"))
    if not isinstance(datos, dict):
        raise OSError("shorts.json no contiene un objeto")
    tomas = datos.get("tomas")
    entregados = datos.get("ganchosEntregados")
    if not isinstance(tomas, dict) or not isinstance(entregados, dict):
        raise OSError("shorts.json no tiene la estructura esperada")
    return copy.deepcopy(datos), version


def _escribir_propuesta(ruta: Path, datos: dict[str, Any]) -> None:
    temporal: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=ruta.parent,
            prefix=".propuesta.",
            suffix=".tmp",
            delete=False,
        ) as salida:
            temporal = Path(salida.name)
            json.dump(datos, salida, ensure_ascii=False, indent=2)
            salida.write("\n")
            salida.flush()
            os.fsync(salida.fileno())
        os.replace(temporal, ruta)
        temporal = None
        descriptor = os.open(
            ruta.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporal is not None:
            temporal.unlink(missing_ok=True)


def _prevalidar(
    propuesta: Propuesta,
    guion: dict[str, Any],
    asignaciones: list[Asignacion],
) -> list[_PlanToma]:
    por_archivo = {toma.archivo: toma for toma in propuesta.archivos}
    escenas, ganchos_guion = destinos_guion(guion)
    ganchos = {
        identificador: gancho["texto"]
        for identificador, gancho in ganchos_guion.items()
        if isinstance(gancho.get("texto"), str)
    }
    archivos_vistos: set[str] = set()
    destinos_vistos: set[str] = set()
    planes: list[_PlanToma] = []
    for asignacion in asignaciones:
        toma = por_archivo.get(asignacion.archivo)
        if toma is None or asignacion.archivo in archivos_vistos:
            raise ColocacionNoValida(422, "Esa toma no está entregada")
        archivos_vistos.add(asignacion.archivo)
        destino = asignacion.destino
        if destino is None:
            continue
        es_camara = destino in escenas
        es_gancho = destino in ganchos
        if not es_camara and not es_gancho and destino != "cierre":
            raise ColocacionNoValida(422, "Ese destino no existe")
        if (es_camara and toma.orientacion != "horizontal") or (
            (es_gancho or destino == "cierre") and toma.orientacion != "vertical"
        ):
            raise ColocacionNoValida(422, "Esa toma no encaja con ese destino")
        if destino != "cierre" and destino in destinos_vistos:
            raise ColocacionNoValida(422, "Hay dos tomas para el mismo destino")
        destinos_vistos.add(destino)
        candidato = None
        if es_camara:
            candidato = next(
                (
                    actual
                    for actual in toma.candidatos
                    if actual.tipo == "camara" and actual.id == destino
                ),
                None,
            )
            if candidato is None:
                raise ColocacionNoValida(422, "Esa toma no encaja con ese destino")
        planes.append(
            _PlanToma(
                toma=toma,
                destino=destino,
                candidato=candidato,
                id_vertical=None if es_camara else id_toma_vertical(toma.archivo),
                texto_vertical=(
                    None
                    if es_camara
                    else toma.texto
                    if destino == "cierre"
                    else ganchos[destino]
                ),
            )
        )
    return planes


def _crear_directorios_reales(ruta: Path, raiz: Path, creados: list[Path]) -> None:
    """Crea ``ruta`` bajo ``raiz`` y apunta en ``creados`` lo que no existía."""
    raiz = raiz.resolve()
    relativa = ruta.relative_to(raiz)
    actual = raiz
    _exigir_directorio_o_ausente(actual)
    for parte in relativa.parts:
        actual /= parte
        try:
            actual.mkdir()
        except FileExistsError:
            pass
        else:
            creados.append(actual)
        if not stat.S_ISDIR(os.lstat(actual).st_mode):
            raise OSError("La carpeta de colocación no es un directorio real")


def _temporal_colocando(destino: Path) -> Path:
    return destino.with_name(f".{destino.stem}.colocando{destino.suffix}")


@dataclass(frozen=True)
class _Salida:
    """Una copia que hay que instalar: de ``origen`` a ``destino``."""

    origen: Path
    destino: Path

    @property
    def temporal(self) -> Path:
        return _temporal_colocando(self.destino)


@dataclass(frozen=True)
class _JsonEscrito:
    ruta: Path
    original: bytes | None
    escrito: bytes
    copia: Path
    copia_existia: bool


@dataclass
class _Deshacer:
    """Lo que ha hecho la colocación, para devolverlo todo a su sitio."""

    directorios: list[Path] = field(default_factory=list)
    temporales: list[Path] = field(default_factory=list)
    movidos: list[tuple[Path, Path]] = field(default_factory=list)
    instaladas: list[tuple[Path, Path | None]] = field(default_factory=list)
    json: list[_JsonEscrito] = field(default_factory=list)


def _quitar_resto(temporal: Path) -> None:
    """Borra el temporal de un intento anterior que se cortó."""
    datos = _lstat_o_none(temporal)
    if datos is None:
        return
    if stat.S_ISDIR(datos.st_mode):
        raise OSError("El temporal de colocación es un directorio")
    os.unlink(temporal)


def _preparar_copia(salida: _Salida, deshacer: _Deshacer) -> None:
    descriptor = os.open(salida.origen, os.O_RDONLY | _NOFOLLOW)
    with os.fdopen(descriptor, "rb") as entrada:
        if not stat.S_ISREG(os.fstat(entrada.fileno()).st_mode):
            raise OSError("El origen de la copia no es un archivo regular")
        temporal = salida.temporal
        _quitar_resto(temporal)
        descriptor_salida = os.open(
            temporal,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW,
            0o600,
        )
        deshacer.temporales.append(temporal)
        with os.fdopen(descriptor_salida, "wb") as copia:
            shutil.copyfileobj(entrada, copia)
            copia.flush()
            os.fsync(copia.fileno())


def _contenido_json(datos: dict[str, Any]) -> bytes:
    return (json.dumps(datos, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _escribir_json(
    ruta: Path,
    datos: dict[str, Any],
    version: str | None,
    original: bytes | None,
    deshacer: _Deshacer,
) -> None:
    copia = ruta.with_name(f"{ruta.name}.antes-de-editar")
    deshacer.json.append(
        _JsonEscrito(
            ruta=ruta,
            original=original,
            escrito=_contenido_json(datos),
            copia=copia,
            copia_existia=os.path.lexists(copia),
        )
    )
    escribir_json_versionado(ruta, datos, version)


def _restaurar_json(escrito: _JsonEscrito) -> None:
    _, actual = version_json(escrito.ruta)
    # Solo se deshace lo que escribió la colocación: un cambio de fuera se respeta.
    if actual == escrito.escrito and actual != escrito.original:
        if escrito.original is None:
            escrito.ruta.unlink()
        else:
            temporal: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=escrito.ruta.parent,
                    prefix=f".{escrito.ruta.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as salida:
                    temporal = Path(salida.name)
                    salida.write(escrito.original)
                    salida.flush()
                    os.fsync(salida.fileno())
                shutil.copymode(escrito.ruta, temporal)
                os.replace(temporal, escrito.ruta)
                temporal = None
            finally:
                if temporal is not None:
                    temporal.unlink(missing_ok=True)
    if not escrito.copia_existia:
        escrito.copia.unlink(missing_ok=True)


def _intentar(descripcion: str, paso: Any, *argumentos: Any) -> None:
    try:
        paso(*argumentos)
    except OSError:
        logger.critical(
            "No se pudo deshacer la colocación (%s)", descripcion, exc_info=True
        )


def _devolver_original(destino: Path, origen: Path) -> None:
    if os.path.lexists(origen):
        raise OSError("Ya hay otro archivo en el sitio del original")
    os.rename(destino, origen)


def _retirar_instalada(destino: Path, archivado: Path | None) -> None:
    if archivado is None:
        os.unlink(destino)
    else:
        os.replace(archivado, destino)


def _quitar_directorio(directorio: Path) -> None:
    try:
        os.rmdir(directorio)
    except FileNotFoundError:
        pass


def _deshacer(deshacer: _Deshacer) -> None:
    """Deja el disco como estaba: originales, anteriores, guion y ``shorts.json``."""
    for escrito in reversed(deshacer.json):
        _intentar("JSON", _restaurar_json, escrito)
    for destino, archivado in reversed(deshacer.instaladas):
        _intentar("copia instalada", _retirar_instalada, destino, archivado)
    for origen, destino in reversed(deshacer.movidos):
        _intentar("original", _devolver_original, destino, origen)
    for temporal in deshacer.temporales:
        _intentar("temporal", _quitar_resto, temporal)
    for directorio in reversed(deshacer.directorios):
        _intentar("carpeta", _quitar_directorio, directorio)


def _instalar(
    salida: _Salida,
    deshacer: _Deshacer,
) -> None:
    anteriores = salida.destino.parent / "anteriores"
    if not os.path.lexists(anteriores):
        # Si la instalación crea ``anteriores/`` y luego hay que deshacer, se quita.
        deshacer.directorios.append(anteriores)
    archivado = instalar_archivando(salida.temporal, salida.destino)
    deshacer.instaladas.append((salida.destino, archivado))


def _limpiar_analisis(carpeta: Path, archivo: str) -> None:
    for extension in ("json", "wav", "origen"):
        ruta = _ruta_literal(carpeta, ".analisis", f"{archivo}.{extension}")
        datos = _lstat_o_none(ruta)
        if datos is not None and stat.S_ISREG(datos.st_mode):
            os.unlink(ruta)


def _hay_trabajo_en_marcha(bd: sqlite3.Connection) -> bool:
    return (
        bd.execute(
            "SELECT 1 FROM trabajo WHERE estado = 'en_marcha' LIMIT 1"
        ).fetchone()
        is not None
    )


def _salidas_del_plan(
    config: Config,
    carpeta: Path,
    guion: str,
    numero: int,
    plan: _PlanToma,
) -> list[_Salida]:
    origen = carpeta / plan.toma.archivo
    analisis = _ruta_literal(carpeta, ".analisis", f"{plan.toma.archivo}.json")
    _exigir_archivo_regular(analisis)
    if plan.candidato is not None:
        return [
            _Salida(
                origen,
                _ruta_literal(
                    config.estudio_dir,
                    "public",
                    "grabaciones",
                    guion,
                    f"{plan.destino}.mov",
                ),
            ),
            _Salida(
                analisis,
                _ruta_literal(
                    config.estudio_dir,
                    "lecciones",
                    "tomas",
                    guion,
                    f"{plan.destino}-camara.json",
                ),
            ),
        ]
    identificador = plan.id_vertical
    if identificador is None:
        raise OSError("Falta el identificador de la toma vertical")
    audio = _ruta_literal(carpeta, ".analisis", f"{plan.toma.archivo}.wav")
    _exigir_archivo_regular(audio)
    publica = ("public", "shorts", f"l{numero}", "tomas")
    datos = ("shorts", f"l{numero}", "tomas")
    return [
        _Salida(
            origen,
            _ruta_literal(
                config.estudio_dir, *publica, "original", f"{identificador}.mov"
            ),
        ),
        _Salida(
            origen,
            _ruta_literal(config.estudio_dir, *publica, f"{identificador}.mov"),
        ),
        _Salida(
            analisis,
            _ruta_literal(config.estudio_dir, *datos, f"{identificador}.json"),
        ),
        _Salida(
            audio,
            _ruta_literal(config.estudio_dir, *datos, f"{identificador}.wav"),
        ),
    ]


def _actualizar_propuesta(
    config: Config,
    curso: str,
    numero: int,
    datos: Any,
    carpeta: Path,
    propuesta: Propuesta,
    planes: list[_PlanToma],
) -> None:
    colocados = {plan.toma.archivo for plan in planes}
    restantes = [toma for toma in propuesta.archivos if toma.archivo not in colocados]
    quedan_videos = listar_entregas(config, curso, numero, datos=datos)
    ruta_propuesta = carpeta / "propuesta.json"
    if not quedan_videos:
        ruta_propuesta.unlink(missing_ok=True)
        return
    _escribir_propuesta(
        ruta_propuesta,
        {
            "version": propuesta.version,
            "guion": propuesta.guion,
            "archivos": [toma.model_dump(mode="json") for toma in restantes],
        },
    )


def _colocar_tomas(
    config: Config,
    bd: sqlite3.Connection,
    curso: str,
    numero: int,
    asignaciones: list[Asignacion],
    pila: ExitStack,
) -> ResultadoColocar:
    datos = datos_curso(config, curso)
    carpeta = carpeta_entregas(config, curso, numero, datos=datos)
    if carpeta is None:
        raise ColocacionNoValida(404, "La lección no existe")
    entregadas = listar_entregas(config, curso, numero, datos=datos)
    propuesta = leer_propuesta(config, curso, numero, datos=datos)
    if entregadas is None or propuesta is None:
        raise ColocacionNoValida(409, "Identifica las tomas antes de colocarlas")
    try:
        # Desde aquí y hasta terminar, ningún trabajo puede arrancar.
        pila.enter_context(ocupar_sin_trabajo())
    except TrabajoEnMarcha as error:
        raise ColocacionNoValida(409, "Ya hay un trabajo en marcha") from error
    if _hay_trabajo_en_marcha(bd):
        raise ColocacionNoValida(409, "Ya hay un trabajo en marcha")
    datos_guion = datos[2].get(numero) if datos is not None else None
    if datos_guion is None:
        raise ColocacionNoValida(409, "Identifica las tomas antes de colocarlas")
    guion = datos_guion[2]
    ruta_guion = datos_guion[3]
    version_guion = hashlib.sha256(datos_guion[4]).hexdigest()
    planes = _prevalidar(propuesta, guion, asignaciones)

    # Validación previa: nada se toca si algo falla.
    grabaciones = carpeta.parent
    videos = _ruta_literal(grabaciones, "videos")
    _exigir_directorio_o_ausente(videos)
    propuestas_en_disco = {entrega.archivo for entrega in entregadas}
    salidas: list[_Salida] = []
    destinos_vistos: set[Path] = set()
    for plan in planes:
        if plan.toma.archivo not in propuestas_en_disco:
            raise ColocacionNoValida(422, "Esa toma no está entregada")
        _exigir_archivo_regular(carpeta / plan.toma.archivo)
        if os.path.lexists(videos / plan.toma.archivo):
            raise ColocacionNoValida(409, "Ya hay una toma con ese nombre")
        for salida in _salidas_del_plan(config, carpeta, propuesta.guion, numero, plan):
            if salida.destino in destinos_vistos:
                raise ColocacionNoValida(422, "Hay dos tomas para el mismo destino")
            destinos_vistos.add(salida.destino)
            salidas.append(salida)
    for salida in salidas:
        _exigir_directorio_o_ausente(salida.destino.parent)
        _exigir_destino_regular_o_ausente(salida.destino)

    hay_verticales = any(plan.candidato is None for plan in planes)
    ruta_shorts = _ruta_literal(
        config.estudio_dir,
        "shorts",
        f"l{numero}",
        "shorts.json",
    )
    shorts: dict[str, Any] | None = None
    version_shorts: str | None = None
    if hay_verticales:
        _exigir_destino_regular_o_ausente(ruta_shorts)
        shorts, version_shorts = _leer_shorts(ruta_shorts, propuesta.guion, numero)

    guion_actualizado = copy.deepcopy(guion)
    escenas, _ = destinos_guion(guion_actualizado)
    for plan in planes:
        if plan.candidato is None:
            if (
                shorts is None
                or plan.id_vertical is None
                or plan.texto_vertical is None
            ):
                raise OSError("Faltan los datos de la toma vertical")
            shorts["tomas"][plan.id_vertical] = plan.texto_vertical
            if plan.destino != "cierre":
                shorts["ganchosEntregados"][plan.destino] = plan.id_vertical
            continue
        candidato = plan.candidato
        escenas[plan.destino]["toma"] = {
            "original": f"grabaciones/videos/{plan.toma.archivo}",
            "video": f"grabaciones/{propuesta.guion}/{plan.destino}.mov",
            "desde": candidato.desde,
            "hasta": candidato.hasta,
            "cues": candidato.cues,
        }

    version_actual_guion, original_guion = version_json(ruta_guion)
    if version_actual_guion != version_guion:
        raise ConflictoEscrituraGuion
    original_shorts: bytes | None = None
    if hay_verticales:
        version_actual_shorts, original_shorts = version_json(ruta_shorts)
        if version_actual_shorts != version_shorts:
            raise ConflictoEscrituraGuion

    deshacer = _Deshacer()
    try:
        # a) Preparación: carpetas y temporales ocultos, nada visible cambia.
        _crear_directorios_reales(videos, grabaciones, deshacer.directorios)
        for salida in salidas:
            _crear_directorios_reales(
                salida.destino.parent, config.estudio_dir, deshacer.directorios
            )
        if hay_verticales:
            _crear_directorios_reales(
                ruta_shorts.parent, config.estudio_dir, deshacer.directorios
            )
        for salida in salidas:
            _preparar_copia(salida, deshacer)

        # b) Instalación: originales, copias (archivando) y JSON.
        for plan in planes:
            origen = carpeta / plan.toma.archivo
            destino_original = videos / plan.toma.archivo
            if os.path.lexists(destino_original):
                raise ColocacionNoValida(409, "Ya hay una toma con ese nombre")
            os.rename(origen, destino_original)
            deshacer.movidos.append((origen, destino_original))
        for salida in salidas:
            _instalar(salida, deshacer)
        _escribir_json(
            ruta_guion, guion_actualizado, version_guion, original_guion, deshacer
        )
        if shorts is not None:
            _escribir_json(
                ruta_shorts, shorts, version_shorts, original_shorts, deshacer
            )
    except BaseException:
        _deshacer(deshacer)
        raise

    # c) Solo con todo instalado: análisis y propuesta. Si esto falla, las tomas
    # ya están colocadas; lo que quede se ignora al leer la propuesta.
    for plan in planes:
        try:
            _limpiar_analisis(carpeta, plan.toma.archivo)
        except OSError:
            logger.warning("No se pudo limpiar el análisis de una toma", exc_info=True)
    try:
        _actualizar_propuesta(config, curso, numero, datos, carpeta, propuesta, planes)
    except OSError, ValueError:
        logger.warning("No se pudo actualizar la propuesta", exc_info=True)

    return ResultadoColocar(
        colocadas=[
            TomaColocada(archivo=plan.toma.archivo, destino=plan.destino)
            for plan in planes
        ],
        ganchos=sum(
            1 for plan in planes if plan.candidato is None and plan.destino != "cierre"
        ),
    )


def colocar_tomas(
    config: Config,
    bd: sqlite3.Connection,
    curso: str,
    numero: int,
    asignaciones: list[Asignacion],
) -> ResultadoColocar:
    try:
        with cerrojo_escritura_guion(), ExitStack() as pila:
            return _colocar_tomas(config, bd, curso, numero, asignaciones, pila)
    except ColocacionNoValida:
        raise
    except (ConflictoEscrituraGuion, OSError, UnicodeError, ValueError) as error:
        raise ColocacionNoValida(503, ERROR_COLOCACION) from error
