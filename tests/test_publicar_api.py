import json
import subprocess
from pathlib import Path

import pytest

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
        "<html>1-youtube-leccion/miniatura-A-ejemplo.jpg</html>"
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


@pytest.mark.parametrize("video", ["/ruta/ficticia.mp4", "../../fuera.mp4"])
def test_guardar_video_fuera_de_publicar_da_422(cliente_con_token, video):
    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/linkedin/textos",
        headers={"X-Estudio-Token": TOKEN},
        json={"texto": "Texto ficticio", "video": video},
    )

    assert respuesta.status_code == 422


def test_regenerar_html_ejecuta_una_lista_sin_shell(
    cliente_con_token, cfg, monkeypatch
):
    script = _instalar_script_html(cfg)
    llamada = {}

    def ejecutar(argumentos, **opciones):
        llamada["argumentos"] = argumentos
        llamada["opciones"] = opciones
        Path(argumentos[3]).write_text("<html>ficticio</html>", encoding="utf-8")
        return subprocess.CompletedProcess(argumentos, 0)

    monkeypatch.setattr("estudio_api.guia.subprocess.run", ejecutar)

    respuesta = cliente_con_token.put(
        f"{RUTA_PUBLICACION}/piezas/leccion/redes/linkedin/textos",
        headers={"X-Estudio-Token": TOKEN},
        json={"texto": "Texto ficticio"},
    )

    assert respuesta.status_code == 200
    assert isinstance(llamada["argumentos"], list)
    assert llamada["argumentos"][1] == str(script.resolve())
    assert llamada["opciones"]["shell"] is False
    assert llamada["opciones"]["timeout"] == 60
    assert llamada["opciones"]["cwd"] == _carpeta_leccion(cfg) / "publicar"
