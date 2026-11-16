import os
import shutil
import tempfile
from pathlib import Path


def _crear_copia_inicial(ruta: Path) -> None:
    copia = ruta.with_name(f"{ruta.name}.antes-de-editar")
    if not ruta.exists() or copia.exists():
        return

    try:
        with ruta.open("rb") as origen, copia.open("xb") as destino:
            shutil.copyfileobj(origen, destino)
    except FileExistsError:
        return
    except BaseException:
        copia.unlink(missing_ok=True)
        raise


def escribir_atomico(ruta: Path, contenido: str) -> None:
    _crear_copia_inicial(ruta)

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

        os.replace(temporal, ruta)
        temporal = None
    finally:
        if temporal is not None:
            temporal.unlink(missing_ok=True)
