import re
import stat
from collections.abc import Iterator
from pathlib import Path

from starlette.responses import Response, StreamingResponse

from estudio_api.config import Config
from estudio_api.rutas import ruta_segura

TAMANO_TROZO = 64 * 1024
PATRON_RANGE = re.compile(r"^bytes=([0-9]{0,18})-([0-9]{0,18})$")
TIPOS_MEDIO = {
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".mov": "video/quicktime",
    ".mp4": "video/mp4",
    ".png": "image/png",
    ".wav": "audio/wav",
}


def _resolver_ruta(config: Config, ruta_publica: str) -> Path | None:
    if not ruta_publica or ruta_publica.startswith("/") or "\\" in ruta_publica:
        return None

    partes = ruta_publica.split("/")
    if len(partes) < 2 or any(parte in {"", ".", ".."} for parte in partes):
        return None

    raices = {
        "cursos": config.cursos_dir,
        "estudio": config.estudio_dir,
    }
    raiz = raices.get(partes[0])
    if raiz is None:
        return None

    try:
        ruta = ruta_segura(raiz, *partes[1:])
        datos = ruta.stat()
    except (OSError, ValueError):
        return None
    if ruta.suffix.lower() not in TIPOS_MEDIO or not stat.S_ISREG(datos.st_mode):
        return None
    return ruta


def _rango_solicitado(cabecera: str, tamano: int) -> tuple[int, int] | None:
    coincidencia = PATRON_RANGE.fullmatch(cabecera)
    if coincidencia is None or tamano == 0:
        return None

    inicio_texto, fin_texto = coincidencia.groups()
    if not inicio_texto and not fin_texto:
        return None

    if not inicio_texto:
        longitud = int(fin_texto)
        if longitud <= 0:
            return None
        inicio = max(tamano - longitud, 0)
        return inicio, tamano - 1

    inicio = int(inicio_texto)
    if inicio >= tamano:
        return None
    if not fin_texto:
        return inicio, tamano - 1

    fin = int(fin_texto)
    if fin < inicio:
        return None
    return inicio, min(fin, tamano - 1)


def _leer_trozo(ruta: Path, inicio: int, longitud: int) -> Iterator[bytes]:
    with ruta.open("rb") as archivo:
        archivo.seek(inicio)
        restante = longitud
        while restante > 0:
            bloque = archivo.read(min(TAMANO_TROZO, restante))
            if not bloque:
                break
            restante -= len(bloque)
            yield bloque


def servir_medio(
    config: Config,
    ruta_publica: str,
    cabecera_range: str | None,
) -> Response:
    ruta = _resolver_ruta(config, ruta_publica)
    if ruta is None:
        return Response(status_code=404)

    try:
        tamano = ruta.stat().st_size
    except OSError:
        return Response(status_code=404)

    cabeceras = {"Accept-Ranges": "bytes"}
    if cabecera_range is None:
        inicio = 0
        longitud = tamano
        estado = 200
    else:
        rango = _rango_solicitado(cabecera_range, tamano)
        if rango is None:
            return Response(
                status_code=416,
                headers={
                    "Accept-Ranges": "bytes",
                    "Content-Range": f"bytes */{tamano}",
                },
            )
        inicio, fin = rango
        longitud = fin - inicio + 1
        estado = 206
        cabeceras["Content-Range"] = f"bytes {inicio}-{fin}/{tamano}"

    cabeceras["Content-Length"] = str(longitud)
    return StreamingResponse(
        _leer_trozo(ruta, inicio, longitud),
        status_code=estado,
        media_type=TIPOS_MEDIO[ruta.suffix.lower()],
        headers=cabeceras,
    )
