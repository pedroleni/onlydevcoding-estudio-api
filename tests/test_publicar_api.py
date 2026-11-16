import json

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
