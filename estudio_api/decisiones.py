import logging
import sqlite3
from pathlib import Path

from pydantic import ValidationError

from estudio_api.modelos import EstadoRed

logger = logging.getLogger(__name__)


def abrir_bd(ruta: Path) -> sqlite3.Connection:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    bd = sqlite3.connect(ruta)
    try:
        version = bd.execute("PRAGMA user_version").fetchone()[0]
        if version == 1:
            return bd
        if version != 0:
            raise RuntimeError(f"Versión de la base de datos no soportada: {version}")

        with bd:
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
            bd.execute("PRAGMA user_version = 1")
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
