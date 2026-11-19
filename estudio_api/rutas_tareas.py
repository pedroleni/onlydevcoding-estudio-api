import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request, status
from pydantic import BaseModel, ConfigDict, StrictBool
from starlette.responses import Response

from estudio_api.config import Config
from estudio_api.decisiones import abrir_bd
from estudio_api.lectura import (
    curso_existe,
    ids_cursos_en_disco,
    leer_leccion,
    leer_lecciones,
)
from estudio_api.reels import leer_temario
from estudio_api.rutas_api import config_peticion
from estudio_api.tareas import (
    DatosTipoTarea,
    EnlaceTarea,
    Tarea,
    TareaNueva,
    TipoTarea,
    borrar_tarea,
    borrar_tipo,
    crear_tarea,
    crear_tipo,
    cursos_app,
    editar_tarea,
    editar_tipo,
    marcar_hecha,
    tareas_atrasadas,
    tareas_entre,
    tareas_sin_fecha,
    tipos,
)
from estudio_api.vista_tareas import (
    TareasDelRango,
    TareaVista,
    construir_vistas_tareas,
)

router = APIRouter(prefix="/api")
TareaId = Annotated[int, Path(ge=1, le=2**63 - 1)]
TipoId = Annotated[str, Path(pattern=r"^[a-z0-9-]{1,30}$")]


class CambioHecha(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hecha: StrictBool


class EdicionTipoTarea(DatosTipoTarea):
    pass


def _tipo_existe(bd: sqlite3.Connection, identificador: str) -> bool:
    return any(tipo.id == identificador for tipo in tipos(bd))


def _en_temario(config: Config, curso: str, numero: int) -> bool:
    try:
        temario = leer_temario(config, curso)
    except Exception:  # noqa: BLE001 - un temario ilegible equivale a no tenerlo.
        return False
    return temario is not None and any(
        leccion.numero == numero for leccion in temario.lecciones
    )


def _validar_enlace(
    config: Config,
    bd: sqlite3.Connection,
    enlace: EnlaceTarea | None,
) -> None:
    if enlace is None:
        return

    # Mismo criterio que el listado de cursos y que la vista de tareas.
    en_disco = enlace.curso in ids_cursos_en_disco(config)
    en_app = any(curso.id == enlace.curso for curso in cursos_app(bd))
    if not en_disco and not en_app:
        raise HTTPException(status_code=422, detail="El curso no existe")
    if enlace.numero is None:
        return
    if not en_disco:
        raise HTTPException(
            status_code=422,
            detail="Un curso sin carpeta solo se puede enlazar a nivel de curso",
        )

    try:
        resumen = next(
            (
                leccion
                for leccion in leer_lecciones(config, enlace.curso, bd)
                if leccion.numero == enlace.numero
            ),
            None,
        )
    except Exception as error:
        raise HTTPException(
            status_code=422,
            detail="No se ha podido leer la lección",
        ) from error
    # Basta con que la lección esté en el listado, aunque solo tenga guion:
    # son justo las que aún se preparan o se graban.
    if resumen is None:
        # Una lección que solo está en el temario también se planifica, pero aún no
        # tiene piezas a las que enlazar.
        if not _en_temario(config, enlace.curso, enlace.numero):
            raise HTTPException(status_code=422, detail="La lección no existe")
        if enlace.pieza is not None:
            raise HTTPException(status_code=422, detail="La pieza no existe")
        return
    if enlace.pieza is None:
        return

    try:
        leccion = leer_leccion(config, enlace.curso, enlace.numero, bd)
    except Exception as error:
        raise HTTPException(
            status_code=422,
            detail="No se ha podido leer la lección",
        ) from error
    if leccion is None:
        raise HTTPException(status_code=422, detail="La lección no existe")
    if all(pieza.id != enlace.pieza for pieza in leccion.piezas):
        raise HTTPException(status_code=422, detail="La pieza no existe")


def _validar_tarea_nueva(
    config: Config,
    bd: sqlite3.Connection,
    nueva: TareaNueva,
) -> None:
    if not _tipo_existe(bd, nueva.tipo):
        raise HTTPException(status_code=422, detail="El tipo de tarea no existe")
    _validar_enlace(config, bd, nueva.enlace)


def _guardar(
    config: Config,
    bd: sqlite3.Connection,
    nueva: TareaNueva,
    operar: Callable[[], Tarea | None],
) -> Tarea | None:
    # Las lecturas de disco van fuera del cerrojo; dentro se vuelve a comprobar el curso,
    # que un DELETE /api/cursos puede haber borrado entretanto.
    _validar_tarea_nueva(config, bd, nueva)
    try:
        with bd:
            bd.execute("BEGIN IMMEDIATE")
            if nueva.enlace is not None and not curso_existe(
                config, bd, nueva.enlace.curso
            ):
                raise HTTPException(status_code=422, detail="El curso no existe")
            return operar()
    except sqlite3.IntegrityError as error:
        raise HTTPException(
            status_code=422,
            detail="El tipo de tarea no existe",
        ) from error


def _vista_unica(
    config: Config,
    bd: sqlite3.Connection,
    tarea: Tarea,
) -> TareaVista:
    return construir_vistas_tareas(config, bd, [tarea])[0]


@router.get("/tareas", response_model=TareasDelRango)
def listar_tareas(
    request: Request,
    desde: date,
    hasta: date,
    atrasadas: bool = False,
) -> TareasDelRango:
    if hasta < desde or (hasta - desde).days >= 62:
        raise HTTPException(status_code=422, detail="El rango de fechas no es válido")

    config = config_peticion(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        del_rango = tareas_entre(bd, desde, hasta)
        anteriores = tareas_atrasadas(bd, desde) if atrasadas else []
        todas = construir_vistas_tareas(config, bd, [*del_rango, *anteriores])
    corte = len(del_rango)
    return TareasDelRango(tareas=todas[:corte], atrasadas=todas[corte:])


@router.get("/tareas/sin-fecha", response_model=list[TareaVista])
def listar_tareas_sin_fecha(request: Request) -> list[TareaVista]:
    config = config_peticion(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        return construir_vistas_tareas(config, bd, tareas_sin_fecha(bd))


@router.post(
    "/tareas",
    response_model=TareaVista,
    status_code=status.HTTP_201_CREATED,
)
def alta_tarea(request: Request, nueva: TareaNueva) -> TareaVista:
    config = config_peticion(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        tarea = _guardar(config, bd, nueva, lambda: crear_tarea(bd, nueva))
        assert tarea is not None
        return _vista_unica(config, bd, tarea)


@router.put("/tareas/{id}", response_model=TareaVista)
def modificar_tarea(
    request: Request,
    nueva: TareaNueva,
    id: TareaId,
) -> TareaVista:
    config = config_peticion(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        tarea = _guardar(config, bd, nueva, lambda: editar_tarea(bd, id, nueva))
        if tarea is None:
            raise HTTPException(status_code=404, detail="La tarea no existe")
        return _vista_unica(config, bd, tarea)


@router.put("/tareas/{id}/hecha", response_model=TareaVista)
def cambiar_tarea_hecha(
    request: Request,
    cambio: CambioHecha,
    id: TareaId,
) -> TareaVista:
    config = config_peticion(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        tarea = marcar_hecha(bd, id, cambio.hecha)
        if tarea is None:
            raise HTTPException(status_code=404, detail="La tarea no existe")
        return _vista_unica(config, bd, tarea)


@router.delete("/tareas/{id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_tarea(request: Request, id: TareaId) -> Response:
    config = config_peticion(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        borrada = borrar_tarea(bd, id)
    if not borrada:
        raise HTTPException(status_code=404, detail="La tarea no existe")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/tipos-tarea", response_model=list[TipoTarea])
def listar_tipos_tarea(request: Request) -> list[TipoTarea]:
    config = config_peticion(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        return tipos(bd)


@router.post(
    "/tipos-tarea",
    response_model=TipoTarea,
    status_code=status.HTTP_201_CREATED,
)
def alta_tipo_tarea(request: Request, tipo: TipoTarea) -> TipoTarea:
    config = config_peticion(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        try:
            return crear_tipo(bd, tipo)
        except sqlite3.IntegrityError as error:
            raise HTTPException(
                status_code=409,
                detail="Ya existe un tipo con ese id",
            ) from error


@router.put("/tipos-tarea/{id}", response_model=TipoTarea)
def modificar_tipo_tarea(
    request: Request,
    cambios: EdicionTipoTarea,
    id: TipoId,
) -> TipoTarea:
    config = config_peticion(request)
    tipo = TipoTarea(id=id, **cambios.model_dump())
    with closing(abrir_bd(config.bd_ruta)) as bd:
        editado = editar_tipo(bd, id, tipo)
    if editado is None:
        raise HTTPException(status_code=404, detail="El tipo de tarea no existe")
    return editado


@router.delete("/tipos-tarea/{id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_tipo_tarea(request: Request, id: TipoId) -> Response:
    config = config_peticion(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        resultado = borrar_tipo(bd, id)
    if resultado == "no_existe":
        raise HTTPException(status_code=404, detail="El tipo de tarea no existe")
    if resultado == "en_uso":
        raise HTTPException(
            status_code=409,
            detail="Hay tareas de este tipo; cámbialas antes de borrarlo",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
