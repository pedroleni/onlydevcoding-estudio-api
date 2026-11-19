from contextlib import closing
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from estudio_api.acciones import ACCIONES_QUE_LEEN_LAS_ENTREGAS
from estudio_api.camara import TomasCamara, leer_camara
from estudio_api.colocar import (
    Asignacion,
    ColocacionNoValida,
    ResultadoColocar,
    colocar_tomas,
)
from estudio_api.config import Config
from estudio_api.decisiones import abrir_bd
from estudio_api.entregas import (
    ArchivoEntregado,
    EntregaExistente,
    EntregaInvalida,
    LeccionNoExiste,
    NombreEntregaInvalido,
    borrar_entrega,
    guardar_entrega,
    listar_entregas,
)
from estudio_api.lectura import _leer_json, datos_curso
from estudio_api.propuesta import Propuesta, escenas_camara, leer_propuesta
from estudio_api.rutas import ruta_segura
from estudio_api.rutas_api import (
    CursoId,
    NumeroLeccion,
    config_peticion,
    exigir_leccion_libre,
    http_de,
)

router = APIRouter(prefix="/api")
ArchivoRuta = Annotated[str, Path(min_length=1)]

NOMBRE_NO_ADMITIDO = (
    "Ese nombre de archivo no se admite: renómbralo con letras sin acentos, "
    "números, espacios, guiones o puntos"
)


class DestinoCamara(BaseModel):
    id: str
    titulo: str
    tiene_toma: bool


class DestinoGancho(BaseModel):
    id: str
    titulo: str
    entregado: bool


class Destinos(BaseModel):
    camara: list[DestinoCamara] = Field(default_factory=list)
    ganchos: list[DestinoGancho] = Field(default_factory=list)


class Entregas(BaseModel):
    archivos: list[ArchivoEntregado] = Field(default_factory=list)
    propuesta: Propuesta | None = None
    destinos: Destinos = Field(default_factory=Destinos)


class PeticionColocar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asignaciones: list[Asignacion] = Field(max_length=200)


def _destinos(
    config: Config,
    numero: int,
    *,
    datos: Any,
) -> Destinos:
    leido = datos
    datos_guion = leido[2].get(numero) if leido is not None else None
    if datos_guion is None:
        return Destinos()
    guion = datos_guion[2]
    identificador_guion = datos_guion[3].stem
    entregados: set[str] = set()
    try:
        shorts = _leer_json(
            ruta_segura(
                config.estudio_dir,
                "shorts",
                f"l{numero}",
                "shorts.json",
            )
        )
    except ValueError:
        shorts = None
    if shorts is not None and shorts.get("leccion") == identificador_guion:
        ganchos_entregados = shorts.get("ganchosEntregados")
        if isinstance(ganchos_entregados, dict):
            entregados = {
                identificador
                for identificador in ganchos_entregados
                if isinstance(identificador, str)
            }

    camara: list[DestinoCamara] = []
    for identificador, escena in escenas_camara(guion):
        titulo = escena.get("titulo")
        camara.append(
            DestinoCamara(
                id=identificador,
                titulo=titulo if isinstance(titulo, str) else identificador,
                tiene_toma=isinstance(escena.get("toma"), dict),
            )
        )

    ganchos: list[DestinoGancho] = []
    datos_ganchos = guion.get("ganchos")
    if isinstance(datos_ganchos, list):
        for gancho in datos_ganchos:
            if not isinstance(gancho, dict):
                continue
            identificador = gancho.get("id")
            if not isinstance(identificador, str):
                continue
            titulo = gancho.get("titulo")
            if not isinstance(titulo, str):
                titulo = gancho.get("texto")
            ganchos.append(
                DestinoGancho(
                    id=identificador,
                    titulo=titulo if isinstance(titulo, str) else identificador,
                    entregado=identificador in entregados,
                )
            )
    return Destinos(camara=camara, ganchos=ganchos)


def _error_nombre() -> HTTPException:
    return HTTPException(status_code=422, detail=NOMBRE_NO_ADMITIDO)


@router.get(
    "/cursos/{curso}/lecciones/{numero}/entregas",
    response_model=Entregas,
)
def obtener_entregas(
    request: Request,
    curso: CursoId,
    numero: NumeroLeccion,
) -> Entregas:
    config = config_peticion(request)
    try:
        datos = datos_curso(config, curso)
        entregas = listar_entregas(config, curso, numero, datos=datos)
        propuesta = leer_propuesta(config, curso, numero, datos=datos)
        destinos = _destinos(config, numero, datos=datos)
    except (OSError, ValueError) as error:
        raise HTTPException(
            status_code=503,
            detail="No se han podido leer las tomas entregadas",
        ) from error
    if entregas is None:
        raise HTTPException(status_code=404, detail="La lección no existe")
    return Entregas(archivos=entregas, propuesta=propuesta, destinos=destinos)


@router.get(
    "/cursos/{curso}/lecciones/{numero}/camara",
    response_model=TomasCamara,
)
def obtener_camara(
    request: Request,
    curso: CursoId,
    numero: NumeroLeccion,
) -> TomasCamara:
    try:
        camara = leer_camara(config_peticion(request), curso, numero)
    except OSError as error:
        raise HTTPException(
            status_code=503,
            detail="No se han podido leer las tomas de la lección",
        ) from error
    if camara is None:
        raise HTTPException(status_code=404, detail="La lección no existe")
    return camara


@router.post(
    "/cursos/{curso}/lecciones/{numero}/entregas/colocar",
    response_model=ResultadoColocar,
)
def colocar_entregas(
    request: Request,
    peticion: PeticionColocar,
    curso: CursoId,
    numero: NumeroLeccion,
) -> ResultadoColocar:
    config = config_peticion(request)
    try:
        with closing(abrir_bd(config.bd_ruta)) as bd:
            return colocar_tomas(
                config,
                bd,
                curso,
                numero,
                peticion.asignaciones,
            )
    except ColocacionNoValida as error:
        raise http_de(error) from error


@router.put(
    "/cursos/{curso}/lecciones/{numero}/entregas/{archivo:path}",
    response_model=ArchivoEntregado,
    status_code=status.HTTP_201_CREATED,
)
async def subir_entrega(
    request: Request,
    curso: CursoId,
    numero: NumeroLeccion,
    archivo: ArchivoRuta,
) -> ArchivoEntregado:
    tipo_medio = request.headers.get("content-type", "").partition(";")[0]
    if tipo_medio.strip().casefold() not in {"video/quicktime", "video/mp4"}:
        raise HTTPException(
            status_code=415,
            detail="La toma tiene que ser un vídeo MOV o MP4",
        )
    longitud = int(request.headers["content-length"])
    config = config_peticion(request)
    # Antes de leer el cuerpo: ``identificar-tomas`` está leyendo las entregas.
    await run_in_threadpool(
        exigir_leccion_libre, config, curso, numero, ACCIONES_QUE_LEEN_LAS_ENTREGAS
    )
    try:
        return await guardar_entrega(
            config,
            curso,
            numero,
            archivo,
            request.stream(),
            longitud,
        )
    except NombreEntregaInvalido as error:
        raise _error_nombre() from error
    except LeccionNoExiste as error:
        raise HTTPException(status_code=404, detail="La lección no existe") from error
    except EntregaExistente as error:
        raise HTTPException(
            status_code=409,
            detail="Ya hay una toma con ese nombre",
        ) from error
    except EntregaInvalida as error:
        raise HTTPException(
            status_code=422,
            detail="El archivo no es un vídeo MOV o MP4",
        ) from error
    except ClientDisconnect:
        raise HTTPException(status_code=400, detail="La subida se ha cortado") from None
    except (OSError, ValueError) as error:
        raise HTTPException(
            status_code=503,
            detail="No se ha podido guardar la toma",
        ) from error


@router.delete(
    "/cursos/{curso}/lecciones/{numero}/entregas/{archivo:path}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def eliminar_entrega(
    request: Request,
    curso: CursoId,
    numero: NumeroLeccion,
    archivo: ArchivoRuta,
) -> Response:
    config = config_peticion(request)
    exigir_leccion_libre(config, curso, numero, ACCIONES_QUE_LEEN_LAS_ENTREGAS)
    try:
        borrada = borrar_entrega(config, curso, numero, archivo)
    except NombreEntregaInvalido as error:
        raise _error_nombre() from error
    except (OSError, ValueError) as error:
        raise HTTPException(
            status_code=503,
            detail="No se ha podido borrar la toma",
        ) from error
    if not borrada:
        try:
            leccion = listar_entregas(config, curso, numero)
        except (OSError, ValueError) as error:
            raise HTTPException(
                status_code=503,
                detail="No se ha podido borrar la toma",
            ) from error
        if leccion is None:
            raise HTTPException(status_code=404, detail="La lección no existe")
        raise HTTPException(status_code=404, detail="La toma entregada no existe")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
