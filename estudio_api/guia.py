import os
import re
import signal
import subprocess
import sys
import tempfile
from contextlib import suppress
from pathlib import Path, PurePosixPath

from estudio_api.config import Config
from estudio_api.escritura import escribir_atomico, reemplazar_atomico
from estudio_api.estado import REDES
from estudio_api.publicacion import (
    Publicacion,
    Red,
    TextosRed,
    _raiz_publicar,
    clave_pieza,
    ruta_escritura_segura,
)
from estudio_api.rutas import ruta_segura

NOMBRES_RED: dict[Red, str] = {
    "youtube": "YouTube",
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "linkedin": "LinkedIn",
}
TIMEOUT_CONVERSOR_S = 60
TIMEOUT_RECOGIDA_S = 5
AVISO_HTML = "No se ha podido regenerar la guía HTML"


def _bloque_codigo(contenido: str) -> str:
    mayor = max((len(grupo) for grupo in re.findall(r"`+", contenido)), default=0)
    valla = "`" * max(3, mayor + 1)
    return f"{valla}\n{contenido}\n{valla}"


def _campo_bloque(partes: list[str], titulo: str, contenido: str | None) -> None:
    if contenido is None:
        return
    partes.extend((f"#### {titulo}", "", _bloque_codigo(contenido), ""))


def _escapar_inicio_markdown(texto: str) -> str:
    if not texto:
        return texto
    if texto[0] in "`#|->":
        return f"\\{texto}"
    coincidencia = re.match(r"^([0-9]+)\.", texto)
    if coincidencia is not None:
        fin_numero = len(coincidencia.group(1))
        return f"{texto[:fin_numero]}\\{texto[fin_numero:]}"
    return texto


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
            titulo_seguro = _escapar_inicio_markdown(titulo)
            etiqueta = (
                f"{titulo_seguro} (recomendado)"
                if indice == 0
                else f"{titulo_seguro} (alternativa)"
            )
            partes.extend((etiqueta, "", _bloque_codigo(titulo), ""))
    _campo_bloque(partes, "Descripción", textos.descripcion)
    if textos.etiquetas:
        _campo_bloque(partes, "Etiquetas", ", ".join(textos.etiquetas))
    _campo_bloque(partes, "Texto", textos.texto)
    _campo_bloque(partes, "Comentario fijado", textos.comentario_fijado)
    if textos.ajustes:
        partes.extend(("#### Ajustes", ""))
        partes.extend(
            f"- {_escapar_inicio_markdown(ajuste)}" for ajuste in textos.ajustes
        )
        partes.append("")
    if textos.video is not None and _es_nombre_relativo(textos.video):
        partes.extend(("#### Archivo de vídeo", "", f"`{textos.video}`", ""))
    _campo_bloque(partes, "Notas", textos.notas)
    return partes


def generar_guia(
    publicacion: Publicacion,
    curso_nombre: str,
    numero: int,
    portada_elegida: dict[str, str],
    titulos_piezas: dict[str, str] | None = None,
) -> str:
    titulos_piezas = titulos_piezas or {}
    partes = [
        (f"# Publicar la lección {numero} de {_escapar_inicio_markdown(curso_nombre)}"),
        "",
    ]
    for identificador in sorted(publicacion.piezas, key=clave_pieza):
        pieza = publicacion.piezas[identificador]
        titulo = (
            pieza.titulo
            or titulos_piezas.get(identificador)
            or identificador.replace("-", " ").capitalize()
        )
        partes.extend((f"## {_escapar_inicio_markdown(titulo)}", ""))
        if pieza.video is not None and _es_nombre_relativo(pieza.video):
            partes.extend((f"- Archivo: `{pieza.video}`",))
        if (portada := portada_elegida.get(identificador)) and _es_nombre_relativo(
            portada
        ):
            partes.extend((f"- Portada: `{portada}`",))
        if pieza.fecha_propuesta is not None:
            partes.extend(
                (
                    (
                        "- Fecha propuesta: "
                        f"{_escapar_inicio_markdown(pieza.fecha_propuesta)}"
                    ),
                )
            )
        if partes[-1] != "":
            partes.append("")
        for red in REDES:
            textos = pieza.redes.get(red)
            if textos is not None:
                partes.extend(_red_markdown(red, textos))

    if publicacion.notas is not None:
        partes.extend(("## Notas", "", _bloque_codigo(publicacion.notas), ""))
    partes.extend(("## Después de publicar", ""))
    if publicacion.despues_de_publicar:
        partes.extend(
            f"- {_escapar_inicio_markdown(tarea)}"
            for tarea in publicacion.despues_de_publicar
        )
    else:
        partes.append("Nada pendiente.")
    return "\n".join(partes).rstrip() + "\n"


def rutas_regeneracion(
    config: Config,
    carpeta: Path,
    numero: int,
) -> tuple[Path, Path, Path, Path] | None:
    try:
        publicar = _raiz_publicar(config, carpeta)
        if publicar is None:
            return None
        markdown = ruta_escritura_segura(publicar, f"PUBLICAR-leccion-{numero}.md")
        html = ruta_escritura_segura(publicar, f"PUBLICAR-leccion-{numero}.html")
        if markdown is None or html is None:
            return None
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
    titulos_piezas: dict[str, str] | None = None,
) -> str | None:
    rutas = rutas_regeneracion(config, carpeta, numero)
    if rutas is None:
        return "No se ha podido regenerar la guía"
    publicar, markdown, html, script = rutas
    try:
        escribir_atomico(
            markdown,
            generar_guia(
                publicacion,
                curso_nombre,
                numero,
                portadas,
                titulos_piezas,
            ),
        )
    except OSError:
        return "No se ha podido regenerar la guía Markdown"
    if not script.is_file():
        return AVISO_HTML

    descriptor, nombre_temporal = tempfile.mkstemp(
        dir=publicar,
        prefix=f".{html.name}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    temporal = Path(nombre_temporal)
    argumentos = [
        sys.executable,
        "-I",
        str(script),
        str(markdown),
        str(temporal),
    ]
    if portada := portadas.get("leccion"):
        try:
            portada_absoluta = ruta_segura(
                publicar,
                *PurePosixPath(portada).parts,
            )
        except ValueError:
            portada_absoluta = None
        if portada_absoluta is not None and portada_absoluta.is_file():
            argumentos.append(str(portada_absoluta))
    entorno = {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": os.environ.get("HOME", str(Path.home())),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
    }
    try:
        proceso = subprocess.Popen(
            argumentos,
            shell=False,
            cwd=publicar,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            env=entorno,
        )
        try:
            proceso.communicate(timeout=TIMEOUT_CONVERSOR_S)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proceso.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                proceso.communicate(timeout=TIMEOUT_RECOGIDA_S)
            except subprocess.TimeoutExpired:
                for tuberia in (proceso.stdout, proceso.stderr):
                    if tuberia is not None:
                        with suppress(OSError):
                            tuberia.close()
            return AVISO_HTML
        if proceso.returncode != 0:
            return AVISO_HTML
        if ruta_escritura_segura(publicar, html.name) != html:
            return AVISO_HTML
        reemplazar_atomico(html, temporal)
    except OSError:
        return AVISO_HTML
    finally:
        temporal.unlink(missing_ok=True)
    return None
