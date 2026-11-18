from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from estudio_api.config import Config
from estudio_api.entregas import (
    PATRON_ARCHIVO_ENTREGA,
    carpeta_entregas,
    listar_entregas,
)
from estudio_api.lectura import MAX_TAMANO_JSON, datos_curso

PATRON_ESCENA_CAMARA = re.compile(r"^E[0-9]{2}$")


class DestinoPropuesta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tipo: Literal["camara", "gancho"]
    id: str

    @model_validator(mode="after")
    def validar_id(self) -> Self:
        if self.tipo == "camara" and PATRON_ESCENA_CAMARA.fullmatch(self.id) is None:
            raise ValueError("El id de cámara no es válido")
        if self.tipo == "gancho" and not self.id:
            raise ValueError("El id de gancho no es válido")
        return self


class Candidato(DestinoPropuesta):
    puntuacion: float = Field(ge=0, le=1, allow_inf_nan=False)
    desde: float = Field(ge=0, allow_inf_nan=False)
    hasta: float = Field(ge=0, allow_inf_nan=False)
    cues: list[float] | None = None

    @model_validator(mode="after")
    def validar_cues_finitos(self) -> Self:
        if self.tipo == "gancho" and "cues" in self.model_fields_set:
            raise ValueError("Un gancho no lleva cues")
        if self.tipo == "camara" and self.cues is None:
            raise ValueError("Una escena de cámara exige cues")
        if self.cues is not None and any(
            not isinstance(cue, (int, float))
            or isinstance(cue, bool)
            or not float("-inf") < cue < float("inf")
            for cue in self.cues
        ):
            raise ValueError("Los cues tienen que ser números finitos")
        return self


class TomaPropuesta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    archivo: str
    bytes: int = Field(ge=0)
    orientacion: Literal["horizontal", "vertical"]
    duracion: float = Field(gt=0, allow_inf_nan=False)
    texto: str = Field(max_length=2000)
    propuesta: DestinoPropuesta | None
    repite: DestinoPropuesta | None
    candidatos: list[Candidato]

    @model_validator(mode="after")
    def validar_nombre_y_tiempos(self) -> Self:
        if PATRON_ARCHIVO_ENTREGA.fullmatch(self.archivo) is None:
            raise ValueError("El nombre de la toma no es válido")
        tipo_esperado = "camara" if self.orientacion == "horizontal" else "gancho"
        destinos = [self.propuesta, self.repite, *self.candidatos]
        if any(
            destino is not None and destino.tipo != tipo_esperado
            for destino in destinos
        ):
            raise ValueError("La orientación no coincide con el destino")
        for candidato in self.candidatos:
            if candidato.desde > candidato.hasta or candidato.hasta > self.duracion:
                raise ValueError("Los tiempos no están dentro de la duración")
            if candidato.cues is not None and any(
                cue < 0 or cue > self.duracion for cue in candidato.cues
            ):
                raise ValueError("Los cues no están dentro de la duración")
        return self


class Propuesta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: Literal[1]
    guion: str
    archivos: list[TomaPropuesta]


def _destinos_guion(
    guion: dict[str, Any],
) -> tuple[dict[str, int], set[str]]:
    camara: dict[str, int] = {}
    escenas = guion.get("escenas")
    if isinstance(escenas, list):
        for escena in escenas:
            if not isinstance(escena, dict) or escena.get("modo") != "camara":
                continue
            identificador = escena.get("id")
            cues = escena.get("cues")
            if (
                isinstance(identificador, str)
                and PATRON_ESCENA_CAMARA.fullmatch(identificador) is not None
                and isinstance(cues, list)
            ):
                camara[identificador] = len(cues)
    ganchos: set[str] = set()
    datos_ganchos = guion.get("ganchos")
    if isinstance(datos_ganchos, list):
        for gancho in datos_ganchos:
            identificador = gancho.get("id") if isinstance(gancho, dict) else None
            if isinstance(identificador, str) and identificador:
                ganchos.add(identificador)
    return camara, ganchos


def _destino_existe(
    destino: DestinoPropuesta,
    camara: dict[str, int],
    ganchos: set[str],
) -> bool:
    ids = camara if destino.tipo == "camara" else ganchos
    return destino.id in ids


def _toma_valida_para_guion(
    toma: TomaPropuesta,
    camara: dict[str, int],
    ganchos: set[str],
) -> bool:
    if any(
        destino is not None and not _destino_existe(destino, camara, ganchos)
        for destino in (toma.propuesta, toma.repite)
    ):
        return False
    for candidato in toma.candidatos:
        if not _destino_existe(candidato, camara, ganchos):
            return False
        if (
            candidato.tipo == "camara"
            and len(candidato.cues or []) != camara[candidato.id]
        ):
            return False
    return True


def _leer_json_propuesta(carpeta: Path) -> dict[str, Any] | None:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor_carpeta = os.open(carpeta, os.O_RDONLY | directory | nofollow)
        try:
            descriptor = os.open(
                "propuesta.json",
                os.O_RDONLY | nofollow,
                dir_fd=descriptor_carpeta,
            )
        finally:
            os.close(descriptor_carpeta)
        try:
            datos_archivo = os.fstat(descriptor)
            if (
                not stat.S_ISREG(datos_archivo.st_mode)
                or datos_archivo.st_size > MAX_TAMANO_JSON
            ):
                return None
            with os.fdopen(descriptor, "rb") as archivo:
                descriptor = -1
                contenido = archivo.read(MAX_TAMANO_JSON + 1)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if len(contenido) > MAX_TAMANO_JSON:
            return None
        datos = json.loads(contenido.decode("utf-8"))
    except OSError, UnicodeError, RecursionError, ValueError:
        return None
    return datos if isinstance(datos, dict) else None


def leer_propuesta(
    config: Config,
    curso: str,
    numero: int,
) -> Propuesta | None:
    leido = datos_curso(config, curso)
    datos_guion = leido[2].get(numero) if leido is not None else None
    if datos_guion is None:
        return None
    guion = datos_guion[2]
    identificador_guion = datos_guion[3].stem
    try:
        carpeta = carpeta_entregas(config, curso, numero)
        entregadas = listar_entregas(config, curso, numero)
    except OSError:
        return None
    if carpeta is None or entregadas is None:
        return None
    datos = _leer_json_propuesta(carpeta)
    if (
        datos is None
        or type(datos.get("version")) is not int
        or datos.get("version") != 1
        or datos.get("guion") != identificador_guion
        or not isinstance(datos.get("archivos"), list)
    ):
        return None

    archivos_en_disco = {entrega.archivo for entrega in entregadas}
    camara, ganchos = _destinos_guion(guion)
    archivos: list[TomaPropuesta] = []
    for datos_toma in datos["archivos"]:
        try:
            toma = TomaPropuesta.model_validate(datos_toma)
        except TypeError, ValidationError:
            continue
        if toma.archivo not in archivos_en_disco:
            continue
        if not _toma_valida_para_guion(toma, camara, ganchos):
            continue
        archivos.append(toma)
    return Propuesta(version=1, guion=identificador_guion, archivos=archivos)
