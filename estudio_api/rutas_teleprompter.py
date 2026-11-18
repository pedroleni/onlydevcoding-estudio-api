import hashlib
import json
import threading
from contextlib import closing
from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Path, Request, status
from pydantic import BaseModel, ConfigDict
from starlette.requests import ClientDisconnect

from estudio_api.acciones import AccionNoDisponible, OpcionesAccion, plan_accion
from estudio_api.config import Config
from estudio_api.decisiones import abrir_bd
from estudio_api.escritura import escribir_atomico
from estudio_api.guion_textos import CambiosTextos, aplicar_textos
from estudio_api.lectura import datos_curso
from estudio_api.rutas_acciones import lanzar_plan
from estudio_api.rutas_api import CursoId, NumeroLeccion
from estudio_api.teleprompter import (
    Teleprompter,
    leer_teleprompter,
)
from estudio_api.tomas import (
    EscenaNoEsVoz,
    EscenaNoExiste,
    LeccionSinGuion,
    TomaGuardada,
    WavInvalido,
    guardar_toma,
)
from estudio_api.trabajos import Trabajo, leer_trabajo

router = APIRouter(prefix="/api")
_BLOQUEO_TEXTOS = threading.Lock()
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
) -> Teleprompter:
    config = _config(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        teleprompter = leer_teleprompter(config, bd, curso, numero)
    if teleprompter is None:
        raise HTTPException(
            status_code=404,
            detail="La lección no existe o no tiene guion",
        )
    return teleprompter


@router.put(
    "/cursos/{curso}/lecciones/{numero}/guion/textos",
    response_model=Teleprompter,
)
def guardar_textos_guion(
    request: Request,
    cambios: CambiosTextos,
    curso: CursoId,
    numero: NumeroLeccion,
) -> Teleprompter:
    config = _config(request)
    conflicto = "El guion ha cambiado fuera de la app. Recarga antes de guardar."
    if not cambios.escenas and cambios.ganchos is None:
        raise HTTPException(status_code=422, detail="No hay cambios que guardar")
    with _BLOQUEO_TEXTOS:
        leido = datos_curso(config, curso)
        datos_guion = leido[2].get(numero) if leido is not None else None
        if datos_guion is None:
            raise HTTPException(status_code=404, detail="La lección no existe")
        guion = datos_guion[2]
        ruta = datos_guion[3]
        contenido_inicial = datos_guion[4]
        version_inicial = hashlib.sha256(contenido_inicial).hexdigest()
        if version_inicial != cambios.version:
            raise HTTPException(status_code=409, detail=conflicto)
        try:
            guion_actualizado = aplicar_textos(guion, cambios)
        except ValueError as error:
            mensaje = str(error)
            raise HTTPException(status_code=422, detail=mensaje) from error
        try:
            contenido_actual = ruta.read_bytes()
        except OSError as error:
            raise HTTPException(status_code=409, detail=conflicto) from error
        if hashlib.sha256(contenido_actual).hexdigest() != version_inicial:
            raise HTTPException(status_code=409, detail=conflicto)
        contenido = json.dumps(guion_actualizado, ensure_ascii=False, indent=2) + "\n"
        escribir_atomico(ruta, contenido)
        with closing(abrir_bd(config.bd_ruta)) as bd:
            teleprompter = leer_teleprompter(config, bd, curso, numero)
        if teleprompter is None:
            raise HTTPException(status_code=404, detail="La lección no existe")
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
    tipo_medio = request.headers.get("content-type", "").partition(";")[0]
    if tipo_medio.strip().casefold() != "audio/wav":
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
    except ClientDisconnect:
        raise HTTPException(
            status_code=400,
            detail="La subida se ha cortado",
        ) from None
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
    try:
        plan = plan_accion(
            config,
            curso,
            numero,
            "previa-grabacion",
            OpcionesAccion(),
        )
    except AccionNoDisponible as error:
        raise HTTPException(
            status_code=error.estado_http,
            detail=error.mensaje,
        ) from error
    return lanzar_plan(config, curso, numero, plan)


@router.get("/trabajos/{id}", response_model=Trabajo)
def obtener_trabajo(request: Request, id: TrabajoId) -> Trabajo:
    config = _config(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        trabajo = leer_trabajo(bd, id)
    if trabajo is None:
        raise HTTPException(status_code=404, detail="El trabajo no existe")
    return trabajo
