import json
import logging
import os
import re
import sqlite3
import subprocess
import threading
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from estudio_api.decisiones import abrir_bd

logger = logging.getLogger(__name__)

_BLOQUEO = threading.Lock()
_HILOS: dict[int, threading.Thread] = {}
_PROGRESO = re.compile(r"(\d+)/(\d+)")
_SEPARADOR_LINEAS = re.compile(r"[\r\n]+")


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
            WHERE id = ?
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


def _borrar_temporal(temporal: Path | None) -> None:
    if temporal is not None:
        temporal.unlink(missing_ok=True)


def _incorporar_linea(linea: str, registro: list[str], progreso: float) -> float:
    if not linea:
        return progreso
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
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                shell=False,
            )
        except OSError as exc:
            _borrar_temporal(temporal)
            _finalizar(
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
        ultima_escritura = time.monotonic()
        while trozo := proceso.stdout.read1(4096):
            pendiente += trozo.decode("utf-8", errors="replace")
            partes = _SEPARADOR_LINEAS.split(pendiente)
            pendiente = partes.pop()
            for linea in partes:
                progreso = _incorporar_linea(linea, registro, progreso)
            ahora = time.monotonic()
            if ahora - ultima_escritura >= 1:
                _guardar_avance(bd_ruta, trabajo_id, progreso, registro)
                ultima_escritura = ahora

        if pendiente:
            progreso = _incorporar_linea(pendiente, registro, progreso)
        codigo = proceso.wait()
        if codigo != 0:
            _borrar_temporal(temporal)
            _finalizar(
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
        _finalizar(bd_ruta, trabajo_id, "hecho", progreso, registro, None)
    except Exception as exc:
        if proceso is not None and proceso.poll() is None:
            proceso.kill()
            proceso.wait()
        try:
            _borrar_temporal(temporal)
        except OSError:
            logger.exception("No se pudo borrar el temporal del trabajo %s", trabajo_id)
        logger.exception("Fallo inesperado en el trabajo %s", trabajo_id)
        _finalizar(
            bd_ruta,
            trabajo_id,
            "error",
            progreso,
            registro,
            f"No se pudo completar el trabajo: {exc}",
        )


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
            if bd.execute(
                "SELECT 1 FROM trabajo WHERE estado = 'en_marcha' LIMIT 1"
            ).fetchone():
                raise TrabajoEnMarcha
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
            target=_ejecutar,
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
        hilo.start()
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
