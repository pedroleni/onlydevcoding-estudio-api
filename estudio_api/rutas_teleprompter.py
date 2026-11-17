import shutil
from contextlib import closing
from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Path, Request, status
from pydantic import BaseModel, ConfigDict
from starlette.responses import Response

from estudio_api.config import Config
from estudio_api.decisiones import abrir_bd
from estudio_api.rutas_api import CursoId, NumeroLeccion
from estudio_api.teleprompter import (
    Teleprompter,
    comando_previa,
    leer_teleprompter,
    ruta_montaje,
    rutas_previa,
)
from estudio_api.tomas import (
    EscenaNoEsVoz,
    EscenaNoExiste,
    LeccionSinGuion,
    TomaGuardada,
    WavInvalido,
    guardar_toma,
)
from estudio_api.trabajos import (
    Trabajo,
    TrabajoEnMarcha,
    lanzar,
    leer_trabajo,
)

router = APIRouter(prefix="/api")
TrabajoId = Annotated[int, Path(ge=1, le=2**63 - 1)]
EscenaId = Annotated[str, Path(pattern=r"^E[0-9]{2}$")]


class PeticionPrevia(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _config(request: Request) -> Config:
    return cast(Config, request.app.state.config)


@router.get(
    "/cursos/{curso}/lecciones/{numero}/teleprompter",
    response_model=Teleprompter,
)
def obtener_teleprompter(
    request: Request,
    curso: CursoId,
    numero: NumeroLeccion,
) -> Teleprompter | Response:
    config = _config(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        teleprompter = leer_teleprompter(config, bd, curso, numero)
    if teleprompter is None:
        return Response(status_code=404)
    return teleprompter


@router.put(
    "/cursos/{curso}/lecciones/{numero}/grabaciones/{escena}",
    response_model=TomaGuardada,
    status_code=status.HTTP_201_CREATED,
)
async def subir_toma_voz(
    request: Request,
    curso: CursoId,
    numero: NumeroLeccion,
    escena: EscenaId,
) -> TomaGuardada:
    if request.headers.get("content-type") != "audio/wav":
        raise HTTPException(
            status_code=415,
            detail="La toma tiene que ser un WAV (audio/wav)",
        )
    longitud = int(request.headers["content-length"])
    try:
        return await guardar_toma(
            _config(request),
            curso,
            numero,
            escena,
            request.stream(),
            longitud,
        )
    except LeccionSinGuion as error:
        raise HTTPException(
            status_code=404,
            detail="La lección no existe",
        ) from error
    except EscenaNoExiste as error:
        raise HTTPException(
            status_code=404,
            detail="La escena no existe en el guion",
        ) from error
    except EscenaNoEsVoz as error:
        raise HTTPException(
            status_code=422,
            detail="Esa escena no se graba con voz",
        ) from error
    except WavInvalido as error:
        raise HTTPException(
            status_code=422,
            detail="El archivo no es un WAV válido",
        ) from error
    except (OSError, ValueError) as error:
        raise HTTPException(
            status_code=503,
            detail="No se ha podido guardar la toma",
        ) from error


@router.post(
    "/cursos/{curso}/lecciones/{numero}/previa-grabacion",
    response_model=Trabajo,
    status_code=status.HTTP_202_ACCEPTED,
)
def generar_previa_grabacion(
    request: Request,
    _peticion: PeticionPrevia,
    curso: CursoId,
    numero: NumeroLeccion,
) -> Trabajo:
    config = _config(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        teleprompter = leer_teleprompter(config, bd, curso, numero)
    if teleprompter is None:
        raise HTTPException(status_code=404, detail="La lección no existe")

    montaje = ruta_montaje(config, teleprompter.guion)
    if montaje is None or not montaje.is_file() or teleprompter.montaje is None:
        raise HTTPException(
            status_code=409,
            detail="Esta lección aún no tiene montaje",
        )
    npx = shutil.which("npx")
    if npx is None:
        raise HTTPException(
            status_code=503,
            detail="No se encuentra npx en el PATH de la API",
        )
    rutas = rutas_previa(config, teleprompter.guion)
    if rutas is None:
        raise HTTPException(status_code=404, detail="La ruta de la previa no es válida")
    temporal, destino = rutas
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise HTTPException(
            status_code=503,
            detail="No se puede preparar la carpeta de la vista previa",
        ) from error
    try:
        return lanzar(
            config.bd_ruta,
            "previa-grabacion",
            curso,
            numero,
            comando_previa(npx, temporal, teleprompter.guion),
            config.estudio_dir,
            temporal,
            destino,
        )
    except TrabajoEnMarcha as error:
        raise HTTPException(
            status_code=409,
            detail="Ya hay un trabajo en marcha",
        ) from error


@router.get("/trabajos/{id}", response_model=Trabajo)
def obtener_trabajo(request: Request, id: TrabajoId) -> Trabajo:
    config = _config(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        trabajo = leer_trabajo(bd, id)
    if trabajo is None:
        raise HTTPException(status_code=404, detail="El trabajo no existe")
    return trabajo
