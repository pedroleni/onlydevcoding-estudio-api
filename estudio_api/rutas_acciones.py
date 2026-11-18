from contextlib import closing
from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Path, Query, Request, status
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
from estudio_api.rutas_api import CursoId, NumeroLeccion
from estudio_api.trabajos import (
    PlanTrabajo,
    Trabajo,
    TrabajoEnMarcha,
    cancelar,
    lanzar,
    listar_trabajos,
)

router = APIRouter(prefix="/api")
TrabajoId = Annotated[int, Path(ge=1, le=2**63 - 1)]


class PeticionCancelar(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _config(request: Request) -> Config:
    return cast(Config, request.app.state.config)


def preparar_carpeta_resultado(config: Config, plan: PlanTrabajo) -> None:
    if plan.destino is None:
        return
    raiz = (
        config.estudio_dir.resolve()
        if plan.accion == "previa-grabacion"
        else config.cursos_dir.resolve()
    )
    try:
        plan.destino.parent.resolve().relative_to(raiz)
        plan.destino.parent.mkdir(parents=True, exist_ok=True)
        plan.destino.parent.resolve().relative_to(raiz)
    except (OSError, ValueError) as error:
        mensaje = (
            "No se puede preparar la carpeta de la vista previa"
            if plan.accion == "previa-grabacion"
            else "No se puede preparar la carpeta del resultado"
        )
        raise HTTPException(status_code=503, detail=mensaje) from error


def lanzar_plan(
    config: Config,
    curso: str,
    numero: int,
    plan: PlanTrabajo,
) -> Trabajo:
    preparar_carpeta_resultado(config, plan)
    try:
        return lanzar(config.bd_ruta, curso, numero, plan)
    except TrabajoEnMarcha as error:
        raise HTTPException(
            status_code=409,
            detail="Ya hay un trabajo en marcha",
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
    config = _config(request)
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
    config = _config(request)
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
    config = _config(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        return listar_trabajos(bd, limite)


@router.post("/trabajos/{id}/cancelar", response_model=Trabajo)
def cancelar_trabajo(
    request: Request,
    _peticion: PeticionCancelar,
    id: TrabajoId,
) -> Trabajo:
    trabajo = cancelar(_config(request).bd_ruta, id)
    if trabajo is None:
        raise HTTPException(
            status_code=409,
            detail="Ese trabajo no está en marcha",
        )
    return trabajo
