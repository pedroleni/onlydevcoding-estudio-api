import codecs
import json
import logging
import os
import re
import signal
import sqlite3
import subprocess
import threading
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from time import monotonic, sleep
from typing import Literal

from pydantic import BaseModel

from estudio_api.decisiones import abrir_bd

logger = logging.getLogger(__name__)

_BLOQUEO = threading.Lock()
_HILOS: dict[int, threading.Thread] = {}

PROGRESO_REMOTION = re.compile(r"(\d+)/(\d+)")
PROGRESO_HERRAMIENTA = re.compile(r"^PROGRESO (\d+)/(\d+)$")

TIEMPO_MAXIMO_RENDER = 2 * 60 * 60
_GRACIA_TERMINAR = 10
_ESPERA_HILOS_AL_APAGAR = 5
_VARIABLES_ENTORNO = ("PATH", "HOME", "TMPDIR", "LANG", "USER", "NODE_ENV")


@dataclass(frozen=True)
class Mensajes:
    codigo: str
    arranque: str
    guardado: str
    tiempo: str


MENSAJES_REMOTION = Mensajes(
    codigo="Remotion terminó con el código {codigo}",
    arranque="No se pudo arrancar la herramienta",
    guardado="No se pudo guardar el resultado",
    tiempo="El trabajo ha tardado demasiado y se ha cancelado",
)
MENSAJES_HERRAMIENTA = Mensajes(
    codigo="La herramienta terminó con el código {codigo}",
    arranque="No se pudo arrancar la herramienta",
    guardado="No se pudo guardar el resultado",
    tiempo="El trabajo ha tardado demasiado y se ha cancelado",
)
MENSAJES_PREVIA = Mensajes(
    codigo="Remotion terminó con el código {codigo}",
    arranque="No se pudo arrancar el render",
    guardado="No se pudo guardar la vista previa",
    tiempo="La vista previa ha tardado demasiado y se ha cancelado",
)

# Mensajes comunes: el detalle técnico (excepción y rutas) solo va al log.
ERROR_INTERRUMPIDO = "El trabajo se ha interrumpido al cerrar la API"
ERROR_CANCELADO = "Cancelado"
ERROR_SIN_PISAR = "Ya existe una versión con ese número; vuelve a lanzarlo"


@dataclass(frozen=True)
class PlanTrabajo:
    accion: str
    objetivo: str | None
    comando: list[str]
    cwd: Path
    temporal: Path | None = None
    destino: Path | None = None
    instalar: Literal["reemplazar", "sin_pisar", "archivar"] = "reemplazar"
    entorno: Mapping[str, str] = field(default_factory=dict)
    patron_progreso: re.Pattern[str] = PROGRESO_REMOTION
    tiempo_maximo: float = TIEMPO_MAXIMO_RENDER
    mensajes: Mensajes = MENSAJES_REMOTION


@dataclass
class _EnCurso:
    """Render en marcha en este proceso, con lo necesario para pararlo."""

    bd_ruta: Path
    temporal: Path | None
    proceso: subprocess.Popen[bytes] | None = None
    # None mientras corre; después indica cómo acaba. Solo se cambia con el
    # cerrojo para que cancelar, el temporizador y el apagado no compitan.
    motivo: Literal["tiempo", "apagado", "cancelado", "fin"] | None = None
    cerrojo: threading.Lock = field(default_factory=threading.Lock)


_EN_CURSO: dict[int, _EnCurso] = {}


class Trabajo(BaseModel):
    id: int
    accion: str
    curso: str | None
    numero: int | None
    objetivo: str | None
    estado: Literal["en_marcha", "hecho", "error", "interrumpido", "cancelado"]
    progreso: float
    inicio: datetime
    fin: datetime | None
    error: str | None


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
        objetivo=fila[4],
        estado=fila[5],
        progreso=fila[6],
        inicio=fila[7],
        fin=fila[8],
        error=fila[9],
    )


def leer_trabajo(bd: sqlite3.Connection, id: int) -> Trabajo | None:
    fila = bd.execute(
        """
        SELECT id, accion, curso, numero, objetivo, estado, progreso,
               inicio, fin, error
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
    objetivo: str | None = None,
) -> Trabajo | None:
    fila = bd.execute(
        """
        SELECT id, accion, curso, numero, objetivo, estado, progreso,
               inicio, fin, error
        FROM trabajo
        WHERE accion = ? AND curso IS ? AND numero IS ? AND objetivo IS ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (accion, curso, numero, objetivo),
    ).fetchone()
    return _desde_fila(fila) if fila is not None else None


def listar_trabajos(bd: sqlite3.Connection, limite: int) -> list[Trabajo]:
    filas = bd.execute(
        """
        SELECT id, accion, curso, numero, objetivo, estado, progreso,
               inicio, fin, error
        FROM trabajo
        ORDER BY id DESC
        LIMIT ?
        """,
        (limite,),
    ).fetchall()
    return [_desde_fila(fila) for fila in filas]


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
    estado: Literal["hecho", "error", "cancelado"],
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
    estado: Literal["hecho", "error", "cancelado"],
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


def _borrar_temporal_sin_fallar(temporal: Path | None, trabajo_id: int) -> None:
    try:
        _borrar_temporal(temporal)
    except OSError:
        logger.exception("No se pudo borrar el temporal del trabajo %s", trabajo_id)


def _entorno_render() -> dict[str, str]:
    return {
        nombre: os.environ[nombre]
        for nombre in _VARIABLES_ENTORNO
        if nombre in os.environ
    }


def _senal_al_grupo(pgid: int, senal: int) -> bool:
    try:
        os.killpg(pgid, senal)
    except ProcessLookupError:
        return False
    except PermissionError:
        logger.warning("Sin permiso para enviar %s al grupo %s", senal, pgid)
        return False
    return True


def _terminar_grupo(
    proceso: subprocess.Popen[bytes], gracia: float | None = None
) -> None:
    """SIGTERM al grupo del render y, si sigue vivo tras la gracia, SIGKILL.

    Con ``start_new_session`` el pid del proceso es también el id de su grupo,
    así que llega a npx, Node y Chromium aunque el hijo directo ya no exista.
    """
    pgid = proceso.pid
    if not _senal_al_grupo(pgid, signal.SIGTERM):
        return
    limite = monotonic() + (_GRACIA_TERMINAR if gracia is None else gracia)
    while monotonic() < limite:
        proceso.poll()
        if not _senal_al_grupo(pgid, 0):
            return
        sleep(0.05)
    _senal_al_grupo(pgid, signal.SIGKILL)
    proceso.poll()


def _vencer_tiempo(en_curso: _EnCurso, trabajo_id: int) -> None:
    with en_curso.cerrojo:
        if en_curso.motivo is not None or en_curso.proceso is None:
            return
        en_curso.motivo = "tiempo"
        proceso = en_curso.proceso
    logger.warning("El trabajo %s ha superado el tiempo máximo", trabajo_id)
    _terminar_grupo(proceso)


def _incorporar_linea(
    linea: str,
    registro: list[str],
    progreso: float,
    *,
    patron_progreso: re.Pattern[str] = PROGRESO_REMOTION,
    reescribir: bool = False,
) -> float:
    if not linea:
        return progreso
    if reescribir and registro:
        registro[-1] = linea[:500]
    else:
        registro.append(linea[:500])
    del registro[:-40]
    for coincidencia in patron_progreso.finditer(linea.strip()):
        actual = int(coincidencia.group(1))
        total = int(coincidencia.group(2))
        if total > 0:
            progreso = min(1.0, max(0.0, actual / total))
    return progreso


def _marca_archivo() -> str:
    return datetime.now().strftime("%Y%m%dT%H%M%S%f")


def _ruta_archivada(destino: Path) -> Path:
    anteriores = destino.parent / "anteriores"
    anteriores.mkdir(parents=True, exist_ok=True)
    base = f"{destino.stem}-{_marca_archivo()}"
    indice = 1
    while True:
        sufijo = "" if indice == 1 else f"-{indice}"
        candidata = anteriores / f"{base}{sufijo}{destino.suffix}"
        if not candidata.exists():
            return candidata
        indice += 1


def _instalar_resultado(plan: PlanTrabajo, trabajo_id: int) -> None:
    temporal = plan.temporal
    destino = plan.destino
    if temporal is None or destino is None:
        return
    if plan.instalar == "reemplazar":
        os.replace(temporal, destino)
        return
    if plan.instalar == "sin_pisar":
        os.link(temporal, destino)
        _borrar_temporal_sin_fallar(temporal, trabajo_id)
        return

    if not destino.exists():
        os.replace(temporal, destino)
        return
    archivado = _ruta_archivada(destino)
    os.replace(destino, archivado)
    try:
        os.replace(temporal, destino)
    except OSError:
        try:
            os.replace(archivado, destino)
        except OSError:
            logger.critical(
                "No se pudo restaurar el resultado anterior tras fallar la instalación",
                exc_info=True,
            )
        raise


def _ejecutar(bd_ruta: Path, trabajo_id: int, plan: PlanTrabajo) -> None:
    with _BLOQUEO:
        en_curso = _EN_CURSO.get(trabajo_id)
    if en_curso is None:
        en_curso = _EnCurso(bd_ruta=bd_ruta, temporal=plan.temporal)
    registro: list[str] = []
    progreso = 0.0
    proceso: subprocess.Popen[bytes] | None = None
    temporizador: threading.Timer | None = None
    try:
        with en_curso.cerrojo:
            if en_curso.motivo is not None:
                # Cancelar o apagar pudo adelantarse al arranque del proceso.
                motivo_inicial = en_curso.motivo
                _borrar_temporal_sin_fallar(plan.temporal, trabajo_id)
                if motivo_inicial == "cancelado":
                    _finalizar_con_reintento(
                        bd_ruta,
                        trabajo_id,
                        "cancelado",
                        progreso,
                        registro,
                        ERROR_CANCELADO,
                    )
                return
            try:
                proceso = subprocess.Popen(
                    list(plan.comando),
                    cwd=plan.cwd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    shell=False,
                    start_new_session=True,
                    env=_entorno_render() | dict(plan.entorno),
                )
            except OSError:
                en_curso.motivo = "fin"
                logger.exception("No se pudo arrancar el trabajo %s", trabajo_id)
                _borrar_temporal_sin_fallar(plan.temporal, trabajo_id)
                _finalizar_con_reintento(
                    bd_ruta,
                    trabajo_id,
                    "error",
                    progreso,
                    registro,
                    plan.mensajes.arranque,
                )
                return
            en_curso.proceso = proceso

        temporizador = threading.Timer(
            plan.tiempo_maximo,
            _vencer_tiempo,
            args=(en_curso, trabajo_id),
        )
        temporizador.daemon = True
        temporizador.start()

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
                        patron_progreso=plan.patron_progreso,
                        reescribir=reescribir_pendiente,
                    )
                    pendiente = ""
                    reescribir_pendiente = reescribir_pendiente or tenia_pendiente
                elif caracter == "\n":
                    progreso = _incorporar_linea(
                        pendiente,
                        registro,
                        progreso,
                        patron_progreso=plan.patron_progreso,
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
                patron_progreso=plan.patron_progreso,
                reescribir=reescribir_pendiente,
            )
        codigo = proceso.wait()
        temporizador.cancel()
        with en_curso.cerrojo:
            if en_curso.motivo is None:
                en_curso.motivo = "fin"
            motivo = en_curso.motivo

        if motivo == "apagado":
            # El apagado ya ha marcado el trabajo como interrumpido.
            _borrar_temporal_sin_fallar(plan.temporal, trabajo_id)
            return
        if motivo == "tiempo":
            # Se espera a que el grupo muera antes de borrar lo que escribía.
            temporizador.join()
            _borrar_temporal_sin_fallar(plan.temporal, trabajo_id)
            _finalizar_con_reintento(
                bd_ruta,
                trabajo_id,
                "error",
                progreso,
                registro,
                plan.mensajes.tiempo,
            )
            return
        if motivo == "cancelado":
            # El líder puede haber muerto antes que un descendiente que no
            # hereda stdout. No se borra ni se finaliza hasta parar el grupo.
            _terminar_grupo(proceso)
            _borrar_temporal_sin_fallar(plan.temporal, trabajo_id)
            _finalizar_con_reintento(
                bd_ruta,
                trabajo_id,
                "cancelado",
                progreso,
                registro,
                ERROR_CANCELADO,
            )
            return
        if codigo != 0:
            _borrar_temporal(plan.temporal)
            _finalizar_con_reintento(
                bd_ruta,
                trabajo_id,
                "error",
                progreso,
                registro,
                plan.mensajes.codigo.format(codigo=codigo),
            )
            return

        try:
            _instalar_resultado(plan, trabajo_id)
        except OSError as error:
            if plan.instalar == "sin_pisar" and isinstance(error, FileExistsError):
                logger.warning("El destino del trabajo %s ya existe", trabajo_id)
                mensaje = ERROR_SIN_PISAR
            else:
                logger.exception(
                    "No se pudo instalar el resultado del trabajo %s", trabajo_id
                )
                mensaje = plan.mensajes.guardado
            _borrar_temporal_sin_fallar(plan.temporal, trabajo_id)
            _finalizar_con_reintento(
                bd_ruta,
                trabajo_id,
                "error",
                progreso,
                registro,
                mensaje,
            )
            return
        _finalizar_con_reintento(
            bd_ruta,
            trabajo_id,
            "hecho",
            progreso,
            registro,
            None,
        )
    except Exception:
        logger.exception("Fallo inesperado en el trabajo %s", trabajo_id)
        with en_curso.cerrojo:
            motivo = en_curso.motivo
            en_curso.motivo = en_curso.motivo or "fin"
        if proceso is not None and (motivo == "cancelado" or proceso.poll() is None):
            _terminar_grupo(proceso)
            proceso.wait()
        _borrar_temporal_sin_fallar(plan.temporal, trabajo_id)
        if motivo == "cancelado":
            _finalizar_con_reintento(
                bd_ruta,
                trabajo_id,
                "cancelado",
                progreso,
                registro,
                ERROR_CANCELADO,
            )
        elif motivo != "apagado":
            _finalizar_con_reintento(
                bd_ruta,
                trabajo_id,
                "error",
                progreso,
                registro,
                plan.mensajes.guardado,
            )
    finally:
        if temporizador is not None:
            temporizador.cancel()


def _ejecutar_y_olvidar(
    bd_ruta: Path,
    trabajo_id: int,
    plan: PlanTrabajo,
) -> None:
    try:
        _ejecutar(bd_ruta, trabajo_id, plan)
    finally:
        with _BLOQUEO:
            _HILOS.pop(trabajo_id, None)
            _EN_CURSO.pop(trabajo_id, None)


def lanzar(
    bd_ruta: Path,
    curso: str | None,
    numero: int | None,
    plan: PlanTrabajo,
) -> Trabajo:
    reciclados: list[tuple[int, str | None]] = []
    with _BLOQUEO, closing(abrir_bd(bd_ruta)) as bd:
        aislamiento_anterior = bd.isolation_level
        bd.isolation_level = None
        try:
            bd.execute("BEGIN IMMEDIATE")
            en_marcha = bd.execute(
                "SELECT id, temporal FROM trabajo WHERE estado = 'en_marcha'"
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
                    SET estado = 'interrumpido', fin = ?, error = ?
                    WHERE id = ? AND estado = 'en_marcha'
                    """,
                    [(_ahora(), ERROR_INTERRUMPIDO, fila[0]) for fila in en_marcha],
                )
                reciclados = [(fila[0], fila[1]) for fila in en_marcha]
            cursor = bd.execute(
                """
                INSERT INTO trabajo
                    (accion, curso, numero, objetivo, estado, inicio, temporal)
                VALUES (?, ?, ?, ?, 'en_marcha', ?, ?)
                """,
                (
                    plan.accion,
                    curso,
                    numero,
                    plan.objetivo,
                    _ahora(),
                    str(plan.temporal) if plan.temporal is not None else None,
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

        for reciclado_id, temporal_reciclado in reciclados:
            if temporal_reciclado is not None:
                _borrar_temporal_sin_fallar(Path(temporal_reciclado), reciclado_id)

        trabajo = leer_trabajo(bd, trabajo_id)
        assert trabajo is not None
        hilo = threading.Thread(
            target=_ejecutar_y_olvidar,
            args=(bd_ruta, trabajo_id, plan),
            daemon=True,
            name=f"trabajo-{trabajo_id}",
        )
        _HILOS[trabajo_id] = hilo
        _EN_CURSO[trabajo_id] = _EnCurso(
            bd_ruta=bd_ruta,
            temporal=plan.temporal,
        )
        try:
            hilo.start()
        except Exception:
            logger.exception("No se pudo iniciar el hilo del trabajo %s", trabajo_id)
            _HILOS.pop(trabajo_id, None)
            _EN_CURSO.pop(trabajo_id, None)
            _borrar_temporal_sin_fallar(plan.temporal, trabajo_id)
            _finalizar_con_reintento(
                bd_ruta,
                trabajo_id,
                "error",
                0.0,
                [],
                plan.mensajes.arranque,
            )
            fallido = leer_trabajo(bd, trabajo_id)
            assert fallido is not None
            return fallido
        return trabajo


def cancelar(bd_ruta: Path, id: int) -> Trabajo | None:
    with _BLOQUEO:
        en_curso = _EN_CURSO.get(id)
        hilo = _HILOS.get(id)
    if (
        en_curso is None
        or hilo is None
        or en_curso.bd_ruta != bd_ruta
        or not hilo.is_alive()
    ):
        return None

    with en_curso.cerrojo:
        if en_curso.motivo is None:
            en_curso.motivo = "cancelado"
        proceso = en_curso.proceso if en_curso.motivo == "cancelado" else None

    limite = monotonic() + 15
    if proceso is not None:
        try:
            _terminar_grupo(proceso)
        except Exception:
            logger.exception("No se pudo cancelar el trabajo %s", id)
    hilo.join(max(0.0, limite - monotonic()))

    with closing(abrir_bd(bd_ruta)) as bd:
        return leer_trabajo(bd, id)


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
            SET estado = 'interrumpido', fin = ?, error = ?
            WHERE id = ? AND estado = 'en_marcha'
            """,
            [(_ahora(), ERROR_INTERRUMPIDO, trabajo_id) for trabajo_id in ids],
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


def _marcar_interrumpido(bd_ruta: Path, trabajo_id: int) -> None:
    try:
        with closing(abrir_bd(bd_ruta)) as bd, bd:
            bd.execute(
                """
                UPDATE trabajo
                SET estado = 'interrumpido', fin = ?, error = ?
                WHERE id = ? AND estado = 'en_marcha'
                """,
                (_ahora(), ERROR_INTERRUMPIDO, trabajo_id),
            )
    except Exception:
        logger.exception("No se pudo marcar interrumpido el trabajo %s", trabajo_id)


def apagar_trabajos(bd_ruta: Path) -> None:
    """Al apagar la API: mata el grupo de cada render de esta base y lo cierra.

    Cada trabajo queda ``interrumpido`` y sin temporal. Un SIGKILL a la API no
    pasa por aquí; ese caso lo recoge ``interrumpir_huerfanos`` al arrancar.
    """
    with _BLOQUEO:
        candidatos = [
            (trabajo_id, en_curso, _HILOS.get(trabajo_id))
            for trabajo_id, en_curso in _EN_CURSO.items()
            if en_curso.bd_ruta == bd_ruta
        ]
    for trabajo_id, en_curso, _ in candidatos:
        with en_curso.cerrojo:
            if en_curso.motivo is None:
                en_curso.motivo = "apagado"
            motivo = en_curso.motivo
            proceso = en_curso.proceso
        if motivo == "fin":
            continue
        if motivo == "apagado":
            _marcar_interrumpido(bd_ruta, trabajo_id)
        if proceso is not None:
            try:
                _terminar_grupo(proceso)
            except Exception:
                logger.exception(
                    "No se pudo parar el render del trabajo %s", trabajo_id
                )
        if motivo == "apagado":
            _borrar_temporal_sin_fallar(en_curso.temporal, trabajo_id)
    for _, _, hilo in candidatos:
        if hilo is not None:
            hilo.join(_ESPERA_HILOS_AL_APAGAR)


def esperar(id: int, timeout: float) -> None:
    with _BLOQUEO:
        hilo = _HILOS.get(id)
    if hilo is not None:
        hilo.join(timeout)
