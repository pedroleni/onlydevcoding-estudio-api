import json

import pytest

from estudio_api.publicacion import (
    TextosRed,
    leer_publicacion,
    ruta_publica_publicar,
    validar_textos,
)


@pytest.fixture
def carpeta_publicacion(cfg):
    carpeta = cfg.cursos_dir / "REACT" / "04-importar-y-exportar"
    publicar = carpeta / "publicar"
    youtube = publicar / "1-youtube-leccion"
    linkedin = publicar / "4-linkedin"
    linkedin.mkdir()
    (linkedin / "video-linkedin.mp4").write_bytes(b"video")
    (youtube / "archivo.txt").write_text("no es un medio", encoding="utf-8")
    return carpeta


def _escribir_publicacion(carpeta, datos):
    (carpeta / "publicar" / "publicacion.json").write_text(
        json.dumps(datos, ensure_ascii=False),
        encoding="utf-8",
    )


def _publicacion_valida():
    return {
        "version": 1,
        "piezas": {
            "leccion": {
                "titulo": "Lección ficticia",
                "video": "1-youtube-leccion/curso-react-04-ejemplo.mp4",
                "duracion": "8:57",
                "portadas": ["1-youtube-leccion/miniatura-A-ejemplo.jpg"],
                "fecha_propuesta": "2026-11-16T20:00",
                "redes": {
                    "youtube": {
                        "titulos": ["Título recomendado 🎬", "Alternativa"],
                        "descripcion": "Primera línea.\n\nSegunda línea con emoji 🚀",
                        "etiquetas": ["curso ficticio", "ejemplo"],
                        "comentario_fijado": "Comentario ficticio",
                        "ajustes": ["Visibilidad: privado"],
                        "notas": "Nota ficticia",
                    },
                    "linkedin": {
                        "texto": "Texto de prueba ✨",
                        "video": "4-linkedin/video-linkedin.mp4",
                    },
                },
            },
            "reel-salida-2": {
                "titulo": "Resumen ficticio",
                "redes": {"instagram": {}, "tiktok": {}},
            },
            "short-1": {"redes": {"youtube": {}}},
        },
        "despues_de_publicar": ["Comprobar un dato ficticio"],
        "notas": None,
    }


def test_lee_publicacion_valida_y_conserva_los_textos(carpeta_publicacion, cfg):
    datos = _publicacion_valida()
    _escribir_publicacion(carpeta_publicacion, datos)

    lectura = leer_publicacion(cfg, carpeta_publicacion)

    assert lectura.error is None
    assert lectura.publicacion is not None
    assert set(lectura.publicacion.piezas) == {
        "leccion",
        "reel-salida-2",
        "short-1",
    }
    youtube = lectura.publicacion.piezas["leccion"].redes["youtube"]
    assert youtube.titulos == ["Título recomendado 🎬", "Alternativa"]
    assert youtube.descripcion == "Primera línea.\n\nSegunda línea con emoji 🚀"
    assert youtube.etiquetas == ["curso ficticio", "ejemplo"]
    assert (
        lectura.publicacion.piezas["leccion"].redes["linkedin"].video
        == "4-linkedin/video-linkedin.mp4"
    )


def test_json_roto_devuelve_el_error_fijado(carpeta_publicacion, cfg):
    (carpeta_publicacion / "publicar" / "publicacion.json").write_text(
        "{json roto",
        encoding="utf-8",
    )

    lectura = leer_publicacion(cfg, carpeta_publicacion)

    assert lectura.publicacion is None
    assert lectura.error == "No se ha podido leer publicacion.json"


def test_campo_desconocido_invalida_el_archivo(carpeta_publicacion, cfg):
    datos = _publicacion_valida()
    datos["campo_raro"] = True
    _escribir_publicacion(carpeta_publicacion, datos)

    lectura = leer_publicacion(cfg, carpeta_publicacion)

    assert lectura.publicacion is None
    assert lectura.error == "No se ha podido leer publicacion.json"


def test_id_de_pieza_no_permitido_invalida_el_archivo(carpeta_publicacion, cfg):
    datos = _publicacion_valida()
    datos["piezas"]["reel-final"] = datos["piezas"].pop("reel-salida-2")
    _escribir_publicacion(carpeta_publicacion, datos)

    lectura = leer_publicacion(cfg, carpeta_publicacion)

    assert lectura.publicacion is None
    assert lectura.error == "No se ha podido leer publicacion.json"


def test_descarta_portadas_inseguras_inexistentes_y_no_servidas(
    carpeta_publicacion, cfg
):
    datos = _publicacion_valida()
    datos["piezas"]["leccion"]["portadas"] = [
        "1-youtube-leccion/miniatura-A-ejemplo.jpg",
        "../../fuera.jpg",
        "1-youtube-leccion/inexistente.jpg",
        "1-youtube-leccion/archivo.txt",
    ]
    _escribir_publicacion(carpeta_publicacion, datos)

    lectura = leer_publicacion(cfg, carpeta_publicacion)

    assert lectura.publicacion is not None
    assert lectura.publicacion.piezas["leccion"].portadas == [
        "1-youtube-leccion/miniatura-A-ejemplo.jpg"
    ]


def test_descarta_rutas_ocultas_node_modules_y_symlink_fuera(
    carpeta_publicacion, cfg, tmp_path
):
    publicar = carpeta_publicacion / "publicar"
    (publicar / ".oculto").mkdir()
    (publicar / ".oculto" / "video.mp4").write_bytes(b"oculto")
    (publicar / "node_modules").mkdir()
    (publicar / "node_modules" / "video.mp4").write_bytes(b"dependencia")
    fuera = tmp_path / "fuera.mp4"
    fuera.write_bytes(b"fuera")
    (publicar / "enlace.mp4").symlink_to(fuera)
    datos = _publicacion_valida()
    pieza = datos["piezas"]["leccion"]
    pieza["video"] = ".oculto/video.mp4"
    pieza["portadas"] = ["node_modules/video.mp4", "enlace.mp4"]
    pieza["redes"]["linkedin"]["video"] = "/ruta/absoluta.mp4"
    _escribir_publicacion(carpeta_publicacion, datos)

    lectura = leer_publicacion(cfg, carpeta_publicacion)

    assert lectura.publicacion is not None
    pieza_leida = lectura.publicacion.piezas["leccion"]
    assert pieza_leida.video is None
    assert pieza_leida.portadas == []
    assert pieza_leida.redes["linkedin"].video is None


def test_descarta_symlink_visible_cuyo_destino_real_esta_oculto(
    carpeta_publicacion, cfg
):
    publicar = carpeta_publicacion / "publicar"
    oculto = publicar / ".h"
    oculto.mkdir()
    (oculto / "video.mp4").write_bytes(b"oculto")
    (publicar / "video-visible.mp4").symlink_to(oculto / "video.mp4")
    datos = _publicacion_valida()
    datos["piezas"]["leccion"]["video"] = "video-visible.mp4"
    _escribir_publicacion(carpeta_publicacion, datos)

    lectura = leer_publicacion(cfg, carpeta_publicacion)

    assert lectura.publicacion is not None
    assert lectura.publicacion.piezas["leccion"].video is None


def test_sustituto_unicode_suelto_invalida_el_archivo(carpeta_publicacion, cfg):
    (carpeta_publicacion / "publicar" / "publicacion.json").write_bytes(
        b'{"version":1,"piezas":{"leccion":{"titulo":"\\ud800"}}}'
    )

    lectura = leer_publicacion(cfg, carpeta_publicacion)

    assert lectura.publicacion is None
    assert lectura.error == "No se ha podido leer publicacion.json"


def test_id_de_pieza_solo_admite_digitos_ascii(carpeta_publicacion, cfg):
    datos = _publicacion_valida()
    datos["piezas"]["short-1\u0663"] = datos["piezas"].pop("short-1")
    _escribir_publicacion(carpeta_publicacion, datos)

    lectura = leer_publicacion(cfg, carpeta_publicacion)

    assert lectura.publicacion is None
    assert lectura.error == "No se ha podido leer publicacion.json"


def test_sin_carpeta_o_sin_archivo_no_es_un_error(carpeta_publicacion, cfg):
    assert leer_publicacion(cfg, None).model_dump() == {
        "publicacion": None,
        "error": None,
    }
    assert leer_publicacion(cfg, carpeta_publicacion).model_dump() == {
        "publicacion": None,
        "error": None,
    }


def test_archivo_mayor_de_cinco_mb_devuelve_error(carpeta_publicacion, cfg):
    (carpeta_publicacion / "publicar" / "publicacion.json").write_bytes(
        b" " * (5 * 1024 * 1024 + 1)
    )

    lectura = leer_publicacion(cfg, carpeta_publicacion)

    assert lectura.publicacion is None
    assert lectura.error == "No se ha podido leer publicacion.json"


def test_ruta_publica_publicar_usa_el_formato_de_medios(carpeta_publicacion, cfg):
    assert ruta_publica_publicar(
        cfg,
        carpeta_publicacion,
        "1-youtube-leccion/miniatura-A-ejemplo.jpg",
    ) == (
        "cursos/REACT/04-importar-y-exportar/publicar/"
        "1-youtube-leccion/miniatura-A-ejemplo.jpg"
    )
    assert ruta_publica_publicar(cfg, carpeta_publicacion, "../secreto.jpg") is None


@pytest.mark.parametrize(
    ("red", "textos", "campo", "limite"),
    [
        ("youtube", TextosRed(titulos=["x" * 101]), "titulos", "100"),
        ("youtube", TextosRed(descripcion="x" * 5001), "descripcion", "5000"),
        (
            "youtube",
            TextosRed(etiquetas=["x" * 499, "y"]),
            "etiquetas",
            "500",
        ),
        ("instagram", TextosRed(texto="x" * 2201), "texto", "2200"),
        ("tiktok", TextosRed(texto="x" * 2201), "texto", "2200"),
        ("linkedin", TextosRed(texto="x" * 3001), "texto", "3000"),
        (
            "youtube",
            TextosRed(comentario_fijado="x" * 10001),
            "comentario_fijado",
            "10000",
        ),
        ("youtube", TextosRed(ajustes=["x"] * 31), "ajustes", "30"),
        ("youtube", TextosRed(ajustes=["x" * 301]), "ajustes", "300"),
    ],
)
def test_validar_textos_nombra_el_campo_y_el_limite(red, textos, campo, limite):
    with pytest.raises(ValueError) as error:
        validar_textos(red, textos)

    assert campo in str(error.value)
    assert limite in str(error.value)


def test_limite_despues_de_publicar_invalida_el_archivo(carpeta_publicacion, cfg):
    datos = _publicacion_valida()
    datos["despues_de_publicar"] = ["x"] * 31
    _escribir_publicacion(carpeta_publicacion, datos)

    lectura = leer_publicacion(cfg, carpeta_publicacion)

    assert lectura.publicacion is None
    assert lectura.error == "No se ha podido leer publicacion.json"
