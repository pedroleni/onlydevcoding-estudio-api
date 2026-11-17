import logging
import sqlite3
from pathlib import Path

from pydantic import ValidationError

from estudio_api.modelos import EstadoRed

logger = logging.getLogger(__name__)

_SEMBRAR_TIPOS = """
    INSERT INTO tipo_tarea (id, nombre, color, orden)
    VALUES
        (?, ?, ?, ?),
        (?, ?, ?, ?),
        (?, ?, ?, ?),
        (?, ?, ?, ?),
        (?, ?, ?, ?)
"""


def _crear_tablas_fase_2(bd: sqlite3.Connection) -> None:
    bd.execute(
        """
        CREATE TABLE IF NOT EXISTS portada_elegida (
            curso TEXT NOT NULL,
            numero INTEGER NOT NULL,
            pieza TEXT NOT NULL,
            ruta TEXT NOT NULL,
            PRIMARY KEY (curso, numero, pieza)
        )
        """
    )
    bd.execute(
        """
        CREATE TABLE IF NOT EXISTS estado_red (
            curso TEXT NOT NULL,
            numero INTEGER NOT NULL,
            pieza TEXT NOT NULL,
            red TEXT NOT NULL,
            estado TEXT NOT NULL,
            fecha TEXT,
            url TEXT,
            PRIMARY KEY (curso, numero, pieza, red)
        )
        """
    )


def _crear_tablas_tareas(bd: sqlite3.Connection) -> None:
    bd.execute(
        """
        CREATE TABLE tipo_tarea (
            id TEXT PRIMARY KEY,
            nombre TEXT NOT NULL,
            color TEXT NOT NULL,
            orden INTEGER NOT NULL
        )
        """
    )
    bd.execute(
        """
        CREATE TABLE curso_app (
            id TEXT PRIMARY KEY,
            nombre TEXT NOT NULL
        )
        """
    )
    bd.execute(
        """
        CREATE TABLE tarea (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            hora TEXT,
            texto TEXT NOT NULL,
            tipo TEXT NOT NULL REFERENCES tipo_tarea(id),
            curso TEXT,
            numero INTEGER,
            pieza TEXT,
            red TEXT,
            hecha INTEGER NOT NULL DEFAULT 0,
            hecha_en TEXT
        )
        """
    )
    bd.execute("CREATE INDEX idx_tarea_fecha ON tarea(fecha)")
    bd.execute(
        _SEMBRAR_TIPOS,
        (
            "preparar",
            "Preparar",
            "#A371F7",
            1,
            "grabar",
            "Grabar",
            "#E5534B",
            2,
            "editar",
            "Editar",
            "#E8A33D",
            3,
            "publicar",
            "Publicar",
            "#4BC98C",
            4,
            "otro",
            "Otro",
            "#9B9BA4",
            5,
        ),
    )


def abrir_bd(ruta: Path) -> sqlite3.Connection:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    bd = sqlite3.connect(ruta)
    try:
        bd.execute("PRAGMA foreign_keys = ON")
        version = bd.execute("PRAGMA user_version").fetchone()[0]
        if version == 2:
            return bd
        if version not in (0, 1):
            raise RuntimeError(f"Versión de la base de datos no soportada: {version}")

        aislamiento_anterior = bd.isolation_level
        bd.isolation_level = None
        try:
            bd.execute("BEGIN")
            if version == 0:
                _crear_tablas_fase_2(bd)
            _crear_tablas_tareas(bd)
            bd.execute("PRAGMA user_version = 2")
            bd.execute("COMMIT")
        except Exception:
            if bd.in_transaction:
                bd.execute("ROLLBACK")
            raise
        finally:
            bd.isolation_level = aislamiento_anterior
    except Exception:
        bd.close()
        raise
    return bd


def elegir_portada(
    bd: sqlite3.Connection,
    curso: str,
    numero: int,
    pieza: str,
    ruta: str,
) -> None:
    with bd:
        bd.execute(
            """
            INSERT INTO portada_elegida (curso, numero, pieza, ruta)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (curso, numero, pieza) DO UPDATE SET ruta = excluded.ruta
            """,
            (curso, numero, pieza, ruta),
        )


def portadas_elegidas(
    bd: sqlite3.Connection, curso: str, numero: int
) -> dict[str, str]:
    filas = bd.execute(
        """
        SELECT pieza, ruta
        FROM portada_elegida
        WHERE curso = ? AND numero = ?
        """,
        (curso, numero),
    )
    return dict(filas)


def fijar_estado(
    bd: sqlite3.Connection,
    curso: str,
    numero: int,
    pieza: str,
    red: str,
    estado: EstadoRed,
) -> None:
    with bd:
        if estado.estado == "pendiente":
            bd.execute(
                """
                DELETE FROM estado_red
                WHERE curso = ? AND numero = ? AND pieza = ? AND red = ?
                """,
                (curso, numero, pieza, red),
            )
            return

        fecha = estado.fecha.isoformat() if estado.fecha is not None else None
        bd.execute(
            """
            INSERT INTO estado_red
                (curso, numero, pieza, red, estado, fecha, url)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (curso, numero, pieza, red) DO UPDATE SET
                estado = excluded.estado,
                fecha = excluded.fecha,
                url = excluded.url
            """,
            (curso, numero, pieza, red, estado.estado, fecha, estado.url),
        )


def estados(
    bd: sqlite3.Connection, curso: str, numero: int
) -> dict[tuple[str, str], EstadoRed]:
    filas = bd.execute(
        """
        SELECT pieza, red, estado, fecha, url
        FROM estado_red
        WHERE curso = ? AND numero = ?
        """,
        (curso, numero),
    )
    resultado = {}
    for pieza, red, estado, fecha, url in filas:
        try:
            resultado[(pieza, red)] = EstadoRed(estado=estado, fecha=fecha, url=url)
        except ValidationError:
            logger.warning(
                "Fila de estado de red inconsistente omitida: "
                "curso=%r numero=%r pieza=%r red=%r",
                curso,
                numero,
                pieza,
                red,
            )
    return resultado
