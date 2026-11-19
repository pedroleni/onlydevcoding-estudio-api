import json
import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest

from estudio_api.decisiones import abrir_bd
from estudio_api.tareas import TareaNueva, crear_tarea
from tests.ayudas import TOKEN

RUTA_PUBLICACION = "/api/cursos/react/lecciones/4/publicacion"
PORTADA_LECCION = (
    "cursos/REACT/04-importar-y-exportar/publicar/"
    "1-youtube-leccion/miniatura-A-ejemplo.jpg"
)


def _carpeta_leccion(cfg):
    return cfg.cursos_dir / "REACT" / "04-importar-y-exportar"


def _escribir_publicacion(cfg):
    datos = {
        "version": 1,
        "piezas": {
            "leccion": {
                "titulo": "Lección preparada",
                "video": "1-youtube-leccion/curso-react-04-ejemplo.mp4",
                "duracion": "8:57",
                "portadas": ["1-youtube-leccion/miniatura-A-ejemplo.jpg"],
                "fecha_propuesta": "2026-11-18T20:00",
                "redes": {
                    "youtube": {
                        "titulos": ["Título ficticio"],
                        "video": "1-youtube-leccion/curso-react-04-ejemplo.mp4",
                    },
                },
            },
            "reel-salida": {
                "titulo": "Reel preparado",
                "redes": {"instagram": {"texto": "Texto ficticio"}},
            },
            "short-1": {
                "titulo": "Short solo en el JSON",
                "redes": {"tiktok": {"texto": "Texto ficticio"}},
            },
        },
        "despues_de_publicar": ["Comprobar un dato ficticio"],
        "notas": "Nota ficticia",
    }
    ruta = _carpeta_leccion(cfg) / "publicar" / "publicacion.json"
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")


def _pieza(vista, identificador):
    return next(pieza for pieza in vista["piezas"] if pieza["id"] == identificador)


def _instalar_script_html(cfg, contenido=None):
    script = cfg.estudio_dir / "herramientas" / "publicar" / "md-a-html.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        contenido
        or (
            "from pathlib import Path\n"
            "import sys\n"
            "imagenes = '|'.join(sys.argv[3:])\n"
            "Path(sys.argv[2]).write_text(\n"
            "    f'<html>{imagenes}</html>', encoding='utf-8'\n"
            ")\n"
        ),
        encoding="utf-8",
    )
    return script


def _crear_tarea(cfg, *, texto="Tarea ficticia", enlace=None):
    with closing(abrir_bd(cfg.bd_ruta)) as bd:
        return crear_tarea(
            bd,
            TareaNueva.model_validate(
                {
                    "fecha": "2026-11-17",
                    "hora": None,
                    "texto": texto,
                    "tipo": "publicar",
                    "enlace": enlace,
                }
            ),
        )


def _estado_tarea(cfg, tarea_id):
    with closing(abrir_bd(cfg.bd_ruta)) as bd:
        return bd.execute(
            "SELECT hecha, hecha_en FROM tarea WHERE id = ?", (tarea_id,)
        ).fetchone()


def test_get_sin_json_une_las_piezas_del_disco_y_ordena_las_redes(cliente):
    respuesta = cliente.get(RUTA_PUBLICACION)

    assert respuesta.status_code == 200
    vista = respuesta.json()
    assert vista["curso"] == "react"
    assert vista["numero"] == 4
    assert [pieza["id"] for pieza in vista["piezas"]] == [
        "leccion",
        "reel-salida",
        "short-2",
    ]
    assert [red["red"] for red in vista["piezas"][0]["redes"]] == [
        "youtube",
        "instagram",
        "tiktok",
        "linkedin",
    ]
    assert all(red["textos"] is None for red in vista["piezas"][0]["redes"])
    assert vista["error"] is None
    assert vista["aviso"] is None


def test_get_con_json_une_prioriza_y_ordena_las_piezas(cliente, cfg):
    _escribir_publicacion(cfg)

    respuesta = cliente.get(RUTA_PUBLICACION)

    assert respuesta.status_code == 200
    vista = respuesta.json()
    assert [pieza["id"] for pieza in vista["piezas"]] == [
        "leccion",
        "reel-salida",
        "short-1",
        "short-2",
    ]
    leccion = _pieza(vista, "leccion")
    assert leccion["titulo"] == "Lección preparada"
    assert leccion["video"].endswith("/curso-react-04-ejemplo.mp4")
    assert leccion["duracion"] == "8:57"
    assert leccion["fecha_propuesta"] == "2026-11-18T20:00"
    assert leccion["portadas"] == [PORTADA_LECCION]
    assert leccion["redes"][0]["textos"]["titulos"] == ["Título ficticio"]
    assert leccion["redes"][0]["textos"]["video"].startswith("cursos/")
    assert vista["despues_de_publicar"] == ["Comprobar un dato ficticio"]
    assert vista["notas"] == "Nota ficticia"
    assert vista["aviso"] is None


def test_get_ignora_un_titulo_de_publicacion_vacio(cliente, cfg):
    ruta = _carpeta_leccion(cfg) / "publicar" / "publicacion.json"
    ruta.write_text(
        json.dumps(
            {
                "version": 1,
                "piezas": {"reel-salida": {"titulo": "   "}},
            }
        ),
        encoding="utf-8",
    )

    respuesta = cliente.get(RUTA_PUBLICACION)

    assert respuesta.status_code == 200
    assert _pieza(respuesta.json(), "reel-salida")["titulo"] == "Reel salida"


def test_get_incluye_portadas_candidatas_de_las_subcarpetas(cliente, cfg):
    publicar = _carpeta_leccion(cfg) / "publicar"
    youtube = publicar / "1-youtube-leccion"
    verticales = publicar / "2-shorts-y-reels"
    opciones_miniatura = youtube / "opciones-miniatura"
    opciones_short = verticales / "portadas-short-2-opciones"
    poses_short = verticales / "portadas-short-2-poses"
    verticales_short = verticales / "portadas-short-2-verticales"
    opciones_miniatura.mkdir()
    opciones_short.mkdir()
    poses_short.mkdir()
    verticales_short.mkdir()

    (opciones_miniatura / "miniatura-B.webp").write_bytes(b"imagen")
    (opciones_miniatura / "miniatura-A.png").write_bytes(b"imagen")
    (opciones_short / "opcion-B.jpeg").write_bytes(b"imagen")
    (opciones_short / "opcion-A.png").write_bytes(b"imagen")
    (poses_short / "pose.webp").write_bytes(b"imagen")
    (verticales_short / "vertical.jpg").write_bytes(b"imagen")
    opciones_compartidas = verticales / "portadas-opciones"
    (opciones_compartidas / "portada-reel-B.webp").write_bytes(b"imagen")
    (opciones_compartidas / "portada-reel-A.png").write_bytes(b"imagen")
    (opciones_compartidas / "portada-short-2-C.webp").write_bytes(b"imagen")
    (opciones_compartidas / "portada-short-20-otra.png").write_bytes(b"imagen")

    # No son candidatas: ocultas, extensiones ajenas, más de un nivel y descartadas.
    (opciones_short / ".oculta.jpg").write_bytes(b"imagen")
    (opciones_short / "notas.txt").write_text("texto", encoding="utf-8")
    profunda = opciones_short / "otra-carpeta"
    profunda.mkdir()
    (profunda / "profunda.jpg").write_bytes(b"imagen")
    (verticales / "descartadas" / "portada-short-2-descartada.jpg").write_bytes(
        b"imagen"
    )
    (verticales / "anteriores" / "portada-reel-anterior.jpg").write_bytes(b"imagen")

    respuesta = cliente.get(RUTA_PUBLICACION)

    assert respuesta.status_code == 200
    vista = respuesta.json()
    leccion = _pieza(vista, "leccion")
    reel = _pieza(vista, "reel-salida")
    short = _pieza(vista, "short-2")
    assert leccion["portadas"] == [
        PORTADA_LECCION,
        f"{PORTADA_LECCION.rsplit('/', 1)[0]}/opciones-miniatura/miniatura-A.png",
        f"{PORTADA_LECCION.rsplit('/', 1)[0]}/opciones-miniatura/miniatura-B.webp",
    ]
    assert [ruta.rsplit("/", 1)[-1] for ruta in reel["portadas"]] == [
        "portada-reel-A.png",
        "portada-reel-B.webp",
    ]
    assert [ruta.rsplit("/", 1)[-1] for ruta in short["portadas"]] == [
        "portada-short-2-principal.jpg",
        "opcion-A.png",
        "opcion-B.jpeg",
        "pose.webp",
        "vertical.jpg",
        "portada-short-2-alternativa.jpg",
        "portada-short-2-C.webp",
    ]
    assert not any(
        nombre in ruta
        for pieza in (leccion, reel, short)
        for ruta in pieza["portadas"]
        for nombre in ("oculta", "notas", "profunda", "descartada", "anterior")
    )


def test_elegir_una_portada_de_subcarpeta_funciona(cliente_con_token, cfg):
    opciones = (
        _carpeta_leccion(cfg)
        / "publicar"
        / "2-shorts-y-reels"
        / "portadas-short-2-poses"
    )
    opciones.mkdir()
    (opciones / "pose-elegida.webp").write_bytes(b"imagen")
    ruta = (
        "cursos/REACT/04-importar-y-exportar/publicar/2-shorts-y-reels/"
        "portadas-short-2-poses/pose-elegida.webp"
    )

    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/short-2/portada",
        headers={"X-Estudio-Token": TOKEN},
        json={"ruta": ruta},
    )

    assert respuesta.status_code == 200
    assert _pieza(respuesta.json(), "short-2")["portada_elegida"] == ruta
    recargada = cliente_con_token.get(RUTA_PUBLICACION)
    assert _pieza(recargada.json(), "short-2")["portada_elegida"] == ruta


def test_get_de_leccion_inexistente_da_404(cliente):
    assert cliente.get("/api/cursos/react/lecciones/99/publicacion").status_code == 404


def test_elegir_portada_persiste_y_desaparece_si_se_borra_el_archivo(
    cliente_con_token, cfg
):
    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/portada",
        headers={"X-Estudio-Token": TOKEN},
        json={"ruta": PORTADA_LECCION},
    )

    assert respuesta.status_code == 200
    assert _pieza(respuesta.json(), "leccion")["portada_elegida"] == PORTADA_LECCION
    recargada = cliente_con_token.get(RUTA_PUBLICACION)
    assert _pieza(recargada.json(), "leccion")["portada_elegida"] == PORTADA_LECCION
    detalle = cliente_con_token.get("/api/cursos/react/lecciones/4").json()
    assert detalle["estado"]["miniatura"] == PORTADA_LECCION
    lista = cliente_con_token.get("/api/cursos/react/lecciones").json()
    leccion = next(elemento for elemento in lista if elemento["numero"] == 4)
    assert leccion["estado"]["miniatura"] == PORTADA_LECCION

    portada = (
        _carpeta_leccion(cfg)
        / "publicar"
        / "1-youtube-leccion"
        / "miniatura-A-ejemplo.jpg"
    )
    portada.unlink()

    sin_archivo = cliente_con_token.get(RUTA_PUBLICACION)
    assert _pieza(sin_archivo.json(), "leccion")["portada_elegida"] is None
    detalle_sin_archivo = cliente_con_token.get("/api/cursos/react/lecciones/4").json()
    assert detalle_sin_archivo["estado"]["miniatura"] is None


def test_elegir_portada_regenera_una_guia_creada_por_la_app(cliente_con_token, cfg):
    _escribir_publicacion(cfg)
    _instalar_script_html(cfg)
    publicar = _carpeta_leccion(cfg) / "publicar"
    markdown = publicar / "PUBLICAR-leccion-4.md"
    markdown.write_text("guía manual inicial", encoding="utf-8")
    portada_b = publicar / "1-youtube-leccion" / "miniatura-B-ejemplo.jpg"
    portada_b.write_bytes(b"miniatura B")
    datos = json.loads((publicar / "publicacion.json").read_text(encoding="utf-8"))
    datos["piezas"]["leccion"]["portadas"].append(
        "1-youtube-leccion/miniatura-B-ejemplo.jpg"
    )
    (publicar / "publicacion.json").write_text(json.dumps(datos), encoding="utf-8")
    portada_b_publica = PORTADA_LECCION.replace("miniatura-A", "miniatura-B")

    elegida_a = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/portada",
        headers={"X-Estudio-Token": TOKEN},
        json={"ruta": PORTADA_LECCION},
    )
    assert elegida_a.status_code == 200
    guardado = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/youtube/textos",
        headers={"X-Estudio-Token": TOKEN},
        json={"titulos": ["Título ficticio"]},
    )
    assert guardado.status_code == 200
    assert "miniatura-A-ejemplo.jpg" in markdown.read_text(encoding="utf-8")
    assert markdown.with_name(f"{markdown.name}.antes-de-editar").is_file()

    elegida_b = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/portada",
        headers={"X-Estudio-Token": TOKEN},
        json={"ruta": portada_b_publica},
    )

    assert elegida_b.status_code == 200
    assert elegida_b.json()["aviso"] is None
    guia = markdown.read_text(encoding="utf-8")
    assert "miniatura-B-ejemplo.jpg" in guia
    assert "miniatura-A-ejemplo.jpg" not in guia


def test_elegir_portada_no_modifica_una_guia_manual_sin_copia(cliente_con_token, cfg):
    # Con JSON y conversor presentes, lo único que impide regenerar es que falte la copia.
    _escribir_publicacion(cfg)
    _instalar_script_html(cfg)
    publicar = _carpeta_leccion(cfg) / "publicar"
    markdown = publicar / "PUBLICAR-leccion-4.md"
    markdown.write_text("guía manual intacta", encoding="utf-8")

    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/portada",
        headers={"X-Estudio-Token": TOKEN},
        json={"ruta": PORTADA_LECCION},
    )

    assert respuesta.status_code == 200
    assert markdown.read_text(encoding="utf-8") == "guía manual intacta"
    assert not markdown.with_name(f"{markdown.name}.antes-de-editar").exists()


def test_elegir_portada_devuelve_aviso_si_falla_el_html(cliente_con_token, cfg):
    _escribir_publicacion(cfg)
    _instalar_script_html(cfg, "raise SystemExit(7)\n")
    publicar = _carpeta_leccion(cfg) / "publicar"
    markdown = publicar / "PUBLICAR-leccion-4.md"
    markdown.write_text("guía anterior", encoding="utf-8")
    markdown.with_name(f"{markdown.name}.antes-de-editar").write_text(
        "guía original", encoding="utf-8"
    )

    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/portada",
        headers={"X-Estudio-Token": TOKEN},
        json={"ruta": PORTADA_LECCION},
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["aviso"] == "No se ha podido regenerar la guía HTML"
    assert "miniatura-A-ejemplo.jpg" in markdown.read_text(encoding="utf-8")


def test_portada_que_no_es_candidata_da_422(cliente_con_token):
    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/portada",
        headers={"X-Estudio-Token": TOKEN},
        json={"ruta": "cursos/REACT/04-importar-y-exportar/secreto.jpg"},
    )

    assert respuesta.status_code == 422


def test_marcar_youtube_publicado_actualiza_detalle_y_lista(cliente_con_token):
    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/youtube/estado",
        headers={"X-Estudio-Token": TOKEN},
        json={"estado": "publicado"},
    )

    assert respuesta.status_code == 200
    youtube = _pieza(respuesta.json(), "leccion")["redes"][0]
    assert youtube["estado"]["estado"] == "publicado"
    assert youtube["estado"]["fecha"] is not None

    detalle = cliente_con_token.get("/api/cursos/react/lecciones/4").json()
    assert detalle["estado"]["publicado"]["youtube"] is True
    lista = cliente_con_token.get("/api/cursos/react/lecciones").json()
    leccion = next(elemento for elemento in lista if elemento["numero"] == 4)
    assert leccion["estado"]["publicado"]["youtube"] is True


def test_publicar_completa_solo_las_tareas_enlazadas_a_esa_red(cliente_con_token, cfg):
    tarea_de_red = _crear_tarea(
        cfg,
        texto="Publicar pieza ficticia",
        enlace={
            "curso": "react",
            "numero": 4,
            "pieza": "leccion",
            "red": "youtube",
        },
    )
    tarea_de_leccion = _crear_tarea(
        cfg,
        texto="Revisar lección ficticia",
        enlace={"curso": "react", "numero": 4},
    )

    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/youtube/estado",
        headers={"X-Estudio-Token": TOKEN},
        json={"estado": "publicado"},
    )

    assert respuesta.status_code == 200
    hecha, hecha_en = _estado_tarea(cfg, tarea_de_red.id)
    assert hecha == 1
    assert hecha_en is not None
    assert _estado_tarea(cfg, tarea_de_leccion.id) == (0, None)


def test_programar_no_completa_y_volver_a_pendiente_no_reabre(cliente_con_token, cfg):
    tarea = _crear_tarea(
        cfg,
        enlace={
            "curso": "react",
            "numero": 4,
            "pieza": "leccion",
            "red": "youtube",
        },
    )
    ruta = f"{RUTA_PUBLICACION}/piezas/leccion/redes/youtube/estado"

    programada = cliente_con_token.put(
        ruta,
        headers={"X-Estudio-Token": TOKEN},
        json={"estado": "programado", "fecha": "2026-11-18T20:00:00+01:00"},
    )
    assert programada.status_code == 200
    assert _estado_tarea(cfg, tarea.id) == (0, None)

    publicada = cliente_con_token.put(
        ruta,
        headers={"X-Estudio-Token": TOKEN},
        json={"estado": "publicado"},
    )
    assert publicada.status_code == 200
    estado_publicada = _estado_tarea(cfg, tarea.id)
    assert estado_publicada[0] == 1

    pendiente = cliente_con_token.put(
        ruta,
        headers={"X-Estudio-Token": TOKEN},
        json={"estado": "pendiente"},
    )
    assert pendiente.status_code == 200
    assert _estado_tarea(cfg, tarea.id) == estado_publicada


def test_volver_a_guardar_publicado_completa_nuevas_tareas_pendientes(
    cliente_con_token, cfg
):
    ruta = f"{RUTA_PUBLICACION}/piezas/leccion/redes/youtube/estado"
    primera = cliente_con_token.put(
        ruta,
        headers={"X-Estudio-Token": TOKEN},
        json={"estado": "publicado"},
    )
    assert primera.status_code == 200
    tarea = _crear_tarea(
        cfg,
        enlace={
            "curso": "react",
            "numero": 4,
            "pieza": "leccion",
            "red": "youtube",
        },
    )

    segunda = cliente_con_token.put(
        ruta,
        headers={"X-Estudio-Token": TOKEN},
        json={"estado": "publicado", "url": "https://youtu.be/video-ficticio"},
    )

    assert segunda.status_code == 200
    hecha, hecha_en = _estado_tarea(cfg, tarea.id)
    assert hecha == 1
    assert hecha_en is not None


def test_fallo_al_completar_tareas_revierte_el_estado(
    cliente_con_token, cfg, monkeypatch
):
    def fallar_al_completar(*_args, **_kwargs):
        raise RuntimeError("fallo ficticio al completar")

    monkeypatch.setattr(
        "estudio_api.rutas_publicar.completar_tareas_de_red",
        fallar_al_completar,
    )

    with pytest.raises(RuntimeError, match="fallo ficticio al completar"):
        cliente_con_token.put(
            f"{RUTA_PUBLICACION}/piezas/leccion/redes/youtube/estado",
            headers={"X-Estudio-Token": TOKEN},
            json={"estado": "publicado"},
        )

    with closing(abrir_bd(cfg.bd_ruta)) as bd:
        estado = bd.execute(
            """
            SELECT estado FROM estado_red
            WHERE curso = ? AND numero = ? AND pieza = ? AND red = ?
            """,
            ("react", 4, "leccion", "youtube"),
        ).fetchone()
    assert estado is None


def test_reel_previsto_en_instagram_pendiente_mantiene_la_red_falsa(
    cliente_con_token, cfg
):
    _escribir_publicacion(cfg)
    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/instagram/estado",
        headers={"X-Estudio-Token": TOKEN},
        json={"estado": "publicado"},
    )

    assert respuesta.status_code == 200
    detalle = cliente_con_token.get("/api/cursos/react/lecciones/4").json()
    assert detalle["estado"]["publicado"]["instagram"] is False


def test_put_sin_token_da_401(cliente_con_token):
    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/portada",
        json={"ruta": PORTADA_LECCION},
    )

    assert respuesta.status_code == 401


@pytest.mark.parametrize(
    "sufijo",
    [
        "/piezas/short-1\u0663/portada",
        "/piezas/leccion/redes/facebook/estado",
    ],
)
def test_pieza_o_red_invalida_se_rechaza_antes_de_abrir_la_base(
    cliente_con_token, monkeypatch, sufijo
):
    def no_abrir(_ruta):
        raise AssertionError("No debe abrir la base")

    monkeypatch.setattr("estudio_api.rutas_publicar.abrir_bd", no_abrir)

    respuesta = cliente_con_token.put(
        RUTA_PUBLICACION + sufijo,
        headers={"X-Estudio-Token": TOKEN},
        json={"estado": "pendiente", "ruta": PORTADA_LECCION},
    )

    assert respuesta.status_code in (404, 422)


def test_cambiar_estado_de_pieza_inexistente_da_404(cliente_con_token):
    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/short-99/redes/youtube/estado",
        headers={"X-Estudio-Token": TOKEN},
        json={"estado": "pendiente"},
    )

    assert respuesta.status_code == 404


def test_guardar_textos_escribe_json_y_regenera_las_dos_guias(cliente_con_token, cfg):
    _escribir_publicacion(cfg)
    _instalar_script_html(cfg)
    publicar = _carpeta_leccion(cfg) / "publicar"
    markdown = publicar / "PUBLICAR-leccion-4.md"
    html = publicar / "PUBLICAR-leccion-4.html"
    markdown.write_text("guía anterior", encoding="utf-8")
    html.write_text("html anterior", encoding="utf-8")
    json_ruta = publicar / "publicacion.json"
    json_anterior = json_ruta.read_text(encoding="utf-8")

    eleccion = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/portada",
        headers={"X-Estudio-Token": TOKEN},
        json={"ruta": PORTADA_LECCION},
    )
    assert eleccion.status_code == 200

    textos = {
        "titulos": ["Título recomendado", "Otra opción"],
        "descripcion": 'Línea con ``` y "comillas".\n\nEmoji 🚀',
        "etiquetas": ["prueba", "ficticia"],
        "comentario_fijado": "Comentario ficticio",
        "ajustes": ["Visibilidad: privado"],
        "notas": "Nota ficticia",
    }
    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/youtube/textos",
        headers={"X-Estudio-Token": TOKEN},
        json=textos,
    )

    assert respuesta.status_code == 200
    vista = respuesta.json()
    assert vista["aviso"] is None
    assert (
        _pieza(vista, "leccion")["redes"][0]["textos"]["descripcion"]
        == (textos["descripcion"])
    )
    serializado = json_ruta.read_text(encoding="utf-8")
    assert serializado.endswith("\n")
    assert "🚀" in serializado
    assert "\\ud83d" not in serializado.lower()
    assert (
        '"descripcion": "Línea con ``` y \\"comillas\\".\\n\\nEmoji 🚀"' in serializado
    )
    assert '"texto": null' not in serializado
    assert (publicar / "publicacion.json.antes-de-editar").read_text(
        encoding="utf-8"
    ) == json_anterior

    guia = markdown.read_text(encoding="utf-8")
    assert "# Publicar la lección 4 de React" in guia
    assert "`1-youtube-leccion/curso-react-04-ejemplo.mp4`" in guia
    assert "`1-youtube-leccion/miniatura-A-ejemplo.jpg`" in guia
    assert str(cfg.cursos_dir) not in guia
    assert (publicar / "PUBLICAR-leccion-4.md.antes-de-editar").read_text(
        encoding="utf-8"
    ) == "guía anterior"
    assert html.read_text(encoding="utf-8") == (
        "<html>"
        + str((publicar / "1-youtube-leccion" / "miniatura-A-ejemplo.jpg").resolve())
        + "</html>"
    )
    assert (publicar / "PUBLICAR-leccion-4.html.antes-de-editar").read_text(
        encoding="utf-8"
    ) == "html anterior"


def test_guardar_textos_sin_json_lo_crea_y_avisa_si_falla_el_html(
    cliente_con_token, cfg
):
    _instalar_script_html(cfg, "raise SystemExit(7)\n")
    publicar = _carpeta_leccion(cfg) / "publicar"

    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/instagram/textos",
        headers={"X-Estudio-Token": TOKEN},
        json={"texto": "Texto ficticio"},
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["aviso"]
    datos = json.loads((publicar / "publicacion.json").read_text(encoding="utf-8"))
    assert datos["version"] == 1
    assert datos["piezas"]["leccion"]["redes"]["instagram"]["texto"] == (
        "Texto ficticio"
    )
    assert (publicar / "PUBLICAR-leccion-4.md").is_file()
    assert not (publicar / "PUBLICAR-leccion-4.html").exists()
    assert not list(publicar.glob(".PUBLICAR-leccion-4.html.*.tmp"))


def test_guardar_textos_con_json_corrupto_da_409_y_no_escribe(cliente_con_token, cfg):
    publicar = _carpeta_leccion(cfg) / "publicar"
    json_ruta = publicar / "publicacion.json"
    json_ruta.write_bytes(b"{json roto")
    contenido_anterior = json_ruta.read_bytes()

    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/youtube/textos",
        headers={"X-Estudio-Token": TOKEN},
        json={"titulos": ["Título ficticio"]},
    )

    assert respuesta.status_code == 409
    assert respuesta.json()["detail"] == (
        "Arregla publicacion.json antes de editar desde la app"
    )
    assert json_ruta.read_bytes() == contenido_anterior
    assert not (publicar / "publicacion.json.antes-de-editar").exists()
    assert not (publicar / "PUBLICAR-leccion-4.md").exists()


def test_guardar_titulo_de_101_caracteres_da_422(cliente_con_token):
    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/youtube/textos",
        headers={"X-Estudio-Token": TOKEN},
        json={"titulos": ["x" * 101]},
    )

    assert respuesta.status_code == 422
    assert "100" in respuesta.text


@pytest.mark.parametrize(
    "video",
    [
        "1-youtube-leccion/curso-react-04-ejemplo.mp4",
        "/ruta/ficticia.mp4",
        "../../fuera.mp4",
        None,
    ],
)
def test_guardar_textos_rechaza_el_campo_video(cliente_con_token, video):
    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/linkedin/textos",
        headers={"X-Estudio-Token": TOKEN},
        json={"texto": "Texto ficticio", "video": video},
    )

    assert respuesta.status_code == 422


@pytest.mark.parametrize(
    "video",
    [
        "1-youtube-leccion/curso-react-04-ejemplo.mp4",
        "pendiente/video-linkedin.mp4",
    ],
)
def test_guardar_textos_conserva_el_video_de_la_misma_red(
    cliente_con_token, cfg, video
):
    publicar = _carpeta_leccion(cfg) / "publicar"
    datos = {
        "version": 1,
        "piezas": {
            "leccion": {
                "redes": {
                    "linkedin": {
                        "texto": "Texto anterior",
                        "video": video,
                    }
                }
            }
        },
    }
    ruta = publicar / "publicacion.json"
    ruta.write_text(json.dumps(datos), encoding="utf-8")

    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/linkedin/textos",
        headers={"X-Estudio-Token": TOKEN},
        json={"texto": "Texto actualizado"},
    )

    assert respuesta.status_code == 200
    guardado = json.loads(ruta.read_text(encoding="utf-8"))
    assert guardado["piezas"]["leccion"]["redes"]["linkedin"]["video"] == video


def test_regenerar_html_ejecuta_una_lista_sin_shell(
    cliente_con_token, cfg, monkeypatch
):
    script = _instalar_script_html(cfg)
    llamada = {}

    class ProcesoFalso:
        pid = 12345
        returncode = 0

        def __init__(self, argumentos):
            self.argumentos = argumentos

        def communicate(self, timeout):
            llamada["timeout"] = timeout
            Path(self.argumentos[4]).write_text(
                "<html>ficticio</html>", encoding="utf-8"
            )
            return b"salida", b"error"

    def ejecutar(argumentos, **opciones):
        llamada["argumentos"] = argumentos
        llamada["opciones"] = opciones
        return ProcesoFalso(argumentos)

    eleccion = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/portada",
        headers={"X-Estudio-Token": TOKEN},
        json={"ruta": PORTADA_LECCION},
    )
    assert eleccion.status_code == 200
    monkeypatch.setattr("estudio_api.guia.subprocess.Popen", ejecutar)

    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/linkedin/textos",
        headers={"X-Estudio-Token": TOKEN},
        json={"texto": "Texto ficticio"},
    )

    assert respuesta.status_code == 200
    assert isinstance(llamada["argumentos"], list)
    assert llamada["argumentos"][1:3] == ["-I", str(script.resolve())]
    assert llamada["argumentos"][5] == str(
        (
            _carpeta_leccion(cfg)
            / "publicar"
            / "1-youtube-leccion"
            / "miniatura-A-ejemplo.jpg"
        ).resolve()
    )
    assert llamada["opciones"]["shell"] is False
    assert llamada["opciones"]["stdout"] is subprocess.PIPE
    assert llamada["opciones"]["stderr"] is subprocess.PIPE
    assert llamada["opciones"]["start_new_session"] is True
    assert llamada["opciones"]["cwd"] == _carpeta_leccion(cfg) / "publicar"
    assert set(llamada["opciones"]["env"]) == {"PATH", "HOME", "LANG"}
    assert "ESTUDIO_TOKEN" not in llamada["opciones"]["env"]
    assert llamada["timeout"] == 60


def test_regenerar_html_no_hereda_estudio_token(cliente_con_token, cfg, monkeypatch):
    _instalar_script_html(cfg)
    monkeypatch.setenv("ESTUDIO_TOKEN", "secreto-ficticio-que-no-debe-heredarse")
    entorno = {}

    class ProcesoFalso:
        pid = 12345
        returncode = 0

        def __init__(self, argumentos):
            self.argumentos = argumentos

        def communicate(self, timeout):
            Path(self.argumentos[4]).write_text("<html></html>", encoding="utf-8")
            return b"", b""

    def ejecutar(argumentos, **opciones):
        entorno.update(opciones["env"])
        return ProcesoFalso(argumentos)

    monkeypatch.setattr("estudio_api.guia.subprocess.Popen", ejecutar)

    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/linkedin/textos",
        headers={"X-Estudio-Token": TOKEN},
        json={"texto": "Texto ficticio"},
    )

    assert respuesta.status_code == 200
    assert set(entorno) == {"PATH", "HOME", "LANG"}
    assert "ESTUDIO_TOKEN" not in entorno


def test_put_conserva_medios_anotados_aunque_aun_no_existan(cliente_con_token, cfg):
    publicar = _carpeta_leccion(cfg) / "publicar"
    datos = {
        "version": 1,
        "piezas": {
            "leccion": {
                "video": "pendiente/video-leccion.mp4",
                "portadas": ["pendiente/portada-leccion.jpg"],
                "redes": {
                    "linkedin": {
                        "texto": "Texto ficticio",
                        "video": "pendiente/video-linkedin.mp4",
                    }
                },
            }
        },
    }
    (publicar / "publicacion.json").write_text(json.dumps(datos), encoding="utf-8")

    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/instagram/textos",
        headers={"X-Estudio-Token": TOKEN},
        json={"texto": "Texto actualizado"},
    )

    assert respuesta.status_code == 200
    guardado = json.loads((publicar / "publicacion.json").read_text(encoding="utf-8"))
    pieza = guardado["piezas"]["leccion"]
    assert pieza["video"] == "pendiente/video-leccion.mp4"
    assert pieza["portadas"] == ["pendiente/portada-leccion.jpg"]
    assert pieza["redes"]["linkedin"]["video"] == "pendiente/video-linkedin.mp4"


def test_put_rechaza_publicar_symlink_fuera_sin_escribir(
    cliente_con_token, cfg, tmp_path
):
    publicar = _carpeta_leccion(cfg) / "publicar"
    fuera = tmp_path / "fuera"
    shutil.rmtree(publicar)
    fuera.mkdir()
    publicar.symlink_to(fuera, target_is_directory=True)

    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/instagram/textos",
        headers={"X-Estudio-Token": TOKEN},
        json={"texto": "Texto ficticio"},
    )

    assert respuesta.status_code == 409
    assert respuesta.json()["detail"] == "La carpeta publicar no es válida"
    assert not (fuera / "publicacion.json").exists()


def test_dos_put_simultaneos_conservan_las_dos_redes(
    cliente_con_token, cfg, monkeypatch
):
    from estudio_api import rutas_publicar

    lectura_real = rutas_publicar.leer_publicacion

    def leer_con_retardo(*argumentos, **opciones):
        lectura = lectura_real(*argumentos, **opciones)
        time.sleep(0.15)
        return lectura

    monkeypatch.setattr(rutas_publicar, "leer_publicacion", leer_con_retardo)
    monkeypatch.setattr(rutas_publicar, "regenerar_guia", lambda *args, **kwargs: None)

    def guardar(red):
        return cliente_con_token.put(
            f"{RUTA_PUBLICACION}/piezas/leccion/redes/{red}/textos",
            headers={"X-Estudio-Token": TOKEN},
            json={"texto": f"Texto de {red}"},
        )

    with ThreadPoolExecutor(max_workers=2) as ejecutor:
        respuestas = list(ejecutor.map(guardar, ["youtube", "instagram"]))

    assert [respuesta.status_code for respuesta in respuestas] == [200, 200]
    ruta = _carpeta_leccion(cfg) / "publicar" / "publicacion.json"
    redes = json.loads(ruta.read_text(encoding="utf-8"))["piezas"]["leccion"]["redes"]
    assert set(redes) == {"youtube", "instagram"}


def test_put_con_sustituto_unicode_suelto_da_422(cliente_con_token):
    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/instagram/textos",
        headers={
            "X-Estudio-Token": TOKEN,
            "Content-Type": "application/json",
        },
        content=b'{"texto":"a\\ud800b"}',
    )

    assert respuesta.status_code == 422


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"titulos": ["Título\n## Falso"]},
        {"ajustes": ["Visibilidad: privado\n## Falso"]},
    ],
)
def test_put_rechaza_saltos_en_titulos_y_ajustes(cliente_con_token, cuerpo):
    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/youtube/textos",
        headers={"X-Estudio-Token": TOKEN},
        json=cuerpo,
    )

    assert respuesta.status_code == 422


def test_put_sin_carpeta_publicar_da_409(cliente_con_token, cfg):
    shutil.rmtree(_carpeta_leccion(cfg) / "publicar")

    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/instagram/textos",
        headers={"X-Estudio-Token": TOKEN},
        json={"texto": "Texto ficticio"},
    )

    assert respuesta.status_code == 409
    assert respuesta.json()["detail"] == "La lección no tiene carpeta publicar"


def test_fallo_al_escribir_markdown_devuelve_vista_con_aviso(
    cliente_con_token, cfg, monkeypatch
):
    def fallar_markdown(*_argumentos, **_opciones):
        raise OSError("fallo ficticio")

    monkeypatch.setattr("estudio_api.guia.escribir_atomico", fallar_markdown)

    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/instagram/textos",
        headers={"X-Estudio-Token": TOKEN},
        json={"texto": "Texto guardado"},
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["aviso"]
    ruta = _carpeta_leccion(cfg) / "publicar" / "publicacion.json"
    assert (
        json.loads(ruta.read_text(encoding="utf-8"))["piezas"]["leccion"]["redes"][
            "instagram"
        ]["texto"]
        == "Texto guardado"
    )


def test_timeout_mata_el_grupo_del_conversor(cliente_con_token, cfg, monkeypatch):
    from estudio_api import guia

    assert hasattr(guia, "TIMEOUT_CONVERSOR_S")
    monkeypatch.setattr(guia, "TIMEOUT_CONVERSOR_S", 0.05)
    _instalar_script_html(
        cfg,
        (
            "import os\n"
            "from pathlib import Path\n"
            "import time\n"
            "Path('.grupo-prueba').write_text(str(os.getpgrp()), encoding='utf-8')\n"
            "time.sleep(30)\n"
        ),
    )
    publicar = _carpeta_leccion(cfg) / "publicar"

    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/instagram/textos",
        headers={"X-Estudio-Token": TOKEN},
        json={"texto": "Texto ficticio"},
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["aviso"] == "No se ha podido regenerar la guía HTML"
    grupo = int((publicar / ".grupo-prueba").read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.killpg(grupo, 0)


def test_timeout_de_recogida_no_cuelga_la_peticion(cliente_con_token, cfg, monkeypatch):
    _instalar_script_html(cfg)
    llamadas = []

    class TuberiaFalsa:
        def __init__(self):
            self.cerrada = False

        def close(self):
            self.cerrada = True

    class ProcesoFalso:
        pid = 12345
        returncode = None
        stdout = TuberiaFalsa()
        stderr = TuberiaFalsa()

        def communicate(self, timeout):
            llamadas.append(timeout)
            raise subprocess.TimeoutExpired(["conversor"], timeout)

    proceso = ProcesoFalso()
    monkeypatch.setattr("estudio_api.guia.subprocess.Popen", lambda *_a, **_k: proceso)
    monkeypatch.setattr("estudio_api.guia.os.killpg", lambda *_a: None)

    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/instagram/textos",
        headers={"X-Estudio-Token": TOKEN},
        json={"texto": "Texto ficticio"},
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["aviso"] == "No se ha podido regenerar la guía HTML"
    assert llamadas == [60, 5]
    assert proceso.stdout.cerrada is True
    assert proceso.stderr.cerrada is True


def test_json_guardado_omite_listas_vacias_y_none_sin_perder_version(
    cliente_con_token, cfg
):
    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/instagram/textos",
        headers={"X-Estudio-Token": TOKEN},
        json={"texto": "Texto ficticio", "titulos": [], "ajustes": []},
    )

    assert respuesta.status_code == 200
    ruta = _carpeta_leccion(cfg) / "publicar" / "publicacion.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert datos["version"] == 1
    assert "titulos" not in datos["piezas"]["leccion"]["redes"]["instagram"]
    assert "ajustes" not in datos["piezas"]["leccion"]["redes"]["instagram"]
    assert "null" not in ruta.read_text(encoding="utf-8")


def test_guardar_red_vacia_elimina_la_red_y_la_pieza(cliente_con_token, cfg):
    publicar = _carpeta_leccion(cfg) / "publicar"
    ruta = publicar / "publicacion.json"
    ruta.write_text(
        json.dumps(
            {
                "version": 1,
                "piezas": {"leccion": {"redes": {"tiktok": {"texto": "Antes"}}}},
            }
        ),
        encoding="utf-8",
    )

    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/tiktok/textos",
        headers={"X-Estudio-Token": TOKEN},
        json={},
    )

    assert respuesta.status_code == 200
    guardado = json.loads(ruta.read_text(encoding="utf-8"))
    assert "leccion" not in guardado["piezas"]
    assert '"tiktok": {}' not in ruta.read_text(encoding="utf-8")


def test_json_guardado_ordena_las_piezas_como_la_vista(cliente_con_token, cfg):
    publicar = _carpeta_leccion(cfg) / "publicar"
    ruta = publicar / "publicacion.json"
    ruta.write_text(
        json.dumps(
            {
                "version": 1,
                "piezas": {
                    "short-10": {"titulo": "Short diez"},
                    "reel-salida-2": {"titulo": "Segundo reel"},
                    "short-2": {"titulo": "Short dos"},
                    "leccion": {"titulo": "Lección"},
                    "reel-salida": {"titulo": "Primer reel"},
                },
            }
        ),
        encoding="utf-8",
    )

    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/youtube/textos",
        headers={"X-Estudio-Token": TOKEN},
        json={"titulos": ["Título ficticio"]},
    )

    assert respuesta.status_code == 200
    guardado = json.loads(ruta.read_text(encoding="utf-8"))
    assert list(guardado["piezas"]) == [
        "leccion",
        "reel-salida",
        "reel-salida-2",
        "short-2",
        "short-10",
    ]


def test_json_demasiado_grande_da_422_y_no_escribe(cliente_con_token, cfg, monkeypatch):
    publicar = _carpeta_leccion(cfg) / "publicar"
    ruta = publicar / "publicacion.json"
    ruta.write_text(
        json.dumps(
            {
                "version": 1,
                "piezas": {"leccion": {"titulo": "Título anterior"}},
            }
        ),
        encoding="utf-8",
    )
    anterior = ruta.read_bytes()
    monkeypatch.setattr("estudio_api.rutas_publicar.MAX_TAMANO_JSON", 100)

    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/youtube/textos",
        headers={"X-Estudio-Token": TOKEN},
        json={"titulos": ["x" * 50]},
    )

    assert respuesta.status_code == 422
    assert ruta.read_bytes() == anterior
    assert not ruta.with_name(f"{ruta.name}.antes-de-editar").exists()


def test_put_rechaza_publicacion_json_como_enlace_colgante(cliente_con_token, cfg):
    publicar = _carpeta_leccion(cfg) / "publicar"
    destino = publicar / "1-youtube-leccion" / "no-permitido.html"
    (publicar / "publicacion.json").symlink_to(destino)

    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/instagram/textos",
        headers={"X-Estudio-Token": TOKEN},
        json={"texto": "Texto ficticio"},
    )

    assert respuesta.status_code == 409
    assert not destino.exists()


def test_put_rechaza_markdown_enlazado_a_video(cliente_con_token, cfg):
    publicar = _carpeta_leccion(cfg) / "publicar"
    destino = publicar / "1-youtube-leccion" / "curso-react-04-ejemplo.mp4"
    contenido = destino.read_bytes()
    markdown = publicar / "PUBLICAR-leccion-4.md"
    markdown.symlink_to(destino)

    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/instagram/textos",
        headers={"X-Estudio-Token": TOKEN},
        json={"texto": "Texto ficticio"},
    )

    assert respuesta.status_code == 409
    assert destino.read_bytes() == contenido


def test_put_rechaza_html_enlazado_a_video(cliente_con_token, cfg):
    publicar = _carpeta_leccion(cfg) / "publicar"
    destino = publicar / "1-youtube-leccion" / "curso-react-04-ejemplo.mp4"
    contenido = destino.read_bytes()
    html = publicar / "PUBLICAR-leccion-4.html"
    html.symlink_to(destino)

    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/instagram/textos",
        headers={"X-Estudio-Token": TOKEN},
        json={"texto": "Texto ficticio"},
    )

    assert respuesta.status_code == 409
    assert destino.read_bytes() == contenido


def test_put_rechaza_publicar_enlazada_a_otra_leccion(cliente_con_token, cfg):
    leccion = _carpeta_leccion(cfg)
    publicar = leccion / "publicar"
    destino = cfg.cursos_dir / "REACT" / "05-otra" / "publicar"
    destino.mkdir()
    shutil.rmtree(publicar)
    publicar.symlink_to(destino, target_is_directory=True)

    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/instagram/textos",
        headers={"X-Estudio-Token": TOKEN},
        json={"texto": "Texto ficticio"},
    )

    assert respuesta.status_code == 409
    assert list(destino.iterdir()) == []


def test_put_rechaza_publicar_enlazada_a_raiz(cliente_con_token, cfg):
    publicar = _carpeta_leccion(cfg) / "publicar"
    shutil.rmtree(publicar)
    publicar.symlink_to(cfg.cursos_dir, target_is_directory=True)
    nombres_antes = {ruta.name for ruta in cfg.cursos_dir.iterdir()}

    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/instagram/textos",
        headers={"X-Estudio-Token": TOKEN},
        json={"texto": "Texto ficticio"},
    )

    assert respuesta.status_code == 409
    assert {ruta.name for ruta in cfg.cursos_dir.iterdir()} == nombres_antes


def test_guia_usa_el_mismo_titulo_que_la_vista_si_falta_en_json(cliente_con_token, cfg):
    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/instagram/textos",
        headers={"X-Estudio-Token": TOKEN},
        json={"texto": "Texto ficticio"},
    )

    assert respuesta.status_code == 200
    titulo_vista = _pieza(respuesta.json(), "leccion")["titulo"]
    guia = (_carpeta_leccion(cfg) / "publicar" / "PUBLICAR-leccion-4.md").read_text(
        encoding="utf-8"
    )
    assert f"## {titulo_vista}" in guia
    assert "## Leccion\n" not in guia


def test_put_construye_la_vista_una_sola_vez(cliente_con_token, monkeypatch):
    from estudio_api import rutas_publicar

    construir_real = rutas_publicar.construir_vista_publicacion
    llamadas = 0

    def contar(*argumentos, **opciones):
        nonlocal llamadas
        llamadas += 1
        return construir_real(*argumentos, **opciones)

    monkeypatch.setattr(rutas_publicar, "construir_vista_publicacion", contar)

    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/instagram/textos",
        headers={"X-Estudio-Token": TOKEN},
        json={"texto": "Texto ficticio"},
    )

    assert respuesta.status_code == 200
    assert llamadas == 1
