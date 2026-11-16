import json

import pytest

from estudio_api.lectura import leer_cursos, leer_leccion, leer_lecciones
from estudio_api.rutas import ruta_segura


def test_solo_cursos_con_lecciones(cfg):
    assert [curso.id for curso in leer_cursos(cfg)] == ["react"]


def test_curso_usa_nombre_del_primer_guion(cfg):
    assert leer_cursos(cfg)[0].nombre == "React"


def test_leccion_sin_guion_aparece(cfg):
    lecciones = leer_lecciones(cfg, "react")

    assert [leccion.numero for leccion in lecciones] == [4, 5]
    assert lecciones[1].slug == "otra"


def test_guion_sin_carpeta_aparece(cfg):
    guion = {
        "ficha": "React",
        "numero": 6,
        "titulo": "Solo en el estudio",
        "subtitulo": "Ejemplo ficticio",
        "carpeta": "REACT/06-solo-guion",
        "escenas": [],
        "ganchos": [],
    }
    (cfg.estudio_dir / "lecciones" / "react-06.json").write_text(
        json.dumps(guion),
        encoding="utf-8",
    )

    lecciones = leer_lecciones(cfg, "react")

    assert [leccion.numero for leccion in lecciones] == [4, 5, 6]
    assert leer_leccion(cfg, "react", 6).slug == "solo-guion"


def test_escenas_con_textos_y_tiempos(cfg):
    leccion = leer_leccion(cfg, "react", 4)

    assert leccion is not None
    assert leccion.duracion_s == 6.0
    assert leccion.escenas[0].textos == ["Texto ficticio de apertura."]
    assert (
        leccion.escenas[1].id,
        leccion.escenas[1].inicio_s,
        leccion.escenas[1].duracion_s,
    ) == ("E03", 2.0, 3.0)
    assert leccion.escenas[2].textos == []


def test_piezas_y_portadas(cfg):
    leccion = leer_leccion(cfg, "react", 4)

    assert leccion is not None
    assert [pieza.tipo for pieza in leccion.piezas] == [
        "leccion",
        "reel",
        "short",
    ]
    assert len(leccion.piezas[0].portadas) == 1
    assert len(leccion.piezas[2].portadas) == 2
    assert all(ruta.startswith("cursos/") for ruta in leccion.piezas[2].portadas)


def test_reel_unico_recibe_portadas_aunque_no_coincidan_los_nombres(cfg):
    verticales = (
        cfg.cursos_dir
        / "REACT"
        / "04-importar-y-exportar"
        / "publicar"
        / "2-shorts-y-reels"
    )
    (verticales / "reel-salida.mp4").unlink()
    (verticales / "reel-nueva-leccion-4-pagina-en-blanco.mp4").write_bytes(b"reel")
    (verticales / "portada-reel-nueva-leccion-4-caja.jpg").write_bytes(b"portada")

    leccion = leer_leccion(cfg, "react", 4)

    reel = next(pieza for pieza in leccion.piezas if pieza.tipo == "reel")
    assert [ruta.rsplit("/", 1)[-1] for ruta in reel.portadas] == [
        "portada-reel-nueva-leccion-4-caja.jpg"
    ]


def test_varios_reels_reparten_portadas_por_prefijo_comun_mas_largo(cfg):
    verticales = (
        cfg.cursos_dir
        / "REACT"
        / "04-importar-y-exportar"
        / "publicar"
        / "2-shorts-y-reels"
    )
    (verticales / "reel-salida.mp4").unlink()
    (verticales / "reel-ya-esta-la-leccion-2.mp4").write_bytes(b"reel A")
    (verticales / "reel-nueva-leccion-2.mp4").write_bytes(b"reel B")
    (verticales / "portada-reel-ya-esta-la-leccion-2-A-para.jpg").write_bytes(
        b"portada A"
    )
    (verticales / "portada-reel-nueva-leccion-2-B-caja.jpg").write_bytes(
        b"portada B"
    )

    leccion = leer_leccion(cfg, "react", 4)

    reels = {
        pieza.id: [ruta.rsplit("/", 1)[-1] for ruta in pieza.portadas]
        for pieza in leccion.piezas
        if pieza.tipo == "reel"
    }
    assert reels == {
        "reel-nueva-leccion-2": ["portada-reel-nueva-leccion-2-B-caja.jpg"],
        "reel-ya-esta-la-leccion-2": [
            "portada-reel-ya-esta-la-leccion-2-A-para.jpg"
        ],
    }


def test_portada_de_reel_anterior_se_ignora(cfg):
    verticales = (
        cfg.cursos_dir
        / "REACT"
        / "04-importar-y-exportar"
        / "publicar"
        / "2-shorts-y-reels"
    )
    (verticales / "portada-reel-salida-A.jpg").write_bytes(b"actual")
    (verticales / "portada-reel-salida-anterior-A.jpg").write_bytes(b"anterior")

    leccion = leer_leccion(cfg, "react", 4)

    reel = next(pieza for pieza in leccion.piezas if pieza.tipo == "reel")
    assert [ruta.rsplit("/", 1)[-1] for ruta in reel.portadas] == [
        "portada-reel-salida-A.jpg"
    ]


def test_previas_ordenadas_por_numero_de_version(cfg):
    leccion = leer_leccion(cfg, "react", 4)

    assert leccion is not None
    assert [ruta.rsplit("/", 1)[-1] for ruta in leccion.previas] == [
        "previa-v2.mp4",
        "previa-v10.mp4",
    ]


def test_ignora_anteriores_y_descartadas(cfg):
    leccion = leer_leccion(cfg, "react", 4)

    assert leccion is not None
    videos = [pieza.video for pieza in leccion.piezas if pieza.video]
    assert all("anterior" not in video for video in videos)
    assert all("descartad" not in video for video in videos)


def test_estado_vacio_por_defecto(cfg):
    leccion = leer_leccion(cfg, "react", 4)

    assert leccion is not None
    assert leccion.estado.guion is False
    assert leccion.estado.voz.hechas == leccion.estado.voz.total == 0
    assert leccion.estado.camara.hechas == leccion.estado.camara.total == 0
    assert leccion.estado.publicado == {}


def test_curso_invalido_no_se_lee(cfg):
    assert leer_lecciones(cfg, "../react") == []
    assert leer_leccion(cfg, "../react", 4) is None


def test_numero_fuera_de_rango_no_se_lee(cfg):
    assert leer_leccion(cfg, "react", 0) is None
    assert leer_leccion(cfg, "react", 1000) is None


def test_ruta_segura_rechaza_salida(tmp_path):
    with pytest.raises(ValueError):
        ruta_segura(tmp_path, "../x")


def test_ruta_segura_rechaza_segmento_padre_aunque_no_escape(tmp_path):
    with pytest.raises(ValueError):
        ruta_segura(tmp_path, "carpeta", "..", "archivo.mp4")


def test_ruta_segura_rechaza_ruta_absoluta(tmp_path):
    with pytest.raises(ValueError):
        ruta_segura(tmp_path, "/etc/passwd")


def test_ruta_segura_rechaza_enlace_fuera(tmp_path):
    raiz = tmp_path / "raiz"
    raiz.mkdir()
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    (raiz / "enlace").symlink_to(fuera, target_is_directory=True)

    with pytest.raises(ValueError):
        ruta_segura(raiz, "enlace", "archivo.mp4")
