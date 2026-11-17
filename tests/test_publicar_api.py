import json
import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
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

    class ProcesoFalso:
        pid = 12345
        returncode = 0

        def __init__(self, argumentos):
            self.argumentos = argumentos

        def communicate(self, timeout):
            llamada["timeout"] = timeout
            Path(self.argumentos[3]).write_text(
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
    assert llamada["argumentos"][1] == str(script.resolve())
    assert llamada["argumentos"][4] == str(
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
    assert llamada["timeout"] == 60


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
