import hashlib
from contextlib import closing
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request, status
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from estudio_api.acciones import (
    ACCIONES_QUE_LEEN_LA_LECCION,
    SIN_GUION,
    AccionNoDisponible,
    OpcionesAccion,
    plan_accion,
)
from estudio_api.config import Config
from estudio_api.decisiones import abrir_bd
from estudio_api.guion_textos import (
    CambiosTextos,
    ConflictoEscrituraGuion,
    aplicar_textos,
    cerrojo_escritura_guion,
    escribir_json_versionado,
)
from estudio_api.lectura import datos_curso
from estudio_api.rutas_acciones import lanzar_plan
from estudio_api.rutas_api import (
    CursoId,
    NumeroLeccion,
    TrabajoId,
    config_peticion,
)
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
from estudio_api.trabajos import Trabajo, hay_trabajo_en_leccion, leer_trabajo

router = APIRouter(prefix="/api")
EscenaId = Annotated[str, Path(pattern=r"^E[0-9]{2}$")]
LECCION_OCUPADA = (
    "No se puede cambiar mientras se prepara esta lección. "
    "Espera a que termine el trabajo."
)


class PeticionPrevia(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _exigir_leccion_libre(config: Config, curso: str, numero: int) -> None:
    """409 si una herramienta está leyendo el guion o las tomas de la lección."""
    with closing(abrir_bd(config.bd_ruta)) as bd:
        ocupada = hay_trabajo_en_leccion(
            bd,
            curso,
            numero,
            ACCIONES_QUE_LEEN_LA_LECCION,
        )
    if ocupada:
        raise HTTPException(status_code=409, detail=LECCION_OCUPADA)


@router.get(
    "/cursos/{curso}/lecciones/{numero}/teleprompter",
    response_model=Teleprompter,
)
def obtener_teleprompter(
    request: Request,
    curso: CursoId,
    numero: NumeroLeccion,
) -> Teleprompter:
    config = config_peticion(request)
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
    config = config_peticion(request)
    conflicto = "El guion ha cambiado fuera de la app. Recarga antes de guardar."
    if not cambios.escenas and cambios.ganchos is None:
        raise HTTPException(status_code=422, detail="No hay cambios que guardar")
    with cerrojo_escritura_guion():
        _exigir_leccion_libre(config, curso, numero)
        leido = datos_curso(config, curso)
        datos_guion = leido[2].get(numero) if leido is not None else None
        if datos_guion is None:
            raise HTTPException(status_code=404, detail="La lección no existe")
        guion = datos_guion[2]
        ruta = datos_guion[3]
        version_inicial = hashlib.sha256(datos_guion[4]).hexdigest()
        if version_inicial != cambios.version:
            raise HTTPException(status_code=409, detail=conflicto)
        try:
            guion_actualizado = aplicar_textos(guion, cambios)
        except ValueError as error:
            mensaje = str(error)
            raise HTTPException(status_code=422, detail=mensaje) from error
        try:
            escribir_json_versionado(ruta, guion_actualizado, version_inicial)
        except (ConflictoEscrituraGuion, OSError) as error:
            raise HTTPException(status_code=409, detail=conflicto) from error
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
    config = config_peticion(request)
    # Antes de leer el cuerpo: no tiene sentido recibir la toma para nada.
    await run_in_threadpool(_exigir_leccion_libre, config, curso, numero)
    try:
        return await guardar_toma(
            config,
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
    config = config_peticion(request)
    try:
        plan = plan_accion(
            config,
            curso,
            numero,
            "previa-grabacion",
            OpcionesAccion(),
        )
    except AccionNoDisponible as error:
        if error.mensaje == SIN_GUION:
            # Contrato de la fase 4: la previa de una lección sin guion es 404.
            raise HTTPException(
                status_code=404,
                detail="La lección no existe",
            ) from error
        raise HTTPException(
            status_code=error.estado_http,
            detail=error.mensaje,
        ) from error
    return lanzar_plan(config, curso, numero, plan)


@router.get("/trabajos/{id}", response_model=Trabajo)
def obtener_trabajo(request: Request, id: TrabajoId) -> Trabajo:
    config = config_peticion(request)
    with closing(abrir_bd(config.bd_ruta)) as bd:
        trabajo = leer_trabajo(bd, id)
    if trabajo is None:
        raise HTTPException(status_code=404, detail="El trabajo no existe")
    return trabajo
