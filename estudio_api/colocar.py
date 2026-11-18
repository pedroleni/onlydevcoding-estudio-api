from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
from dataclasses import dataclass
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
from estudio_api.propuesta import Candidato, Propuesta, TomaPropuesta, leer_propuesta
from estudio_api.rutas import ruta_segura
from estudio_api.trabajos import instalar_archivando

ERROR_COLOCACION = "No se han podido colocar las tomas"


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


def _crear_directorios_reales(ruta: Path, raiz: Path) -> None:
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
        if not stat.S_ISDIR(os.lstat(actual).st_mode):
            raise OSError("La carpeta de colocación no es un directorio real")


def _copiar_archivando(origen: Path, destino: Path) -> None:
    temporal: Path | None = None
    descriptor_origen = os.open(origen, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        if not stat.S_ISREG(os.fstat(descriptor_origen).st_mode):
            raise OSError("El origen de la copia no es un archivo regular")
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destino.parent,
            prefix=f".{destino.name}.",
            suffix=".copiando",
            delete=False,
        ) as salida:
            temporal = Path(salida.name)
            with os.fdopen(descriptor_origen, "rb") as entrada:
                descriptor_origen = -1
                shutil.copyfileobj(entrada, salida)
            salida.flush()
            os.fsync(salida.fileno())
        instalar_archivando(temporal, destino)
        temporal = None
    finally:
        if descriptor_origen >= 0:
            os.close(descriptor_origen)
        if temporal is not None:
            temporal.unlink(missing_ok=True)


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


def _destinos_guion(
    guion: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    escenas: dict[str, dict[str, Any]] = {}
    for escena in guion.get("escenas", []):
        if not isinstance(escena, dict) or escena.get("modo") != "camara":
            continue
        identificador = escena.get("id")
        if isinstance(identificador, str):
            escenas[identificador] = escena
    ganchos: dict[str, str] = {}
    for gancho in guion.get("ganchos", []):
        if not isinstance(gancho, dict):
            continue
        identificador = gancho.get("id")
        texto = gancho.get("texto")
        if isinstance(identificador, str) and isinstance(texto, str):
            ganchos[identificador] = texto
    return escenas, ganchos


def _prevalidar(
    propuesta: Propuesta,
    guion: dict[str, Any],
    asignaciones: list[Asignacion],
) -> list[_PlanToma]:
    por_archivo = {toma.archivo: toma for toma in propuesta.archivos}
    escenas, ganchos = _destinos_guion(guion)
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


def _hay_trabajo_en_marcha(bd: sqlite3.Connection) -> bool:
    return (
        bd.execute(
            "SELECT 1 FROM trabajo WHERE estado = 'en_marcha' LIMIT 1"
        ).fetchone()
        is not None
    )


def _limpiar_analisis(carpeta: Path, archivo: str) -> None:
    analisis = carpeta / ".analisis"
    if not analisis.exists():
        return
    prefijo = f"{archivo}."
    with os.scandir(analisis) as entradas:
        for entrada in entradas:
            if not entrada.name.startswith(prefijo):
                continue
            datos = entrada.stat(follow_symlinks=False)
            if stat.S_ISREG(datos.st_mode):
                os.unlink(entrada.path)


def _colocar_tomas(
    config: Config,
    bd: sqlite3.Connection,
    curso: str,
    numero: int,
    asignaciones: list[Asignacion],
) -> ResultadoColocar:
    datos = datos_curso(config, curso)
    carpeta = carpeta_entregas(config, curso, numero, datos=datos)
    entregadas = listar_entregas(config, curso, numero, datos=datos)
    propuesta = leer_propuesta(config, curso, numero, datos=datos)
    if carpeta is None or entregadas is None or propuesta is None:
        raise ColocacionNoValida(409, "Identifica las tomas antes de colocarlas")
    if _hay_trabajo_en_marcha(bd):
        raise ColocacionNoValida(409, "Ya hay un trabajo en marcha")
    datos_guion = datos[2].get(numero) if datos is not None else None
    if datos_guion is None:
        raise ColocacionNoValida(409, "Identifica las tomas antes de colocarlas")
    guion = datos_guion[2]
    ruta_guion = datos_guion[3]
    version_guion = hashlib.sha256(datos_guion[4]).hexdigest()
    planes = _prevalidar(propuesta, guion, asignaciones)

    grabaciones = carpeta.parent
    videos = _ruta_literal(grabaciones, "videos")
    _exigir_directorio_o_ausente(videos)
    propuestas_en_disco = {entrega.archivo for entrega in entregadas}
    destinos_salida: list[Path] = []
    for plan in planes:
        if plan.toma.archivo not in propuestas_en_disco:
            raise ColocacionNoValida(422, "Esa toma no está entregada")
        origen = carpeta / plan.toma.archivo
        _exigir_archivo_regular(origen)
        destino_original = videos / plan.toma.archivo
        if os.path.lexists(destino_original):
            raise ColocacionNoValida(409, "Ya hay una toma con ese nombre")
        analisis = _ruta_literal(carpeta, ".analisis", f"{plan.toma.archivo}.json")
        _exigir_archivo_regular(analisis)
        if plan.candidato is not None:
            destinos_salida.extend(
                [
                    _ruta_literal(
                        config.estudio_dir,
                        "public",
                        "grabaciones",
                        propuesta.guion,
                        f"{plan.destino}.mov",
                    ),
                    _ruta_literal(
                        config.estudio_dir,
                        "lecciones",
                        "tomas",
                        propuesta.guion,
                        f"{plan.destino}-camara.json",
                    ),
                ]
            )
        else:
            identificador = plan.id_vertical
            if identificador is None:
                raise OSError("Falta el identificador de la toma vertical")
            audio = _ruta_literal(carpeta, ".analisis", f"{plan.toma.archivo}.wav")
            _exigir_archivo_regular(audio)
            destinos_salida.extend(
                [
                    _ruta_literal(
                        config.estudio_dir,
                        "public",
                        "shorts",
                        f"l{numero}",
                        "tomas",
                        "original",
                        f"{identificador}.mov",
                    ),
                    _ruta_literal(
                        config.estudio_dir,
                        "public",
                        "shorts",
                        f"l{numero}",
                        "tomas",
                        f"{identificador}.mov",
                    ),
                    _ruta_literal(
                        config.estudio_dir,
                        "shorts",
                        f"l{numero}",
                        "tomas",
                        f"{identificador}.json",
                    ),
                    _ruta_literal(
                        config.estudio_dir,
                        "shorts",
                        f"l{numero}",
                        "tomas",
                        f"{identificador}.wav",
                    ),
                ]
            )
    for destino in destinos_salida:
        _exigir_directorio_o_ausente(destino.parent)
        _exigir_destino_regular_o_ausente(destino)

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
    escenas, _ = _destinos_guion(guion_actualizado)
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

    version_actual_guion, _ = version_json(ruta_guion)
    if version_actual_guion != version_guion:
        raise ConflictoEscrituraGuion
    if hay_verticales:
        version_actual_shorts, _ = version_json(ruta_shorts)
        if version_actual_shorts != version_shorts:
            raise ConflictoEscrituraGuion

    _crear_directorios_reales(videos, grabaciones)
    for destino in destinos_salida:
        _crear_directorios_reales(destino.parent, config.estudio_dir)
    if hay_verticales:
        _crear_directorios_reales(ruta_shorts.parent, config.estudio_dir)

    colocadas: list[TomaColocada] = []
    ganchos = 0
    for plan in planes:
        origen = carpeta / plan.toma.archivo
        destino_original = videos / plan.toma.archivo
        if os.path.lexists(destino_original):
            raise ColocacionNoValida(409, "Ya hay una toma con ese nombre")
        os.rename(origen, destino_original)
        analisis = carpeta / ".analisis" / f"{plan.toma.archivo}.json"
        if plan.candidato is not None:
            video = _ruta_literal(
                config.estudio_dir,
                "public",
                "grabaciones",
                propuesta.guion,
                f"{plan.destino}.mov",
            )
            datos_toma = _ruta_literal(
                config.estudio_dir,
                "lecciones",
                "tomas",
                propuesta.guion,
                f"{plan.destino}-camara.json",
            )
            _copiar_archivando(destino_original, video)
            _copiar_archivando(analisis, datos_toma)
        else:
            identificador = plan.id_vertical
            if identificador is None:
                raise OSError("Falta el identificador vertical")
            base_publica = _ruta_literal(
                config.estudio_dir,
                "public",
                "shorts",
                f"l{numero}",
                "tomas",
            )
            base_datos = _ruta_literal(
                config.estudio_dir,
                "shorts",
                f"l{numero}",
                "tomas",
            )
            _copiar_archivando(
                destino_original,
                base_publica / "original" / f"{identificador}.mov",
            )
            _copiar_archivando(destino_original, base_publica / f"{identificador}.mov")
            _copiar_archivando(analisis, base_datos / f"{identificador}.json")
            _copiar_archivando(
                carpeta / ".analisis" / f"{plan.toma.archivo}.wav",
                base_datos / f"{identificador}.wav",
            )
            if plan.destino != "cierre":
                ganchos += 1
        _limpiar_analisis(carpeta, plan.toma.archivo)
        colocadas.append(TomaColocada(archivo=plan.toma.archivo, destino=plan.destino))

    escribir_json_versionado(ruta_guion, guion_actualizado, version_guion)
    if shorts is not None:
        escribir_json_versionado(ruta_shorts, shorts, version_shorts)

    colocados = {plan.toma.archivo for plan in planes}
    restantes = [toma for toma in propuesta.archivos if toma.archivo not in colocados]
    quedan_videos = listar_entregas(config, curso, numero, datos=datos)
    ruta_propuesta = carpeta / "propuesta.json"
    if not quedan_videos:
        ruta_propuesta.unlink(missing_ok=True)
    else:
        _escribir_propuesta(
            ruta_propuesta,
            {
                "version": propuesta.version,
                "guion": propuesta.guion,
                "archivos": [toma.model_dump(mode="json") for toma in restantes],
            },
        )
    return ResultadoColocar(colocadas=colocadas, ganchos=ganchos)


def colocar_tomas(
    config: Config,
    bd: sqlite3.Connection,
    curso: str,
    numero: int,
    asignaciones: list[Asignacion],
) -> ResultadoColocar:
    try:
        with cerrojo_escritura_guion():
            return _colocar_tomas(config, bd, curso, numero, asignaciones)
    except ColocacionNoValida:
        raise
    except (ConflictoEscrituraGuion, OSError, UnicodeError, ValueError) as error:
        raise ColocacionNoValida(503, ERROR_COLOCACION) from error
