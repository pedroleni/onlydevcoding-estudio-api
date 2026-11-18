import json
import os
import re
import secrets
import stat
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from estudio_api.config import Config
from estudio_api.lectura import MAX_TAMANO_JSON, carpeta_de_trabajo, datos_curso
from estudio_api.rutas import ruta_segura

PATRON_ARCHIVO_ENTREGA = re.compile(
    r"^[A-Za-z0-9_(][A-Za-z0-9 _().-]{0,115}\.(?i:mov|mp4)$"
)
TAMANO_MAXIMO_ENTREGA = 4_294_967_296
EXTENSIONES_ANALISIS = ("json", "wav", "origen")

_BLOQUEO_INSTALACION = threading.Lock()
_SUBIDAS_EN_CURSO: set[tuple[Path, str]] = set()
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_SIN_DATOS = object()


class ArchivoEntregado(BaseModel):
    archivo: str
    bytes: int


class LeccionNoExiste(Exception):
    pass


class NombreEntregaInvalido(Exception):
    pass


class EntregaInvalida(ValueError):
    pass


class EntregaExistente(Exception):
    pass


@dataclass(frozen=True)
class _DirectoriosEntrega:
    grabaciones: Path
    entregas: Path
    creados: tuple[Path, ...]


@dataclass(frozen=True)
class _TemporalEntrega:
    descriptor: int
    descriptor_directorio: int
    nombre: str


def _lstat_o_none(ruta: Path) -> os.stat_result | None:
    try:
        return os.lstat(ruta)
    except FileNotFoundError:
        return None


def _ruta_literal_segura(raiz: Path, *partes: str) -> Path:
    literal = raiz.resolve().joinpath(*partes)
    segura = ruta_segura(raiz, *partes)
    if segura != literal:
        raise OSError("La ruta de entregas no puede contener enlaces simbólicos")
    return literal


def _exigir_directorio_real(ruta: Path) -> None:
    datos = os.lstat(ruta)
    if not stat.S_ISDIR(datos.st_mode):
        raise OSError("La ruta de entregas no es un directorio real")


def _crear_directorio_real(ruta: Path) -> bool:
    try:
        ruta.mkdir()
        creado = True
    except FileExistsError:
        creado = False
    _exigir_directorio_real(ruta)
    return creado


def _borrar_directorios_vacios_sin_bloqueo(
    directorios: tuple[Path, ...],
) -> None:
    for directorio in reversed(directorios):
        if any(carpeta == directorio for carpeta, _ in _SUBIDAS_EN_CURSO):
            continue
        try:
            directorio.rmdir()
        except OSError:
            pass


def _borrar_directorios_vacios(directorios: tuple[Path, ...]) -> None:
    with _BLOQUEO_INSTALACION:
        _borrar_directorios_vacios_sin_bloqueo(directorios)


def _finalizar_subida(
    clave: tuple[Path, str] | None,
    directorios: tuple[Path, ...],
) -> None:
    with _BLOQUEO_INSTALACION:
        if clave is not None:
            _SUBIDAS_EN_CURSO.discard(clave)
        _borrar_directorios_vacios_sin_bloqueo(directorios)


def _carpeta_leccion(
    config: Config,
    curso: str,
    numero: int,
    *,
    datos: Any = _SIN_DATOS,
) -> Path | None:
    leido = datos_curso(config, curso) if datos is _SIN_DATOS else datos
    carpeta = carpeta_de_trabajo(leido, numero)
    if carpeta is None:
        return None
    try:
        relativa = carpeta.resolve().relative_to(config.cursos_dir.resolve())
        return _ruta_literal_segura(config.cursos_dir, *relativa.parts)
    except OSError, ValueError:
        return None


def carpeta_entregas(
    config: Config,
    curso: str,
    numero: int,
    *,
    datos: Any = _SIN_DATOS,
) -> Path | None:
    """Devuelve la ruta literal o ``None`` si la lección no existe.

    Puede lanzar ``OSError`` si algún componente es un enlace simbólico.
    """
    carpeta = _carpeta_leccion(config, curso, numero, datos=datos)
    if carpeta is None:
        return None
    grabaciones = _ruta_literal_segura(carpeta, "grabaciones")
    entregas = _ruta_literal_segura(grabaciones, "entregas")
    for directorio in (carpeta, grabaciones, entregas):
        datos = _lstat_o_none(directorio)
        if datos is not None and not stat.S_ISDIR(datos.st_mode):
            raise OSError("La ruta de entregas no es un directorio real")
    return entregas


def _preparar_directorios(
    config: Config,
    curso: str,
    numero: int,
) -> _DirectoriosEntrega:
    carpeta = _carpeta_leccion(config, curso, numero)
    if carpeta is None:
        raise LeccionNoExiste
    creados: list[Path] = []
    try:
        if _crear_directorio_real(carpeta):
            creados.append(carpeta)
        grabaciones = _ruta_literal_segura(carpeta, "grabaciones")
        if _crear_directorio_real(grabaciones):
            creados.append(grabaciones)
        entregas = _ruta_literal_segura(grabaciones, "entregas")
        if _crear_directorio_real(entregas):
            creados.append(entregas)
        return _DirectoriosEntrega(grabaciones, entregas, tuple(creados))
    except BaseException:
        _borrar_directorios_vacios(tuple(creados))
        raise


def _existe_nombre_en_videos(grabaciones: Path, archivo: str) -> bool:
    videos = _ruta_literal_segura(grabaciones, "videos")
    datos = _lstat_o_none(videos)
    if datos is None:
        return False
    if not stat.S_ISDIR(datos.st_mode):
        raise OSError("La carpeta de vídeos no es un directorio real")
    descriptor = os.open(videos, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW)
    try:
        with os.scandir(descriptor) as entradas:
            return any(entrada.name == archivo for entrada in entradas)
    finally:
        os.close(descriptor)


def _abrir_temporal(
    directorios: _DirectoriosEntrega,
    archivo: str,
) -> _TemporalEntrega:
    nombre_temporal = f".{archivo}.subiendo"
    clave = (directorios.entregas, archivo)
    with _BLOQUEO_INSTALACION:
        if _existe_nombre_en_videos(directorios.grabaciones, archivo):
            raise EntregaExistente
        descriptor_directorio = os.open(
            directorios.entregas,
            os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW,
        )
        try:
            try:
                os.stat(archivo, dir_fd=descriptor_directorio, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise EntregaExistente

            try:
                descriptor = os.open(
                    nombre_temporal,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW,
                    0o600,
                    dir_fd=descriptor_directorio,
                )
            except FileExistsError as error:
                datos = os.stat(
                    nombre_temporal,
                    dir_fd=descriptor_directorio,
                    follow_symlinks=False,
                )
                if stat.S_ISREG(datos.st_mode):
                    if clave in _SUBIDAS_EN_CURSO:
                        raise EntregaExistente from error
                    try:
                        os.unlink(
                            nombre_temporal,
                            dir_fd=descriptor_directorio,
                        )
                    except FileNotFoundError:
                        pass
                    try:
                        descriptor = os.open(
                            nombre_temporal,
                            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW,
                            0o600,
                            dir_fd=descriptor_directorio,
                        )
                    except FileExistsError as segundo_error:
                        raise EntregaExistente from segundo_error
                else:
                    raise OSError(
                        "El temporal de entrega no es un archivo regular"
                    ) from error
            _SUBIDAS_EN_CURSO.add(clave)
        except BaseException:
            os.close(descriptor_directorio)
            raise
    return _TemporalEntrega(descriptor, descriptor_directorio, nombre_temporal)


def _escribir_trozo(descriptor: int, trozo: bytes) -> None:
    pendiente = memoryview(trozo)
    while pendiente:
        escritos = os.write(descriptor, pendiente)
        if escritos <= 0:
            raise OSError("No se ha podido escribir la entrega")
        pendiente = pendiente[escritos:]


def _sincronizar_y_cerrar(descriptor: int) -> None:
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _cerrar_y_borrar_temporal(
    temporal: _TemporalEntrega,
    descriptor_abierto: bool,
) -> None:
    if descriptor_abierto:
        try:
            os.close(temporal.descriptor)
        except OSError:
            pass
    try:
        os.unlink(temporal.nombre, dir_fd=temporal.descriptor_directorio)
    except FileNotFoundError:
        pass


def _limpiar_temporal_completo(temporal: _TemporalEntrega) -> None:
    try:
        _cerrar_y_borrar_temporal(temporal, False)
    finally:
        os.close(temporal.descriptor_directorio)


def _instalar_temporal(
    temporal: _TemporalEntrega,
    directorios: _DirectoriosEntrega,
    archivo: str,
) -> None:
    with _BLOQUEO_INSTALACION:
        if _existe_nombre_en_videos(directorios.grabaciones, archivo):
            raise EntregaExistente
        instalada = False
        try:
            os.link(
                temporal.nombre,
                archivo,
                src_dir_fd=temporal.descriptor_directorio,
                dst_dir_fd=temporal.descriptor_directorio,
                follow_symlinks=False,
            )
            instalada = True
        except FileExistsError as error:
            raise EntregaExistente from error
        try:
            os.unlink(temporal.nombre, dir_fd=temporal.descriptor_directorio)
            os.fsync(temporal.descriptor_directorio)
        except BaseException:
            if instalada:
                try:
                    os.unlink(archivo, dir_fd=temporal.descriptor_directorio)
                except OSError:
                    pass
            raise
    os.close(temporal.descriptor_directorio)


async def _recibir_entrega(
    temporal: _TemporalEntrega,
    trozos: AsyncIterator[bytes],
    longitud: int,
) -> int:
    total = 0
    cabecera = bytearray()
    descriptor_abierto = True
    try:
        async for trozo in trozos:
            if not isinstance(trozo, bytes):
                raise EntregaInvalida
            total += len(trozo)
            if total > longitud or total > TAMANO_MAXIMO_ENTREGA:
                raise EntregaInvalida
            if len(cabecera) < 8:
                cabecera.extend(trozo[: 8 - len(cabecera)])
                if len(cabecera) == 8 and cabecera[4:8] != b"ftyp":
                    raise EntregaInvalida
            await run_in_threadpool(_escribir_trozo, temporal.descriptor, trozo)
        try:
            await run_in_threadpool(_sincronizar_y_cerrar, temporal.descriptor)
        finally:
            descriptor_abierto = False
        if total != longitud or len(cabecera) < 8:
            raise EntregaInvalida
        return total
    except BaseException:
        await run_in_threadpool(
            _cerrar_y_borrar_temporal,
            temporal,
            descriptor_abierto,
        )
        raise


async def guardar_entrega(
    config: Config,
    curso: str,
    numero: int,
    archivo: str,
    trozos: AsyncIterator[bytes],
    longitud: int,
) -> ArchivoEntregado:
    if PATRON_ARCHIVO_ENTREGA.fullmatch(archivo) is None:
        raise NombreEntregaInvalido
    if not 0 <= longitud <= TAMANO_MAXIMO_ENTREGA:
        raise EntregaInvalida
    directorios = await run_in_threadpool(
        _preparar_directorios,
        config,
        curso,
        numero,
    )
    temporal: _TemporalEntrega | None = None
    clave_subida: tuple[Path, str] | None = None
    limpiar_directorios = True
    try:
        temporal = await run_in_threadpool(_abrir_temporal, directorios, archivo)
        clave_subida = (directorios.entregas, archivo)
        total = await _recibir_entrega(temporal, trozos, longitud)
        await run_in_threadpool(
            _instalar_temporal,
            temporal,
            directorios,
            archivo,
        )
        temporal = None
        limpiar_directorios = False
        return ArchivoEntregado(archivo=archivo, bytes=total)
    except BaseException:
        if temporal is not None:
            # ``_recibir_entrega`` ya lo limpia si empezó a consumir el cuerpo;
            # aquí cubrimos fallos posteriores y mantenemos la operación idempotente.
            try:
                await run_in_threadpool(_limpiar_temporal_completo, temporal)
            except OSError:
                pass
        raise
    finally:
        await run_in_threadpool(
            _finalizar_subida,
            clave_subida,
            directorios.creados if limpiar_directorios else (),
        )


def listar_entregas(
    config: Config,
    curso: str,
    numero: int,
    *,
    datos: Any = _SIN_DATOS,
) -> list[ArchivoEntregado] | None:
    carpeta = carpeta_entregas(config, curso, numero, datos=datos)
    if carpeta is None:
        return None
    if not carpeta.exists():
        return []
    _exigir_directorio_real(carpeta)
    archivos: list[ArchivoEntregado] = []
    with os.scandir(carpeta) as entradas:
        for entrada in entradas:
            if PATRON_ARCHIVO_ENTREGA.fullmatch(entrada.name) is None:
                continue
            try:
                datos = entrada.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            if stat.S_ISREG(datos.st_mode):
                archivos.append(
                    ArchivoEntregado(archivo=entrada.name, bytes=datos.st_size)
                )
    return sorted(archivos, key=lambda entrega: entrega.archivo)


def _leer_propuesta_cruda(descriptor_carpeta: int) -> dict[str, Any] | None:
    """``propuesta.json`` tal cual, o ``None`` si no hay o no se entiende.

    Lanza ``OSError`` si es un enlace simbólico.
    """
    try:
        descriptor = os.open(
            "propuesta.json",
            os.O_RDONLY | _O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0),
            dir_fd=descriptor_carpeta,
        )
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, "rb") as entrada:
        datos_archivo = os.fstat(entrada.fileno())
        if (
            not stat.S_ISREG(datos_archivo.st_mode)
            or datos_archivo.st_size > MAX_TAMANO_JSON
        ):
            return None
        contenido = entrada.read(MAX_TAMANO_JSON + 1)
    if len(contenido) > MAX_TAMANO_JSON:
        return None
    try:
        datos = json.loads(contenido.decode("utf-8"))
    except UnicodeError, RecursionError, ValueError:
        return None
    if not isinstance(datos, dict) or not isinstance(datos.get("archivos"), list):
        return None
    return datos


def _escribir_propuesta_cruda(descriptor_carpeta: int, datos: dict[str, Any]) -> None:
    temporal = f".propuesta.{secrets.token_hex(8)}.tmp"
    descriptor = os.open(
        temporal,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW,
        0o600,
        dir_fd=descriptor_carpeta,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as salida:
            json.dump(datos, salida, ensure_ascii=False, indent=2)
            salida.write("\n")
            salida.flush()
            os.fsync(salida.fileno())
        os.replace(
            temporal,
            "propuesta.json",
            src_dir_fd=descriptor_carpeta,
            dst_dir_fd=descriptor_carpeta,
        )
    except BaseException:
        try:
            os.unlink(temporal, dir_fd=descriptor_carpeta)
        except FileNotFoundError:
            pass
        raise


def _quitar_de_propuesta(descriptor_carpeta: int, archivo: str) -> None:
    """Quita de ``propuesta.json`` la entrada de ``archivo``; si no queda nada, la borra."""
    datos = _leer_propuesta_cruda(descriptor_carpeta)
    if datos is None:
        return
    restantes = [
        toma
        for toma in datos["archivos"]
        if not (isinstance(toma, dict) and toma.get("archivo") == archivo)
    ]
    if len(restantes) == len(datos["archivos"]):
        return
    if not restantes:
        os.unlink("propuesta.json", dir_fd=descriptor_carpeta)
        return
    _escribir_propuesta_cruda(descriptor_carpeta, {**datos, "archivos": restantes})


def borrar_entrega(config: Config, curso: str, numero: int, archivo: str) -> bool:
    if PATRON_ARCHIVO_ENTREGA.fullmatch(archivo) is None:
        raise NombreEntregaInvalido
    carpeta = carpeta_entregas(config, curso, numero)
    if carpeta is None or not carpeta.exists():
        return False
    _exigir_directorio_real(carpeta)
    descriptor = os.open(carpeta, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW)
    try:
        nombre_real: str | None = None
        with os.scandir(descriptor) as entradas:
            for entrada in entradas:
                if entrada.name != archivo:
                    continue
                datos = entrada.stat(follow_symlinks=False)
                if stat.S_ISREG(datos.st_mode):
                    nombre_real = entrada.name
                break
        if nombre_real is None:
            return False

        analisis = _ruta_literal_segura(carpeta, ".analisis")
        datos_analisis = _lstat_o_none(analisis)
        if datos_analisis is not None and not stat.S_ISDIR(datos_analisis.st_mode):
            raise OSError("La carpeta de análisis no es un directorio real")

        # Primero la propuesta: si falla, no se ha borrado nada.
        _quitar_de_propuesta(descriptor, nombre_real)

        if datos_analisis is not None:
            descriptor_analisis = os.open(
                analisis,
                os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW,
            )
            try:
                # Solo los tres nombres exactos: ``a.mov`` no toca ``a.mov.mov.*``.
                for extension in EXTENSIONES_ANALISIS:
                    nombre = f"{nombre_real}.{extension}"
                    try:
                        datos = os.stat(
                            nombre, dir_fd=descriptor_analisis, follow_symlinks=False
                        )
                    except FileNotFoundError:
                        continue
                    if stat.S_ISREG(datos.st_mode):
                        os.unlink(nombre, dir_fd=descriptor_analisis)
                os.fsync(descriptor_analisis)
            finally:
                os.close(descriptor_analisis)

        os.unlink(nombre_real, dir_fd=descriptor)
        os.fsync(descriptor)
        return True
    finally:
        os.close(descriptor)
