import logging
import os
import sqlite3
import tempfile
from contextlib import closing, nullcontext
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
            fecha TEXT,
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


def _crear_tabla_trabajo(bd: sqlite3.Connection) -> None:
    bd.execute(
        """
        CREATE TABLE trabajo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            accion TEXT NOT NULL,
            curso TEXT,
            numero INTEGER,
            estado TEXT NOT NULL,
            progreso REAL NOT NULL DEFAULT 0,
            inicio TEXT NOT NULL,
            fin TEXT,
            error TEXT,
            registro TEXT NOT NULL DEFAULT '[]',
            temporal TEXT,
            objetivo TEXT
        )
        """
    )


def _copia_antes_de_migrar(
    bd: sqlite3.Connection, ruta: Path, version_esperada: int = 1
) -> None:
    """Guarda la base en <ruta>.vN si aún conserva la versión esperada."""
    destino = ruta.with_name(f"{ruta.name}.v{version_esperada}")
    if destino.exists():
        return
    descriptor, nombre = tempfile.mkstemp(
        prefix=f".{ruta.name}.v{version_esperada}.", dir=ruta.parent
    )
    os.close(descriptor)
    temporal = Path(nombre)
    try:
        with closing(sqlite3.connect(temporal)) as copia:
            bd.backup(copia)
            version = copia.execute("PRAGMA user_version").fetchone()[0]
        # Otra apertura pudo migrar entretanto: solo sirve la versión observada.
        if version == version_esperada:
            os.replace(temporal, destino)
    finally:
        temporal.unlink(missing_ok=True)


VERSION_BD = 6


def _permitir_tareas_sin_fecha(bd: sqlite3.Connection) -> None:
    # SQLite no quita un NOT NULL con ALTER: se rehace la tabla con los mismos ids.
    # Nadie referencia a tarea, así que se puede borrar con las claves foráneas activas.
    bd.execute(
        """
        CREATE TABLE tarea_v6 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT,
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
    bd.execute(
        """
        INSERT INTO tarea_v6
            (id, fecha, hora, texto, tipo, curso, numero, pieza, red, hecha, hecha_en)
        SELECT id, fecha, hora, texto, tipo, curso, numero, pieza, red, hecha, hecha_en
        FROM tarea
        """
    )
    bd.execute("DROP TABLE tarea")
    bd.execute("ALTER TABLE tarea_v6 RENAME TO tarea")
    bd.execute("CREATE INDEX idx_tarea_fecha ON tarea(fecha)")


def _crear_tabla_gancho_grabado(bd: sqlite3.Connection) -> None:
    # Ganchos verticales (reels) marcados a mano como grabados en el teleprompter.
    bd.execute(
        """
        CREATE TABLE IF NOT EXISTS gancho_grabado (
            curso TEXT NOT NULL,
            numero INTEGER NOT NULL,
            gancho TEXT NOT NULL,
            fecha TEXT NOT NULL,
            PRIMARY KEY (curso, numero, gancho)
        )
        """
    )


def abrir_bd(ruta: Path) -> sqlite3.Connection:  # noqa: C901, PLR0912
    ruta.parent.mkdir(parents=True, exist_ok=True)
    bd = sqlite3.connect(ruta)
    try:
        bd.execute("PRAGMA foreign_keys = ON")
        version = bd.execute("PRAGMA user_version").fetchone()[0]
        if version == VERSION_BD:
            return bd
        if version not in (0, 1, 2, 3, 4, 5):
            raise RuntimeError(f"Versión de la base de datos no soportada: {version}")

        if version in (1, 2, 3, 4, 5):
            # Antes del cerrojo de escritura: backup() no puede leer una base bloqueada
            # por su propia conexión.
            _copia_antes_de_migrar(bd, ruta, version)

        aislamiento_anterior = bd.isolation_level
        bd.isolation_level = None
        try:
            bd.execute("BEGIN IMMEDIATE")
            version = bd.execute("PRAGMA user_version").fetchone()[0]
            if version == VERSION_BD:
                bd.execute("COMMIT")
                return bd
            if version not in (0, 1, 2, 3, 4, 5):
                raise RuntimeError(
                    f"Versión de la base de datos no soportada: {version}"
                )
            if version == 0:
                _crear_tablas_fase_2(bd)
            if version in (0, 1):
                _crear_tablas_tareas(bd)
            if version in (0, 1, 2):
                _crear_tabla_trabajo(bd)
            if version == 3:
                bd.execute("ALTER TABLE trabajo ADD COLUMN objetivo TEXT")
            if version in (0, 1, 2, 3, 4):
                _crear_tabla_gancho_grabado(bd)
            if version in (2, 3, 4, 5):
                _permitir_tareas_sin_fecha(bd)
            bd.execute(f"PRAGMA user_version = {VERSION_BD}")
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
    contexto_transaccion = nullcontext() if bd.in_transaction else bd
    with contexto_transaccion:
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


def marcar_gancho_grabado(
    bd: sqlite3.Connection,
    curso: str,
    numero: int,
    gancho: str,
    grabado: bool,
    fecha: str,
) -> None:
    with bd:
        if grabado:
            bd.execute(
                """
                INSERT INTO gancho_grabado (curso, numero, gancho, fecha)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (curso, numero, gancho) DO NOTHING
                """,
                (curso, numero, gancho, fecha),
            )
        else:
            bd.execute(
                "DELETE FROM gancho_grabado WHERE curso = ? AND numero = ? AND gancho = ?",
                (curso, numero, gancho),
            )


def ganchos_grabados(bd: sqlite3.Connection, curso: str) -> set[tuple[int, str]]:
    return {
        (numero, gancho)
        for numero, gancho in bd.execute(
            "SELECT numero, gancho FROM gancho_grabado WHERE curso = ?", (curso,)
        )
    }
