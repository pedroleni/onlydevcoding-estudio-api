import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

TOKEN = "token-de-prueba-con-32-caracteres!"

# Ahí vive la base de datos real del autor. Se consulta en cada llamada para
# que la guarda se pueda probar con un ``datos/`` falso.
DATOS_REALES = Path(__file__).resolve().parent.parent / "datos"


class BaseRealProtegida(RuntimeError):
    """Un test ha intentado abrir una base de ``datos/``."""


def _ruta_de_base(base: object) -> Path | None:
    if not isinstance(base, (str, bytes, os.PathLike)):
        return None
    texto = os.fsdecode(base)
    if texto.startswith("file:"):
        texto = texto.removeprefix("file:").split("?", 1)[0]
    if not texto or texto == ":memory:":
        return None
    return Path(texto)


def conexion_vigilada(
    conectar_real: Callable[..., Any],
) -> Callable[..., Any]:
    """Envuelve ``sqlite3.connect`` para que falle antes de abrir ``datos/``."""

    def conectar(base: object, *args: Any, **kwargs: Any) -> Any:
        ruta = _ruta_de_base(base)
        if ruta is not None and ruta.resolve().is_relative_to(DATOS_REALES.resolve()):
            raise BaseRealProtegida(
                "Un test ha intentado abrir una base de datos/ "
                "(la base de datos real del autor)"
            )
        return conectar_real(base, *args, **kwargs)

    return conectar
