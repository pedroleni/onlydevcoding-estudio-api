from pathlib import Path


def ruta_segura(raiz: Path, *partes: str) -> Path:
    """Resuelve una ruta y garantiza que permanece dentro de ``raiz``."""
    for parte in partes:
        fragmento = Path(parte)
        if fragmento.is_absolute() or ".." in fragmento.parts:
            raise ValueError("La ruta contiene un segmento no permitido")

    raiz_resuelta = raiz.resolve()
    candidata = raiz_resuelta.joinpath(*partes).resolve()
    if not candidata.is_relative_to(raiz_resuelta):
        raise ValueError("La ruta queda fuera de la raíz permitida")
    return candidata
