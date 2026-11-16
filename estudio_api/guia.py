import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

from estudio_api.config import Config
from estudio_api.escritura import escribir_atomico, reemplazar_atomico
from estudio_api.estado import REDES
from estudio_api.publicacion import Publicacion, Red, TextosRed
from estudio_api.rutas import ruta_segura

NOMBRES_RED: dict[Red, str] = {
    "youtube": "YouTube",
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "linkedin": "LinkedIn",
}


def _bloque_codigo(contenido: str) -> str:
    mayor = max((len(grupo) for grupo in re.findall(r"`+", contenido)), default=0)
    valla = "`" * max(3, mayor + 1)
    return f"{valla}\n{contenido}\n{valla}"


def _campo_bloque(partes: list[str], titulo: str, contenido: str | None) -> None:
    if contenido is None:
        return
    partes.extend((f"#### {titulo}", "", _bloque_codigo(contenido), ""))


def _es_nombre_relativo(valor: str) -> bool:
    if not valor or "\\" in valor:
        return False
    ruta = PurePosixPath(valor)
    return (
        not ruta.is_absolute()
        and all(parte not in {"", ".", ".."} for parte in ruta.parts)
        and not ruta.parts[0].endswith(":")
    )


def _red_markdown(red: Red, textos: TextosRed) -> list[str]:
    partes = [f"### {NOMBRES_RED[red]}", ""]
    if textos.titulos:
        partes.extend(("#### Títulos", ""))
        for indice, titulo in enumerate(textos.titulos):
            etiqueta = (
                f"{titulo} (recomendado)" if indice == 0 else f"{titulo} (alternativa)"
            )
            partes.extend((etiqueta, "", _bloque_codigo(titulo), ""))
    _campo_bloque(partes, "Descripción", textos.descripcion)
    if textos.etiquetas:
        _campo_bloque(partes, "Etiquetas", ", ".join(textos.etiquetas))
    _campo_bloque(partes, "Texto", textos.texto)
    _campo_bloque(partes, "Comentario fijado", textos.comentario_fijado)
    if textos.ajustes:
        partes.extend(("#### Ajustes", ""))
        partes.extend(f"- {ajuste}" for ajuste in textos.ajustes)
        partes.append("")
    if textos.video is not None and _es_nombre_relativo(textos.video):
        partes.extend(("#### Archivo de vídeo", "", f"`{textos.video}`", ""))
    if textos.notas is not None:
        partes.extend(("#### Notas", "", textos.notas, ""))
    return partes


def generar_guia(
    publicacion: Publicacion,
    curso_nombre: str,
    numero: int,
    portada_elegida: dict[str, str],
) -> str:
    partes = [f"# Publicar la lección {numero} de {curso_nombre}", ""]
    for identificador, pieza in publicacion.piezas.items():
        partes.extend(
            (f"## {pieza.titulo or identificador.replace('-', ' ').capitalize()}", "")
        )
        if pieza.video is not None and _es_nombre_relativo(pieza.video):
            partes.extend((f"- Archivo: `{pieza.video}`",))
        if (portada := portada_elegida.get(identificador)) and _es_nombre_relativo(
            portada
        ):
            partes.extend((f"- Portada: `{portada}`",))
        if pieza.fecha_propuesta is not None:
            partes.extend((f"- Fecha propuesta: {pieza.fecha_propuesta}",))
        if partes[-1] != "":
            partes.append("")
        for red in REDES:
            textos = pieza.redes.get(red)
            if textos is not None:
                partes.extend(_red_markdown(red, textos))

    if publicacion.notas is not None:
        partes.extend(("## Notas", "", publicacion.notas, ""))
    partes.extend(("## Después de publicar", ""))
    if publicacion.despues_de_publicar:
        partes.extend(f"- {tarea}" for tarea in publicacion.despues_de_publicar)
    else:
        partes.append("Nada pendiente.")
    return "\n".join(partes).rstrip() + "\n"


def _rutas_regeneracion(
    config: Config,
    carpeta: Path,
    numero: int,
) -> tuple[Path, Path, Path, Path] | None:
    try:
        relativa = carpeta.resolve().relative_to(config.cursos_dir.resolve())
        publicar = ruta_segura(config.cursos_dir, *relativa.parts, "publicar")
        markdown = ruta_segura(publicar, f"PUBLICAR-leccion-{numero}.md")
        html = ruta_segura(publicar, f"PUBLICAR-leccion-{numero}.html")
        script = ruta_segura(
            config.estudio_dir,
            "herramientas",
            "publicar",
            "md-a-html.py",
        )
    except OSError, ValueError:
        return None
    return publicar, markdown, html, script


def regenerar_guia(
    config: Config,
    carpeta: Path,
    numero: int,
    curso_nombre: str,
    publicacion: Publicacion,
    portadas: dict[str, str],
) -> str | None:
    rutas = _rutas_regeneracion(config, carpeta, numero)
    if rutas is None:
        return "No se ha podido regenerar la guía"
    publicar, markdown, html, script = rutas
    escribir_atomico(
        markdown,
        generar_guia(publicacion, curso_nombre, numero, portadas),
    )
    if not script.is_file():
        return "No se ha encontrado md-a-html.py; se ha actualizado solo el Markdown"

    descriptor, nombre_temporal = tempfile.mkstemp(
        dir=publicar,
        prefix=f".{html.name}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    temporal = Path(nombre_temporal)
    argumentos = [
        sys.executable,
        str(script),
        str(markdown),
        str(temporal),
    ]
    if portada := portadas.get("leccion"):
        argumentos.append(portada)
    try:
        subprocess.run(
            argumentos,
            check=True,
            shell=False,
            timeout=60,
            cwd=publicar,
        )
        reemplazar_atomico(html, temporal)
    except OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired:
        return "No se ha podido regenerar la guía HTML; el Markdown sí está actualizado"
    finally:
        temporal.unlink(missing_ok=True)
    return None
