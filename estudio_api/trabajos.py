import codecs
import json
import logging
import os
import re
import sqlite3
import subprocess
import threading
from contextlib import closing
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Literal

from pydantic import BaseModel

from estudio_api.decisiones import abrir_bd

logger = logging.getLogger(__name__)

_BLOQUEO = threading.Lock()
_HILOS: dict[int, threading.Thread] = {}
_PROGRESO = re.compile(r"(\d+)/(\d+)")


class Trabajo(BaseModel):
    id: int
    accion: str
    curso: str | None
    numero: int | None
    estado: Literal["en_marcha", "hecho", "error", "interrumpido"]
    progreso: float
    inicio: datetime
    fin: datetime | None
    error: str | None
    registro: list[str]


class TrabajoEnMarcha(Exception):
    pass


def _ahora() -> str:
    return datetime.now().astimezone().isoformat()


def _desde_fila(fila: sqlite3.Row | tuple) -> Trabajo:
    return Trabajo(
        id=fila[0],
        accion=fila[1],
        curso=fila[2],
        numero=fila[3],
        estado=fila[4],
        progreso=fila[5],
        inicio=fila[6],
        fin=fila[7],
        error=fila[8],
        registro=json.loads(fila[9]),
    )


def leer_trabajo(bd: sqlite3.Connection, id: int) -> Trabajo | None:
    fila = bd.execute(
        """
        SELECT id, accion, curso, numero, estado, progreso,
               inicio, fin, error, registro
        FROM trabajo
        WHERE id = ?
        """,
        (id,),
    ).fetchone()
    return _desde_fila(fila) if fila is not None else None


def ultimo_trabajo(
    bd: sqlite3.Connection,
    accion: str,
    curso: str | None,
    numero: int | None,
) -> Trabajo | None:
    fila = bd.execute(
        """
        SELECT id, accion, curso, numero, estado, progreso,
               inicio, fin, error, registro
        FROM trabajo
        WHERE accion = ? AND curso IS ? AND numero IS ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (accion, curso, numero),
    ).fetchone()
    return _desde_fila(fila) if fila is not None else None


def _guardar_avance(
    bd_ruta: Path, trabajo_id: int, progreso: float, registro: list[str]
) -> None:
    with closing(abrir_bd(bd_ruta)) as bd, bd:
        bd.execute(
            "UPDATE trabajo SET progreso = ?, registro = ? WHERE id = ?",
            (progreso, json.dumps(registro, ensure_ascii=False), trabajo_id),
        )


def _finalizar(
    bd_ruta: Path,
    trabajo_id: int,
    estado: Literal["hecho", "error"],
    progreso: float,
    registro: list[str],
    error: str | None,
) -> None:
    with closing(abrir_bd(bd_ruta)) as bd, bd:
        bd.execute(
            """
            UPDATE trabajo
            SET estado = ?, progreso = ?, fin = ?, error = ?, registro = ?
            WHERE id = ? AND estado = 'en_marcha'
            """,
            (
                estado,
                progreso,
                _ahora(),
                error,
                json.dumps(registro, ensure_ascii=False),
                trabajo_id,
            ),
        )


def _finalizar_con_reintento(
    bd_ruta: Path,
    trabajo_id: int,
    estado: Literal["hecho", "error"],
    progreso: float,
    registro: list[str],
    error: str | None,
) -> bool:
    for intento in range(2):
        try:
            _finalizar(
                bd_ruta,
                trabajo_id,
                estado,
                progreso,
                registro,
                error,
            )
            return True
        except Exception:
            if intento == 0:
                logger.warning(
                    "No se pudo finalizar el trabajo %s; se reintentará",
                    trabajo_id,
                    exc_info=True,
                )
            else:
                logger.exception(
                    "No se pudo finalizar el trabajo %s tras reintentarlo",
                    trabajo_id,
                )
    return False


def _borrar_temporal(temporal: Path | None) -> None:
    if temporal is not None:
        temporal.unlink(missing_ok=True)


def _incorporar_linea(
    linea: str,
    registro: list[str],
    progreso: float,
    *,
    reescribir: bool = False,
) -> float:
    if not linea:
        return progreso
    if reescribir and registro:
        registro[-1] = linea[:500]
    else:
        registro.append(linea[:500])
    del registro[:-40]
    for coincidencia in _PROGRESO.finditer(linea):
        actual = int(coincidencia.group(1))
        total = int(coincidencia.group(2))
        if total > 0:
            progreso = min(1.0, max(0.0, actual / total))
    return progreso


def _ejecutar(
    bd_ruta: Path,
    trabajo_id: int,
    comando: list[str],
    cwd: Path,
    temporal: Path | None,
    destino: Path | None,
) -> None:
    registro: list[str] = []
    progreso = 0.0
    proceso: subprocess.Popen[bytes] | None = None
    try:
        try:
            proceso = subprocess.Popen(
                comando,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                shell=False,
            )
        except OSError as exc:
            _borrar_temporal(temporal)
            _finalizar_con_reintento(
                bd_ruta,
                trabajo_id,
                "error",
                progreso,
                registro,
                f"No se pudo iniciar el trabajo: {exc}",
            )
            return

        assert proceso.stdout is not None
        pendiente = ""
        reescribir_pendiente = False
        ultima_escritura = monotonic()
        decodificador = codecs.getincrementaldecoder("utf-8")(errors="replace")

        def incorporar_texto(texto: str) -> None:
            nonlocal pendiente, progreso, reescribir_pendiente
            for caracter in texto:
                if caracter == "\r":
                    tenia_pendiente = bool(pendiente)
                    progreso = _incorporar_linea(
                        pendiente,
                        registro,
                        progreso,
                        reescribir=reescribir_pendiente,
                    )
                    pendiente = ""
                    reescribir_pendiente = reescribir_pendiente or tenia_pendiente
                elif caracter == "\n":
                    progreso = _incorporar_linea(
                        pendiente,
                        registro,
                        progreso,
                        reescribir=reescribir_pendiente,
                    )
                    pendiente = ""
                    reescribir_pendiente = False
                elif len(pendiente) < 500:
                    pendiente += caracter

        try:
            while trozo := proceso.stdout.read1(4096):
                incorporar_texto(decodificador.decode(trozo))
                ahora = monotonic()
                if ahora - ultima_escritura >= 1:
                    try:
                        _guardar_avance(bd_ruta, trabajo_id, progreso, registro)
                    except Exception:  # noqa: BLE001 -- el avance no debe abortar el render
                        logger.warning(
                            "No se pudo guardar el avance del trabajo %s",
                            trabajo_id,
                        )
                    else:
                        ultima_escritura = ahora
            incorporar_texto(decodificador.decode(b"", final=True))
        finally:
            proceso.stdout.close()

        if pendiente:
            progreso = _incorporar_linea(
                pendiente,
                registro,
                progreso,
                reescribir=reescribir_pendiente,
            )
        codigo = proceso.wait()
        if codigo != 0:
            _borrar_temporal(temporal)
            _finalizar_con_reintento(
                bd_ruta,
                trabajo_id,
                "error",
                progreso,
                registro,
                f"Remotion terminó con el código {codigo}",
            )
            return

        if temporal is not None and destino is not None:
            os.replace(temporal, destino)
        _finalizar_con_reintento(
            bd_ruta,
            trabajo_id,
            "hecho",
            progreso,
            registro,
            None,
        )
    except Exception as exc:
        if proceso is not None and proceso.poll() is None:
            proceso.kill()
            proceso.wait()
        try:
            _borrar_temporal(temporal)
        except OSError:
            logger.exception("No se pudo borrar el temporal del trabajo %s", trabajo_id)
        logger.exception("Fallo inesperado en el trabajo %s", trabajo_id)
        _finalizar_con_reintento(
            bd_ruta,
            trabajo_id,
            "error",
            progreso,
            registro,
            f"No se pudo completar el trabajo: {exc}",
        )


def _ejecutar_y_olvidar(
    bd_ruta: Path,
    trabajo_id: int,
    comando: list[str],
    cwd: Path,
    temporal: Path | None,
    destino: Path | None,
) -> None:
    try:
        _ejecutar(
            bd_ruta,
            trabajo_id,
            comando,
            cwd,
            temporal,
            destino,
        )
    finally:
        with _BLOQUEO:
            _HILOS.pop(trabajo_id, None)


def lanzar(
    bd_ruta: Path,
    accion: str,
    curso: str | None,
    numero: int | None,
    comando: list[str],
    cwd: Path,
    temporal: Path | None,
    destino: Path | None,
) -> Trabajo:
    with _BLOQUEO, closing(abrir_bd(bd_ruta)) as bd:
        aislamiento_anterior = bd.isolation_level
        bd.isolation_level = None
        try:
            bd.execute("BEGIN IMMEDIATE")
            en_marcha = bd.execute(
                "SELECT id FROM trabajo WHERE estado = 'en_marcha'"
            ).fetchall()
            if any(
                (hilo := _HILOS.get(fila[0])) is not None and hilo.is_alive()
                for fila in en_marcha
            ):
                raise TrabajoEnMarcha
            if en_marcha:
                bd.executemany(
                    """
                    UPDATE trabajo
                    SET estado = 'interrumpido', fin = ?
                    WHERE id = ? AND estado = 'en_marcha'
                    """,
                    [(_ahora(), fila[0]) for fila in en_marcha],
                )
            cursor = bd.execute(
                """
                INSERT INTO trabajo
                    (accion, curso, numero, estado, inicio, temporal)
                VALUES (?, ?, ?, 'en_marcha', ?, ?)
                """,
                (
                    accion,
                    curso,
                    numero,
                    _ahora(),
                    str(temporal) if temporal is not None else None,
                ),
            )
            trabajo_id = cursor.lastrowid
            assert trabajo_id is not None
            bd.execute("COMMIT")
        except Exception:
            if bd.in_transaction:
                bd.execute("ROLLBACK")
            raise
        finally:
            bd.isolation_level = aislamiento_anterior

        trabajo = leer_trabajo(bd, trabajo_id)
        assert trabajo is not None
        hilo = threading.Thread(
            target=_ejecutar_y_olvidar,
            args=(
                bd_ruta,
                trabajo_id,
                list(comando),
                cwd,
                temporal,
                destino,
            ),
            daemon=True,
            name=f"trabajo-{trabajo_id}",
        )
        _HILOS[trabajo_id] = hilo
        try:
            hilo.start()
        except Exception as error:  # noqa: BLE001 -- cualquier fallo de start se persiste
            _HILOS.pop(trabajo_id, None)
            try:
                _borrar_temporal(temporal)
            except OSError:
                logger.exception(
                    "No se pudo borrar el temporal del trabajo %s",
                    trabajo_id,
                )
            _finalizar_con_reintento(
                bd_ruta,
                trabajo_id,
                "error",
                0.0,
                [],
                f"No se pudo iniciar el hilo del trabajo: {error}",
            )
            fallido = leer_trabajo(bd, trabajo_id)
            assert fallido is not None
            return fallido
        return trabajo


def interrumpir_huerfanos(bd: sqlite3.Connection) -> int:
    filas = bd.execute(
        "SELECT id, temporal FROM trabajo WHERE estado = 'en_marcha'"
    ).fetchall()
    if not filas:
        return 0

    ids = [fila[0] for fila in filas]
    with bd:
        bd.executemany(
            """
            UPDATE trabajo
            SET estado = 'interrumpido', fin = ?
            WHERE id = ? AND estado = 'en_marcha'
            """,
            [(_ahora(), trabajo_id) for trabajo_id in ids],
        )
    for trabajo_id, temporal in filas:
        if temporal is None:
            continue
        try:
            Path(temporal).unlink(missing_ok=True)
        except OSError:
            logger.exception(
                "No se pudo borrar el temporal del trabajo interrumpido %s",
                trabajo_id,
            )
    return len(filas)


def esperar(id: int, timeout: float) -> None:
    with _BLOQUEO:
        hilo = _HILOS.get(id)
    if hilo is not None:
        hilo.join(timeout)
