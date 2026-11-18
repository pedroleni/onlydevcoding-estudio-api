from contextlib import closing

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict

from estudio_api.acciones import (
    AccionNoDisponible,
    EstadoAccion,
    IdAccion,
    OpcionesAccion,
    estados_acciones,
    plan_accion,
)
from estudio_api.config import Config
from estudio_api.decisiones import abrir_bd
from estudio_api.rutas_api import CursoId, NumeroLeccion, TrabajoId, config_peticion
from estudio_api.trabajos import (
    PlanTrabajo,
    Trabajo,
    TrabajoEnMarcha,
    cancelar,
    lanzar,
    leer_trabajo,
    listar_trabajos,
)

router = APIRouter(prefix="/api")


class PeticionCancelar(BaseModel):
    model_config = ConfigDict(extra="forbid")


def lanzar_plan(
    config: Config,
    curso: str,
    numero: int,
    plan: PlanTrabajo,
) -> Trabajo:
    """Lanza el plan; la carpeta del resultado se prepara ya con el trabajo reservado."""
    try:
        return lanzar(config.bd_ruta, curso, numero, plan)
    except TrabajoEnMarcha as error:
        raise HTTPException(
            status_code=409,
            detail="Ya hay un trabajo en marcha",
        ) from error
    except AccionNoDisponible as error:
        raise HTTPException(
            status_code=error.estado_http,
            detail=error.mensaje,
        ) from error


@router.get(
    "/cursos/{curso}/lecciones/{numero}/acciones",
    response_model=list[EstadoAccion],
)
def obtener_acciones(
    request: Request,
    curso: CursoId,
    numero: NumeroLeccion,
) -> list[EstadoAccion]:
    config = config_peticion(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        acciones = estados_acciones(config, bd, curso, numero)
    if acciones is None:
        raise HTTPException(status_code=404, detail="La lección no existe")
    return acciones


@router.post(
    "/cursos/{curso}/lecciones/{numero}/acciones/{accion}",
    response_model=Trabajo,
    status_code=status.HTTP_202_ACCEPTED,
)
def ejecutar_accion(
    request: Request,
    opciones: OpcionesAccion,
    curso: CursoId,
    numero: NumeroLeccion,
    accion: IdAccion,
) -> Trabajo:
    config = config_peticion(request)
    try:
        plan = plan_accion(config, curso, numero, accion, opciones)
    except AccionNoDisponible as error:
        raise HTTPException(
            status_code=error.estado_http,
            detail=error.mensaje,
        ) from error
    return lanzar_plan(config, curso, numero, plan)


@router.get("/trabajos", response_model=list[Trabajo])
def obtener_trabajos(
    request: Request,
    limite: int = Query(default=20, ge=1, le=100),
) -> list[Trabajo]:
    config = config_peticion(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        return listar_trabajos(bd, limite)


@router.post("/trabajos/{id}/cancelar", response_model=Trabajo)
def cancelar_trabajo(
    request: Request,
    _peticion: PeticionCancelar,
    id: TrabajoId,
) -> Trabajo:
    config = config_peticion(request)
    trabajo = cancelar(config.bd_ruta, id)
    if trabajo is not None:
        return trabajo
    with closing(abrir_bd(config.bd_ruta)) as bd:
        existe = leer_trabajo(bd, id) is not None
    if not existe:
        raise HTTPException(status_code=404, detail="El trabajo no existe")
    raise HTTPException(
        status_code=409,
        detail="Ese trabajo no está en marcha",
    )
