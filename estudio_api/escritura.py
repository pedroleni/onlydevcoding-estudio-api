import os
import shutil
import tempfile
from pathlib import Path


def _crear_copia_inicial(ruta: Path) -> None:
    copia = ruta.with_name(f"{ruta.name}.antes-de-editar")
    if not ruta.exists() or copia.exists():
        return

    copia_creada = False
    try:
        with ruta.open("rb") as origen:
            try:
                destino = copia.open("xb")
            except FileExistsError:
                return
            copia_creada = True
            with destino:
                shutil.copyfileobj(origen, destino)
    except BaseException:
        if copia_creada:
            copia.unlink(missing_ok=True)
        raise


def _sincronizar_directorio(ruta: Path) -> None:
    descriptor = os.open(ruta, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def reemplazar_atomico(ruta: Path, temporal: Path) -> None:
    _crear_copia_inicial(ruta)
    if ruta.exists():
        shutil.copymode(ruta, temporal)
    with temporal.open("rb") as archivo:
        os.fsync(archivo.fileno())
    os.replace(temporal, ruta)
    _sincronizar_directorio(ruta.parent)


def escribir_atomico(ruta: Path, contenido: str) -> None:
    temporal: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=ruta.parent,
            prefix=f".{ruta.name}.",
            suffix=".tmp",
            delete=False,
        ) as archivo:
            temporal = Path(archivo.name)
            archivo.write(contenido)
            archivo.flush()
            os.fsync(archivo.fileno())

        reemplazar_atomico(ruta, temporal)
        temporal = None
    finally:
        if temporal is not None:
            temporal.unlink(missing_ok=True)
