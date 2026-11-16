import os
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel


class Config(BaseModel):
    cursos_dir: Path
    estudio_dir: Path
    origen_web: str = "http://127.0.0.1:3000"
    token_escritura: str | None = None
    bd_ruta: Path = Path("datos/estudio.sqlite3")


def _valor_config(nombre: str, archivo_env: dict[str, str | None]) -> str | None:
    return os.environ.get(nombre) or archivo_env.get(nombre)


def _directorio_configurado(
    nombre: str,
    archivo_env: dict[str, str | None],
) -> Path:
    valor = _valor_config(nombre, archivo_env)
    if not valor:
        raise ValueError(f"Falta la variable obligatoria {nombre}")

    ruta = Path(valor).expanduser()
    if not ruta.exists():
        raise ValueError(f"{nombre} no existe: {ruta}")
    if not ruta.is_dir():
        raise ValueError(f"{nombre} no es un directorio: {ruta}")
    return ruta.resolve()


def cargar_config() -> Config:
    archivo_env = dict(dotenv_values(".env"))
    cursos_dir = _directorio_configurado("CURSOS_DIR", archivo_env)
    estudio_dir = _directorio_configurado("ESTUDIO_DIR", archivo_env)
    origen_web = _valor_config("ORIGEN_WEB", archivo_env) or "http://127.0.0.1:3000"
    token_escritura = _valor_config("ESTUDIO_TOKEN", archivo_env)
    bd_ruta = Path(
        _valor_config("BD_RUTA", archivo_env) or "datos/estudio.sqlite3"
    ).expanduser()
    return Config(
        cursos_dir=cursos_dir,
        estudio_dir=estudio_dir,
        origen_web=origen_web,
        token_escritura=token_escritura,
        bd_ruta=bd_ruta,
    )
