import re
import sqlite3
from contextlib import nullcontext
from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_PATRON_FECHA = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_PATRON_HORA = re.compile(r"([01][0-9]|2[0-3]):[0-5][0-9]")
_PATRON_CURSO = re.compile(r"[a-z0-9-]{1,40}")
_PATRON_TIPO = re.compile(r"[a-z0-9-]{1,30}")
_PATRON_PIEZA = re.compile(r"(leccion|reel-salida(-[1-9][0-9]*)?|short-[1-9][0-9]*)")

ColorTarea = Literal[
    "#299BC6",
    "#4BC98C",
    "#E8A33D",
    "#E5534B",
    "#A371F7",
    "#6CCBEF",
    "#F778BA",
    "#9B9BA4",
]
ResultadoBorrado = Literal["borrado", "no_existe", "en_uso"]


class _ModeloEstricto(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EnlaceTarea(_ModeloEstricto):
    curso: str
    numero: int | None = Field(default=None, strict=True, ge=1, le=999)
    pieza: str | None = None
    red: Literal["youtube", "instagram", "tiktok", "linkedin"] | None = None

    @field_validator("curso")
    @classmethod
    def validar_curso(cls, valor: str) -> str:
        if _PATRON_CURSO.fullmatch(valor) is None:
            raise ValueError("El id del curso no es válido")
        return valor

    @field_validator("pieza")
    @classmethod
    def validar_pieza(cls, valor: str | None) -> str | None:
        if valor is not None and _PATRON_PIEZA.fullmatch(valor) is None:
            raise ValueError("La pieza no es válida")
        return valor

    @model_validator(mode="after")
    def validar_jerarquia(self) -> Self:
        if self.pieza is not None and self.numero is None:
            raise ValueError("Una pieza exige un número de lección")
        if self.red is not None and self.pieza is None:
            raise ValueError("Una red exige una pieza")
        return self


class TareaNueva(_ModeloEstricto):
    fecha: date
    hora: str | None = None
    texto: str
    tipo: str
    enlace: EnlaceTarea | None = None

    @field_validator("fecha", mode="before")
    @classmethod
    def validar_formato_fecha(cls, valor: object) -> object:
        if isinstance(valor, str):
            if _PATRON_FECHA.fullmatch(valor) is None:
                raise ValueError("La fecha debe tener formato YYYY-MM-DD")
            return valor
        if isinstance(valor, datetime) or not isinstance(valor, date):
            raise ValueError(  # noqa: TRY004 - Pydantic no convierte TypeError.
                "La fecha debe tener formato YYYY-MM-DD"
            )
        return valor

    @field_validator("hora")
    @classmethod
    def validar_hora(cls, valor: str | None) -> str | None:
        if valor is not None and _PATRON_HORA.fullmatch(valor) is None:
            raise ValueError("La hora debe tener formato HH:MM")
        return valor

    @field_validator("texto")
    @classmethod
    def validar_texto(cls, valor: str) -> str:
        recortado = valor.strip()
        if not 1 <= len(recortado) <= 300:
            raise ValueError("El texto debe tener entre 1 y 300 caracteres")
        if len(recortado.splitlines()) != 1 or any(
            ord(caracter) < 0x20 or ord(caracter) == 0x7F for caracter in recortado
        ):
            raise ValueError("El texto no puede contener saltos de línea")
        return recortado

    @field_validator("tipo")
    @classmethod
    def validar_tipo(cls, valor: str) -> str:
        if _PATRON_TIPO.fullmatch(valor) is None:
            raise ValueError("El id del tipo no es válido")
        return valor


class Tarea(TareaNueva):
    id: int
    hecha: bool
    hecha_en: datetime | None


class DatosTipoTarea(_ModeloEstricto):
    nombre: str
    color: ColorTarea
    orden: int = Field(strict=True, ge=0, le=10_000)

    @field_validator("nombre")
    @classmethod
    def validar_nombre(cls, valor: str) -> str:
        recortado = valor.strip()
        if not 1 <= len(recortado) <= 40:
            raise ValueError("El nombre debe tener entre 1 y 40 caracteres")
        return recortado


class TipoTarea(DatosTipoTarea):
    id: str

    @field_validator("id")
    @classmethod
    def validar_id(cls, valor: str) -> str:
        if _PATRON_TIPO.fullmatch(valor) is None:
            raise ValueError("El id del tipo no es válido")
        return valor


class CursoApp(_ModeloEstricto):
    id: str
    nombre: str

    @field_validator("id")
    @classmethod
    def validar_id(cls, valor: str) -> str:
        if _PATRON_CURSO.fullmatch(valor) is None:
            raise ValueError("El id del curso no es válido")
        return valor

    @field_validator("nombre")
    @classmethod
    def validar_nombre(cls, valor: str) -> str:
        recortado = valor.strip()
        if not 1 <= len(recortado) <= 60:
            raise ValueError("El nombre debe tener entre 1 y 60 caracteres")
        return recortado


_SELECT_TAREA_POR_ID = """
    SELECT id, fecha, hora, texto, tipo, curso, numero, pieza, red, hecha, hecha_en
    FROM tarea
    WHERE id = ?
"""
_SELECT_TAREAS_ENTRE = """
    SELECT id, fecha, hora, texto, tipo, curso, numero, pieza, red, hecha, hecha_en
    FROM tarea
    WHERE fecha BETWEEN ? AND ?
    ORDER BY fecha, hora IS NULL, hora, id
"""
_SELECT_TAREAS_ATRASADAS = """
    SELECT id, fecha, hora, texto, tipo, curso, numero, pieza, red, hecha, hecha_en
    FROM tarea
    WHERE fecha < ? AND hecha = 0
    ORDER BY fecha, hora IS NULL, hora, id
    LIMIT ?
"""


def _tarea_desde_fila(fila: tuple[object, ...]) -> Tarea:
    curso = fila[5]
    enlace = None
    if curso is not None:
        enlace = EnlaceTarea(
            curso=curso,
            numero=fila[6],
            pieza=fila[7],
            red=fila[8],
        )
    return Tarea(
        id=fila[0],
        fecha=fila[1],
        hora=fila[2],
        texto=fila[3],
        tipo=fila[4],
        enlace=enlace,
        hecha=fila[9],
        hecha_en=fila[10],
    )


def _buscar_tarea(bd: sqlite3.Connection, id: int) -> Tarea | None:
    fila = bd.execute(_SELECT_TAREA_POR_ID, (id,)).fetchone()
    return _tarea_desde_fila(fila) if fila is not None else None


def _valores_enlace(
    enlace: EnlaceTarea | None,
) -> tuple[str | None, int | None, str | None, str | None]:
    if enlace is None:
        return None, None, None, None
    return enlace.curso, enlace.numero, enlace.pieza, enlace.red


def crear_tarea(bd: sqlite3.Connection, nueva: TareaNueva) -> Tarea:
    curso, numero, pieza, red = _valores_enlace(nueva.enlace)
    with bd:
        cursor = bd.execute(
            """
            INSERT INTO tarea
                (fecha, hora, texto, tipo, curso, numero, pieza, red)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                nueva.fecha.isoformat(),
                nueva.hora,
                nueva.texto,
                nueva.tipo,
                curso,
                numero,
                pieza,
                red,
            ),
        )
    tarea = _buscar_tarea(bd, cursor.lastrowid)
    if tarea is None:
        raise RuntimeError("No se ha podido recuperar la tarea creada")
    return tarea


def editar_tarea(bd: sqlite3.Connection, id: int, nueva: TareaNueva) -> Tarea | None:
    curso, numero, pieza, red = _valores_enlace(nueva.enlace)
    with bd:
        cursor = bd.execute(
            """
            UPDATE tarea
            SET fecha = ?, hora = ?, texto = ?, tipo = ?,
                curso = ?, numero = ?, pieza = ?, red = ?
            WHERE id = ?
            """,
            (
                nueva.fecha.isoformat(),
                nueva.hora,
                nueva.texto,
                nueva.tipo,
                curso,
                numero,
                pieza,
                red,
                id,
            ),
        )
    return _buscar_tarea(bd, id) if cursor.rowcount else None


def marcar_hecha(bd: sqlite3.Connection, id: int, hecha: bool) -> Tarea | None:
    hecha_en = datetime.now().replace(microsecond=0).isoformat() if hecha else None
    with bd:
        cursor = bd.execute(
            "UPDATE tarea SET hecha = ?, hecha_en = ? WHERE id = ?",
            (hecha, hecha_en, id),
        )
    return _buscar_tarea(bd, id) if cursor.rowcount else None


def borrar_tarea(bd: sqlite3.Connection, id: int) -> bool:
    with bd:
        cursor = bd.execute("DELETE FROM tarea WHERE id = ?", (id,))
    return cursor.rowcount > 0


def tareas_entre(bd: sqlite3.Connection, desde: date, hasta: date) -> list[Tarea]:
    filas = bd.execute(
        _SELECT_TAREAS_ENTRE,
        (desde.isoformat(), hasta.isoformat()),
    )
    return [_tarea_desde_fila(fila) for fila in filas]


def tareas_atrasadas(
    bd: sqlite3.Connection, antes_de: date, limite: int = 200
) -> list[Tarea]:
    limite_efectivo = min(max(limite, 0), 200)
    filas = bd.execute(
        _SELECT_TAREAS_ATRASADAS,
        (antes_de.isoformat(), limite_efectivo),
    )
    return [_tarea_desde_fila(fila) for fila in filas]


def completar_tareas_de_red(
    bd: sqlite3.Connection,
    curso: str,
    numero: int,
    pieza: str,
    red: str,
) -> int:
    hecha_en = datetime.now().replace(microsecond=0).isoformat()
    contexto_transaccion = nullcontext() if bd.in_transaction else bd
    with contexto_transaccion:
        cursor = bd.execute(
            """
            UPDATE tarea
            SET hecha = 1, hecha_en = ?
            WHERE hecha = 0 AND curso = ? AND numero = ? AND pieza = ? AND red = ?
            """,
            (hecha_en, curso, numero, pieza, red),
        )
    return cursor.rowcount


def tipos(bd: sqlite3.Connection) -> list[TipoTarea]:
    filas = bd.execute(
        "SELECT id, nombre, color, orden FROM tipo_tarea ORDER BY orden, id"
    )
    return [
        TipoTarea(id=id, nombre=nombre, color=color, orden=orden)
        for id, nombre, color, orden in filas
    ]


def crear_tipo(bd: sqlite3.Connection, tipo: TipoTarea) -> TipoTarea:
    with bd:
        bd.execute(
            "INSERT INTO tipo_tarea (id, nombre, color, orden) VALUES (?, ?, ?, ?)",
            (tipo.id, tipo.nombre, tipo.color, tipo.orden),
        )
    return tipo


def editar_tipo(bd: sqlite3.Connection, id: str, tipo: TipoTarea) -> TipoTarea | None:
    with bd:
        cursor = bd.execute(
            """
            UPDATE tipo_tarea SET nombre = ?, color = ?, orden = ? WHERE id = ?
            """,
            (tipo.nombre, tipo.color, tipo.orden, id),
        )
    if not cursor.rowcount:
        return None
    return TipoTarea(id=id, nombre=tipo.nombre, color=tipo.color, orden=tipo.orden)


def borrar_tipo(bd: sqlite3.Connection, id: str) -> ResultadoBorrado:
    bd.execute("BEGIN IMMEDIATE")
    try:
        if (
            bd.execute("SELECT 1 FROM tipo_tarea WHERE id = ?", (id,)).fetchone()
            is None
        ):
            bd.commit()
            return "no_existe"
        if bd.execute("SELECT 1 FROM tarea WHERE tipo = ? LIMIT 1", (id,)).fetchone():
            bd.commit()
            return "en_uso"
        bd.execute("DELETE FROM tipo_tarea WHERE id = ?", (id,))
        bd.commit()
    except Exception:
        bd.rollback()
        raise
    return "borrado"


def cursos_app(bd: sqlite3.Connection) -> list[CursoApp]:
    filas = bd.execute(
        "SELECT id, nombre FROM curso_app ORDER BY nombre COLLATE NOCASE, id"
    )
    return [CursoApp(id=id, nombre=nombre) for id, nombre in filas]


def crear_curso_app(bd: sqlite3.Connection, curso: CursoApp) -> CursoApp:
    with bd:
        bd.execute(
            "INSERT INTO curso_app (id, nombre) VALUES (?, ?)",
            (curso.id, curso.nombre),
        )
    return curso


def borrar_curso_app(bd: sqlite3.Connection, id: str) -> ResultadoBorrado:
    bd.execute("BEGIN IMMEDIATE")
    try:
        if bd.execute("SELECT 1 FROM curso_app WHERE id = ?", (id,)).fetchone() is None:
            bd.commit()
            return "no_existe"
        if bd.execute("SELECT 1 FROM tarea WHERE curso = ? LIMIT 1", (id,)).fetchone():
            bd.commit()
            return "en_uso"
        bd.execute("DELETE FROM curso_app WHERE id = ?", (id,))
        bd.commit()
    except Exception:
        bd.rollback()
        raise
    return "borrado"
