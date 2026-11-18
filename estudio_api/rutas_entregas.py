from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request, Response, status
from starlette.requests import ClientDisconnect

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
from estudio_api.rutas_api import CursoId, NumeroLeccion, config_peticion

router = APIRouter(prefix="/api")
ArchivoRuta = Annotated[str, Path(min_length=1)]

NOMBRE_NO_ADMITIDO = (
    "Ese nombre de archivo no se admite: renómbralo con letras sin acentos, "
    "números, espacios, guiones o puntos"
)


def _error_nombre() -> HTTPException:
    return HTTPException(status_code=422, detail=NOMBRE_NO_ADMITIDO)


@router.get(
    "/cursos/{curso}/lecciones/{numero}/entregas",
    response_model=list[ArchivoEntregado],
)
def obtener_entregas(
    request: Request,
    curso: CursoId,
    numero: NumeroLeccion,
) -> list[ArchivoEntregado]:
    try:
        entregas = listar_entregas(config_peticion(request), curso, numero)
    except OSError as error:
        raise HTTPException(
            status_code=503,
            detail="No se han podido leer las tomas entregadas",
        ) from error
    if entregas is None:
        raise HTTPException(status_code=404, detail="La lección no existe")
    return entregas


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
    try:
        return await guardar_entrega(
            config_peticion(request),
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
    try:
        borrada = borrar_entrega(config_peticion(request), curso, numero, archivo)
    except NombreEntregaInvalido as error:
        raise _error_nombre() from error
    except OSError as error:
        raise HTTPException(
            status_code=503,
            detail="No se ha podido borrar la toma",
        ) from error
    if not borrada:
        try:
            leccion = listar_entregas(config_peticion(request), curso, numero)
        except OSError as error:
            raise HTTPException(
                status_code=503,
                detail="No se ha podido borrar la toma",
            ) from error
        if leccion is None:
            raise HTTPException(status_code=404, detail="La lección no existe")
        raise HTTPException(status_code=404, detail="La toma entregada no existe")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
