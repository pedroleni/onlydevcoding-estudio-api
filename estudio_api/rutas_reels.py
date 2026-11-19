from contextlib import closing
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request
from pydantic import BaseModel, ConfigDict

from estudio_api.decisiones import abrir_bd
from estudio_api.reels import (
    ReelsCurso,
    Temario,
    gancho_existe,
    guardar_gancho_grabado,
    leer_reels,
    leer_temario,
)
from estudio_api.rutas_api import CursoId, NumeroLeccion, config_peticion

router = APIRouter(prefix="/api")
GanchoId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,20}$")]


class CambioGrabado(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grabado: bool


@router.get("/cursos/{curso}/reels", response_model=ReelsCurso)
def reels_del_curso(request: Request, curso: CursoId) -> ReelsCurso:
    config = config_peticion(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        reels = leer_reels(config, bd, curso)
    if reels is None:
        raise HTTPException(status_code=404, detail="El curso no existe")
    return reels


@router.put(
    "/cursos/{curso}/lecciones/{numero}/ganchos/{gancho}/grabado",
    response_model=ReelsCurso,
)
def marcar_grabado(
    request: Request,
    curso: CursoId,
    numero: NumeroLeccion,
    gancho: GanchoId,
    cambio: CambioGrabado,
) -> ReelsCurso:
    config = config_peticion(request)
    if not gancho_existe(config, curso, numero, gancho):
        raise HTTPException(status_code=404, detail="El gancho no existe")
    with closing(abrir_bd(config.bd_ruta)) as bd:
        guardar_gancho_grabado(bd, curso, numero, gancho, cambio.grabado)
        reels = leer_reels(config, bd, curso)
    if reels is None:
        raise HTTPException(status_code=404, detail="El curso no existe")
    return reels


@router.get("/cursos/{curso}/temario", response_model=Temario)
def temario_del_curso(request: Request, curso: CursoId) -> Temario:
    temario = leer_temario(config_peticion(request), curso)
    if temario is None:
        raise HTTPException(status_code=404, detail="El curso no existe")
    return temario
