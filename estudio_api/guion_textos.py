import copy
import hashlib
import json
import threading
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from estudio_api.escritura import escribir_atomico

_BLOQUEO_ESCRITURA_GUION = threading.RLock()


class ConflictoEscrituraGuion(Exception):
    pass


@contextmanager
def cerrojo_escritura_guion():
    """Serializa las escrituras del guion y de sus JSON derivados."""
    with _BLOQUEO_ESCRITURA_GUION:
        yield


def version_json(ruta: Path) -> tuple[str | None, bytes | None]:
    """Lee un JSON para una escritura optimista; ``None`` representa que no existe."""
    try:
        contenido = ruta.read_bytes()
    except FileNotFoundError:
        return None, None
    return hashlib.sha256(contenido).hexdigest(), contenido


def escribir_json_versionado(
    ruta: Path,
    datos: dict[str, Any],
    version_esperada: str | None,
) -> None:
    """Escribe JSON con copia inicial si no ha cambiado desde que se leyó."""
    version_actual, contenido_actual = version_json(ruta)
    if version_actual != version_esperada:
        raise ConflictoEscrituraGuion
    contenido = json.dumps(datos, ensure_ascii=False, indent=2) + "\n"
    if contenido_actual != contenido.encode("utf-8"):
        escribir_atomico(ruta, contenido)


class CambioEscena(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^E[0-9]{2}$")
    cues: list[str] | None = None
    puntos: list[str] | None = None


class CambioGancho(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    texto: str


class CambiosTextos(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(pattern=r"^[0-9a-f]{64}$")
    escenas: list[CambioEscena] = Field(default_factory=list, max_length=200)
    ganchos: list[CambioGancho] | None = Field(
        default=None,
        min_length=1,
        max_length=20,
    )


# Controles bidireccionales de incrustación (U+202A–U+202E) y de aislamiento
# (U+2066–U+2069). El resto de ``Cf`` pasa: el ZWJ U+200D forma emojis.
_BIDI_PROHIBIDOS = frozenset(
    chr(codigo) for codigo in (*range(0x202A, 0x202F), *range(0x2066, 0x206A))
)


def _caracter_prohibido(caracter: str) -> bool:
    return caracter in _BIDI_PROHIBIDOS or unicodedata.category(caracter) in {
        "Cc",
        "Cs",
    }


def _validar_texto(texto: str) -> str:
    texto = texto.strip()
    if not texto:
        raise ValueError("El texto no puede estar vacío")
    if len(texto.splitlines()) != 1 or any(
        _caracter_prohibido(caracter) for caracter in texto
    ):
        raise ValueError(
            "El texto no puede contener saltos de línea ni caracteres de control"
        )
    if len(texto) > 1000:
        raise ValueError("El texto no puede superar los 1000 caracteres")
    return texto


def _escena_por_id(guion: dict[str, Any], identificador: str) -> dict[str, Any]:
    escenas = guion.get("escenas")
    if not isinstance(escenas, list):
        raise ValueError(  # noqa: TRY004 - contrato público de aplicar_textos
            f"La escena {identificador} no existe"
        )
    escena = next(
        (
            candidata
            for candidata in escenas
            if isinstance(candidata, dict) and candidata.get("id") == identificador
        ),
        None,
    )
    if escena is None:
        raise ValueError(f"La escena {identificador} no existe")
    if escena.get("modo") not in {"voz", "camara"}:
        raise ValueError(f"La escena {identificador} no se puede editar")
    return escena


def _aplicar_cues(
    escena: dict[str, Any],
    identificador: str,
    textos: list[str],
) -> None:
    cues = escena.get("cues")
    if not isinstance(cues, list) or any(not isinstance(cue, dict) for cue in cues):
        raise ValueError(f"La escena {identificador} no tiene frases editables")
    if len(cues) != len(textos):
        raise ValueError(
            f"La escena {identificador} tiene {len(cues)} frases "
            f"y se han enviado {len(textos)}"
        )
    textos_validados = [_validar_texto(texto) for texto in textos]
    for cue, texto in zip(cues, textos_validados, strict=True):
        cue["texto"] = texto


def _aplicar_puntos(
    escena: dict[str, Any],
    identificador: str,
    textos: list[str],
) -> None:
    if "puntos" not in escena and not textos:
        # La web envía ``puntos: []`` para una escena sin puntos: sin cambios.
        return
    puntos = escena.get("puntos")
    if not isinstance(puntos, list) or any(
        not isinstance(punto, str) for punto in puntos
    ):
        raise ValueError(f"La escena {identificador} no tiene puntos editables")
    if len(puntos) != len(textos):
        raise ValueError(
            f"La escena {identificador} tiene {len(puntos)} puntos "
            f"y se han enviado {len(textos)}"
        )
    escena["puntos"] = [_validar_texto(texto) for texto in textos]


def _ganchos_validos(guion: dict[str, Any]) -> list[dict[str, Any]]:
    ganchos = guion.get("ganchos")
    if not isinstance(ganchos, list):
        return []
    return [
        gancho
        for gancho in ganchos
        if isinstance(gancho, dict)
        and isinstance(gancho.get("id"), str)
        and isinstance(gancho.get("texto"), str)
    ]


def _aplicar_ganchos(
    guion: dict[str, Any],
    cambios: list[CambioGancho],
) -> None:
    ganchos = _ganchos_validos(guion)
    ids_guion = [gancho["id"] for gancho in ganchos]
    if len(ids_guion) != len(set(ids_guion)):
        raise ValueError("Los ganchos del guion tienen ids repetidos")

    ids_cambios = [cambio.id for cambio in cambios]
    if len(ids_cambios) != len(set(ids_cambios)):
        raise ValueError("Los ganchos enviados tienen ids repetidos")
    if len(ids_cambios) != len(ids_guion) or set(ids_cambios) != set(ids_guion):
        raise ValueError("Hay que enviar todos los ganchos del guion una sola vez")

    textos = {cambio.id: _validar_texto(cambio.texto) for cambio in cambios}
    for gancho in ganchos:
        gancho["texto"] = textos[gancho["id"]]


def aplicar_textos(guion: dict[str, Any], cambios: CambiosTextos) -> dict[str, Any]:
    resultado = copy.deepcopy(guion)
    for cambio in cambios.escenas:
        escena = _escena_por_id(resultado, cambio.id)
        if cambio.cues is None and cambio.puntos is None:
            raise ValueError(f"La escena {cambio.id} no contiene textos para editar")
        if cambio.cues is not None:
            _aplicar_cues(escena, cambio.id, cambio.cues)
        if cambio.puntos is not None:
            if escena.get("modo") != "camara":
                raise ValueError(f"La escena {cambio.id} no tiene puntos editables")
            _aplicar_puntos(escena, cambio.id, cambio.puntos)
    if cambios.ganchos is not None:
        _aplicar_ganchos(resultado, cambios.ganchos)
    return resultado
