import re
import stat
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from estudio_api.config import Config
from estudio_api.lectura import _leer_json, _ruta_publica
from estudio_api.medios import TIPOS_MEDIO
from estudio_api.rutas import ruta_segura

Red = Literal["youtube", "instagram", "tiktok", "linkedin"]

ERROR_LECTURA = "No se ha podido leer publicacion.json"
PATRON_ID_PIEZA = re.compile(
    r"^(leccion|reel-salida(-[1-9][0-9]*)?|short-[1-9][0-9]*)$"
)
MAX_LINEAS = 30
MAX_CARACTERES_LINEA = 300


class TextosRed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    titulos: list[str] = Field(default_factory=list)
    descripcion: str | None = None
    etiquetas: list[str] = Field(default_factory=list)
    texto: str | None = None
    comentario_fijado: str | None = None
    ajustes: list[str] = Field(default_factory=list)
    video: str | None = None
    notas: str | None = None


class PiezaPublicacion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    titulo: str | None = None
    video: str | None = None
    duracion: str | None = None
    portadas: list[str] = Field(default_factory=list)
    fecha_propuesta: str | None = None
    redes: dict[Red, TextosRed] = Field(default_factory=dict)


class Publicacion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    piezas: dict[str, PiezaPublicacion]
    despues_de_publicar: list[str] = Field(default_factory=list)
    notas: str | None = None

    @model_validator(mode="after")
    def validar_contenido(self) -> Self:
        for identificador, pieza in self.piezas.items():
            if PATRON_ID_PIEZA.fullmatch(identificador) is None:
                raise ValueError(f"El id de pieza no es válido: {identificador}")
            for red, textos in pieza.redes.items():
                validar_textos(red, textos)

        _validar_lineas("despues_de_publicar", self.despues_de_publicar)
        return self


class LecturaPublicacion(BaseModel):
    publicacion: Publicacion | None = None
    error: str | None = None


def _validar_maximo(campo: str, valor: str | None, limite: int) -> None:
    if valor is not None and len(valor) > limite:
        raise ValueError(f"El campo {campo} tiene un límite de {limite} caracteres")


def _validar_lineas(campo: str, lineas: list[str]) -> None:
    if len(lineas) > MAX_LINEAS:
        raise ValueError(f"El campo {campo} tiene un límite de {MAX_LINEAS} líneas")
    if any(len(linea) > MAX_CARACTERES_LINEA for linea in lineas):
        raise ValueError(
            f"El campo {campo} tiene un límite de "
            f"{MAX_CARACTERES_LINEA} caracteres por línea"
        )


def validar_textos(red: Red, textos: TextosRed) -> None:
    if red == "youtube":
        for titulo in textos.titulos:
            _validar_maximo("titulos", titulo, 100)
        _validar_maximo("descripcion", textos.descripcion, 5000)
        _validar_maximo("etiquetas", ", ".join(textos.etiquetas), 500)
    elif red in {"instagram", "tiktok"}:
        _validar_maximo("texto", textos.texto, 2200)
    elif red == "linkedin":
        _validar_maximo("texto", textos.texto, 3000)
    else:
        raise ValueError(f"La red no está permitida: {red}")

    _validar_maximo("comentario_fijado", textos.comentario_fijado, 10000)
    _validar_lineas("ajustes", textos.ajustes)


def _raiz_publicar(config: Config, carpeta: Path) -> Path | None:
    try:
        relativa = carpeta.resolve().relative_to(config.cursos_dir.resolve())
        return ruta_segura(config.cursos_dir, *relativa.parts, "publicar")
    except OSError, ValueError:
        return None


def _resolver_medio(publicar: Path, relativa: str) -> Path | None:
    if not relativa or relativa.startswith("/") or "\\" in relativa:
        return None

    partes = relativa.split("/")
    if any(parte in {"", "node_modules"} or parte.startswith(".") for parte in partes):
        return None

    try:
        ruta = ruta_segura(publicar, *partes)
        partes_reales = ruta.relative_to(publicar.resolve()).parts
        datos = ruta.stat()
    except OSError, ValueError:
        return None
    if any(
        parte in {"", "node_modules"} or parte.startswith(".")
        for parte in partes_reales
    ):
        return None
    if ruta.suffix.lower() not in TIPOS_MEDIO or not stat.S_ISREG(datos.st_mode):
        return None
    return ruta


def _texto_codificable_en_utf8(valor: object) -> bool:
    if isinstance(valor, str):
        try:
            valor.encode("utf-8")
        except UnicodeError:
            return False
        return True
    if isinstance(valor, dict):
        return all(
            _texto_codificable_en_utf8(clave) and _texto_codificable_en_utf8(elemento)
            for clave, elemento in valor.items()
        )
    if isinstance(valor, list):
        return all(_texto_codificable_en_utf8(elemento) for elemento in valor)
    return True


def ruta_publica_publicar(
    config: Config,
    carpeta: Path,
    relativa: str,
) -> str | None:
    publicar = _raiz_publicar(config, carpeta)
    if publicar is None:
        return None
    ruta = _resolver_medio(publicar, relativa)
    if ruta is None:
        return None
    try:
        return _ruta_publica(config.cursos_dir, "cursos", ruta)
    except OSError, ValueError:
        return None


def _filtrar_medios(publicar: Path, publicacion: Publicacion) -> None:
    for pieza in publicacion.piezas.values():
        if pieza.video is not None and _resolver_medio(publicar, pieza.video) is None:
            pieza.video = None
        pieza.portadas = [
            portada
            for portada in pieza.portadas
            if _resolver_medio(publicar, portada) is not None
        ]
        for textos in pieza.redes.values():
            if (
                textos.video is not None
                and _resolver_medio(publicar, textos.video) is None
            ):
                textos.video = None


def leer_publicacion(config: Config, carpeta: Path | None) -> LecturaPublicacion:
    if carpeta is None:
        return LecturaPublicacion()

    publicar = _raiz_publicar(config, carpeta)
    if publicar is None:
        return LecturaPublicacion()
    try:
        ruta = ruta_segura(publicar, "publicacion.json")
    except ValueError:
        return LecturaPublicacion(publicacion=None, error=ERROR_LECTURA)
    if not ruta.is_file():
        return LecturaPublicacion()

    datos = _leer_json(ruta)
    if datos is None:
        return LecturaPublicacion(publicacion=None, error=ERROR_LECTURA)
    try:
        publicacion = Publicacion.model_validate(datos)
    except RecursionError, ValidationError, ValueError:
        return LecturaPublicacion(publicacion=None, error=ERROR_LECTURA)
    if not _texto_codificable_en_utf8(publicacion.model_dump(mode="json")):
        return LecturaPublicacion(publicacion=None, error=ERROR_LECTURA)

    _filtrar_medios(publicar, publicacion)
    return LecturaPublicacion(publicacion=publicacion, error=None)
