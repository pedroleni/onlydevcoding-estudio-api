import sqlite3
from typing import Any

from pydantic import BaseModel, ConfigDict

from estudio_api.config import Config
from estudio_api.lectura import (
    datos_curso,
    leer_cursos,
    leer_leccion,
    leer_lecciones,
)
from estudio_api.modelos import Curso, Leccion, LeccionResumen
from estudio_api.tareas import Tarea


class EnlaceVista(BaseModel):
    model_config = ConfigDict(extra="forbid")

    curso_nombre: str | None
    leccion_titulo: str | None
    pieza_titulo: str | None
    roto: bool


class TareaVista(Tarea):
    enlace_vista: EnlaceVista | None


class TareasDelRango(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tareas: list[TareaVista]
    atrasadas: list[TareaVista]


class _CacheEnlaces:
    """Resuelve los enlaces leyendo cada curso una sola vez por petición."""

    def __init__(self, config: Config, bd: sqlite3.Connection) -> None:
        self.config = config
        self.bd = bd
        self._cursos: dict[str, Curso] | None = None
        self._datos: dict[str, Any] = {}
        self._lecciones: dict[str, dict[int, LeccionResumen]] = {}
        self._detalles: dict[tuple[str, int], Leccion | None] = {}

    def _curso(self, identificador: str) -> Curso | None:
        # Mismo criterio que el listado de cursos y que la validación al crear.
        if self._cursos is None:
            try:
                cursos = leer_cursos(self.config, self.bd)
            except Exception:  # noqa: BLE001 - el enlace roto tolera cualquier lector.
                cursos = []
            self._cursos = {curso.id: curso for curso in cursos}
        return self._cursos.get(identificador)

    def _datos_de(self, curso: str) -> Any:
        if curso not in self._datos:
            try:
                self._datos[curso] = datos_curso(self.config, curso)
            except Exception:  # noqa: BLE001 - el enlace roto tolera cualquier lector.
                self._datos[curso] = None
        return self._datos[curso]

    def _resumenes(self, curso: str) -> dict[int, LeccionResumen]:
        if curso not in self._lecciones:
            try:
                lecciones = leer_lecciones(
                    self.config, curso, self.bd, datos=self._datos_de(curso)
                )
            except Exception:  # noqa: BLE001 - el enlace roto tolera cualquier lector.
                lecciones = []
            self._lecciones[curso] = {leccion.numero: leccion for leccion in lecciones}
        return self._lecciones[curso]

    def _detalle(self, curso: str, numero: int) -> Leccion | None:
        clave = (curso, numero)
        if clave not in self._detalles:
            try:
                self._detalles[clave] = leer_leccion(
                    self.config, curso, numero, self.bd, datos=self._datos_de(curso)
                )
            except Exception:  # noqa: BLE001 - un guion corrupto no tumba el listado.
                self._detalles[clave] = None
        return self._detalles[clave]

    def tarea(self, tarea: Tarea) -> TareaVista:
        enlace = tarea.enlace
        if enlace is None:
            return TareaVista(**tarea.model_dump(), enlace_vista=None)

        curso = self._curso(enlace.curso)
        curso_nombre = curso.nombre if curso is not None else None
        leccion_titulo = None
        pieza_titulo = None
        roto = curso is None

        if enlace.numero is not None and curso is not None:
            # Una lección que solo tiene guion sigue siendo válida: aún se prepara.
            resumen = self._resumenes(enlace.curso).get(enlace.numero)
            if resumen is None:
                roto = True
            else:
                leccion_titulo = resumen.titulo

            if enlace.pieza is not None and resumen is not None:
                detalle = self._detalle(enlace.curso, enlace.numero)
                if detalle is None:
                    roto = True
                else:
                    leccion_titulo = leccion_titulo or detalle.titulo
                    pieza = next(
                        (
                            candidata
                            for candidata in detalle.piezas
                            if candidata.id == enlace.pieza
                        ),
                        None,
                    )
                    if pieza is None:
                        roto = True
                    else:
                        pieza_titulo = pieza.titulo

        return TareaVista(
            **tarea.model_dump(),
            enlace_vista=EnlaceVista(
                curso_nombre=curso_nombre,
                leccion_titulo=leccion_titulo,
                pieza_titulo=pieza_titulo,
                roto=roto,
            ),
        )


def construir_vistas_tareas(
    config: Config,
    bd: sqlite3.Connection,
    tareas: list[Tarea],
) -> list[TareaVista]:
    cache = _CacheEnlaces(config, bd)
    return [cache.tarea(tarea) for tarea in tareas]
