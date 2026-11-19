import os
import re
import stat
from pathlib import Path, PurePosixPath
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


class _CamposTextosRed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    titulos: list[str] = Field(default_factory=list)
    descripcion: str | None = None
    etiquetas: list[str] = Field(default_factory=list)
    texto: str | None = None
    comentario_fijado: str | None = None
    ajustes: list[str] = Field(default_factory=list)
    notas: str | None = None


class TextosRed(_CamposTextosRed):
    video: str | None = None


class TextosRedEditables(_CamposTextosRed):
    pass


class PiezaPublicacion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    titulo: str | None = None
    video: str | None = None
    duracion: str | None = None
    portadas: list[str] = Field(default_factory=list)
    fecha_propuesta: str | None = None
    redes: dict[Red, TextosRed] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validar_campos_de_una_linea(self) -> Self:
        _validar_cadena_sin_saltos("titulo", self.titulo)
        _validar_cadena_sin_saltos("fecha_propuesta", self.fecha_propuesta)
        return self


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
        _validar_sin_saltos("despues_de_publicar", self.despues_de_publicar)
        _validar_maximo("notas", self.notas, 2000)
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


def _validar_sin_saltos(campo: str, lineas: list[str]) -> None:
    if any("\n" in linea or "\r" in linea for linea in lineas):
        raise ValueError(f"El campo {campo} no admite saltos de línea")


def _validar_cadena_sin_saltos(campo: str, valor: str | None) -> None:
    if valor is not None:
        _validar_sin_saltos(campo, [valor])


def validar_textos(red: Red, textos: _CamposTextosRed) -> None:
    if not _texto_codificable_en_utf8(textos.model_dump(mode="json")):
        raise ValueError("Los textos deben poder codificarse en UTF-8")

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
    _validar_maximo("notas", textos.notas, 2000)
    _validar_sin_saltos("titulos", textos.titulos)
    _validar_sin_saltos("ajustes", textos.ajustes)
    _validar_lineas("ajustes", textos.ajustes)


def _raiz_publicar(config: Config, carpeta: Path) -> Path | None:
    try:
        carpeta_resuelta = carpeta.resolve()
        relativa = carpeta_resuelta.relative_to(config.cursos_dir.resolve())
        esperada = carpeta_resuelta / "publicar"
        try:
            datos = os.lstat(esperada)
        except FileNotFoundError:
            datos = None
        if datos is not None and stat.S_ISLNK(datos.st_mode):
            return None
        publicar = ruta_segura(config.cursos_dir, *relativa.parts, "publicar")
        if publicar != esperada:
            return None
        return publicar
    except OSError, ValueError:
        return None


def ruta_escritura_segura(publicar: Path, nombre: str) -> Path | None:
    literal = publicar / nombre
    try:
        try:
            datos = os.lstat(literal)
        except FileNotFoundError:
            datos = None
        if datos is not None and stat.S_ISLNK(datos.st_mode):
            return None
        segura = ruta_segura(publicar, nombre)
    except OSError, ValueError:
        return None
    return literal if segura == literal else None


def clave_pieza(identificador: str) -> tuple[int, int]:
    if identificador == "leccion":
        return (0, 0)
    if identificador == "reel-salida":
        return (1, 0)
    if coincidencia := re.fullmatch(r"reel-salida-([1-9][0-9]*)", identificador):
        return (1, int(coincidencia.group(1)))
    coincidencia = re.fullmatch(r"short-([1-9][0-9]*)", identificador)
    assert coincidencia is not None
    return (2, int(coincidencia.group(1)))


def textos_red_vacios(textos: TextosRed) -> bool:
    return not textos.model_dump(exclude_none=True, exclude_defaults=True)


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


def portadas_candidatas(
    config: Config,
    carpeta: Path | None,
    portadas_disco: list[str],
    pieza: PiezaPublicacion | None,
) -> list[str]:
    portadas_json: list[str] = []
    if carpeta is not None and pieza is not None:
        portadas_json = [
            publica
            for portada in pieza.portadas
            if (publica := ruta_publica_publicar(config, carpeta, portada)) is not None
        ]
    return list(dict.fromkeys(portadas_json + portadas_disco))


def ruta_relativa_publicar(
    config: Config,
    carpeta: Path,
    publica: str,
) -> str | None:
    publicar = _raiz_publicar(config, carpeta)
    if publicar is None:
        return None
    try:
        prefijo = PurePosixPath(
            "cursos",
            *publicar.relative_to(config.cursos_dir.resolve()).parts,
        )
        ruta_publica = PurePosixPath(publica)
        partes = ruta_publica.relative_to(prefijo).parts
    except ValueError:
        return None
    relativa = PurePosixPath(*partes).as_posix()
    if _resolver_medio(publicar, relativa) is None:
        return None
    return relativa


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


def leer_publicacion(  # noqa: PLR0911
    config: Config,
    carpeta: Path | None,
    *,
    filtrar: bool = True,
) -> LecturaPublicacion:
    if carpeta is None:
        return LecturaPublicacion()

    publicar = _raiz_publicar(config, carpeta)
    if publicar is None:
        return LecturaPublicacion(publicacion=None, error=ERROR_LECTURA)
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

    if filtrar:
        _filtrar_medios(publicar, publicacion)
    return LecturaPublicacion(publicacion=publicacion, error=None)
