import json

import pytest

from estudio_api.lectura import _leer_json, leer_cursos, leer_leccion, leer_lecciones
from estudio_api.rutas import ruta_segura


def test_solo_cursos_con_lecciones(cfg):
    assert [curso.id for curso in leer_cursos(cfg)] == ["react"]


def test_curso_usa_nombre_del_primer_guion(cfg):
    assert leer_cursos(cfg)[0].nombre == "React"


def test_leccion_sin_guion_aparece(cfg):
    lecciones = leer_lecciones(cfg, "react")

    assert [leccion.numero for leccion in lecciones] == [4, 5]
    assert lecciones[1].slug == "otra"


def test_leccion_con_numero_de_tres_cifras_aparece(cfg):
    (cfg.cursos_dir / "REACT" / "100-ejemplo-ficticio").mkdir()

    lecciones = leer_lecciones(cfg, "react")

    assert 100 in [leccion.numero for leccion in lecciones]


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


def test_guion_con_json_roto_se_ignora_sin_romper(cfg):
    (cfg.estudio_dir / "lecciones" / "react-06.json").write_text(
        "{json roto",
        encoding="utf-8",
    )

    assert [leccion.numero for leccion in leer_lecciones(cfg, "react")] == [4, 5]


def test_guion_que_no_es_objeto_se_ignora_sin_romper(cfg):
    (cfg.estudio_dir / "lecciones" / "react-06.json").write_text(
        json.dumps(["no", "es", "un", "objeto"]),
        encoding="utf-8",
    )

    assert [leccion.numero for leccion in leer_lecciones(cfg, "react")] == [4, 5]


@pytest.mark.parametrize("error", [RecursionError, ValueError])
def test_error_al_decodificar_json_se_ignora(tmp_path, monkeypatch, error):
    ruta = tmp_path / "datos.json"
    ruta.write_text("{}", encoding="utf-8")

    def fallar(_archivo):
        raise error

    monkeypatch.setattr("estudio_api.lectura.json.load", fallar)

    assert _leer_json(ruta) is None


def test_json_mayor_de_cinco_mb_no_se_lee(tmp_path, monkeypatch):
    ruta = tmp_path / "demasiado-grande.json"
    ruta.write_bytes(b" " * (5 * 1024 * 1024 + 1))

    def no_debe_leerse(_archivo):
        raise AssertionError("json.load no debe recibir archivos mayores de 5 MB")

    monkeypatch.setattr("estudio_api.lectura.json.load", no_debe_leerse)

    assert _leer_json(ruta) is None


def test_leccion_sin_montaje_no_rompe(cfg):
    montaje = cfg.estudio_dir / "public" / "lecciones" / "react-04" / "montaje.json"
    montaje.unlink()

    leccion = leer_leccion(cfg, "react", 4)

    assert leccion is not None
    assert leccion.duracion_s is None
    assert [
        (escena.id, escena.textos, escena.inicio_s, escena.duracion_s)
        for escena in leccion.escenas
    ] == [
        ("E01", ["Texto ficticio de apertura."], None, None),
        ("E03", ["Explicación ficticia."], None, None),
        ("E04", [], None, None),
    ]


def test_enlace_de_curso_que_apunta_fuera_se_ignora(cfg, tmp_path):
    curso_fuera = tmp_path / "fuera" / "MALICIOSO" / "01-secreto"
    curso_fuera.mkdir(parents=True)
    (cfg.cursos_dir / "MALICIOSO").symlink_to(
        curso_fuera.parent, target_is_directory=True
    )

    cursos = leer_cursos(cfg)

    assert [curso.id for curso in cursos] == ["react"]


def test_guion_con_carpeta_que_contiene_padre_se_ignora(cfg, tmp_path):
    carpeta_fuera = tmp_path / "06-fuera"
    carpeta_fuera.mkdir()
    guion = {
        "ficha": "React",
        "numero": 6,
        "titulo": "No debe leerse",
        "carpeta": "REACT/../06-fuera",
        "escenas": [],
    }
    (cfg.estudio_dir / "lecciones" / "react-06.json").write_text(
        json.dumps(guion),
        encoding="utf-8",
    )

    assert [leccion.numero for leccion in leer_lecciones(cfg, "react")] == [4, 5]


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


@pytest.mark.parametrize(
    "fps",
    [float("inf"), float("nan"), 0, -1, 0.000_001, 1001],
)
def test_fps_no_finito_o_absurdo_se_trata_como_desconocido(cfg, fps):
    montaje = cfg.estudio_dir / "public" / "lecciones" / "react-04" / "montaje.json"
    datos = json.loads(montaje.read_text(encoding="utf-8"))
    datos["fps"] = fps
    montaje.write_text(json.dumps(datos), encoding="utf-8")

    leccion = leer_leccion(cfg, "react", 4)

    assert leccion is not None
    assert leccion.duracion_s is None
    assert all(escena.inicio_s is None for escena in leccion.escenas)
    leccion.model_dump_json()


@pytest.mark.parametrize(
    "duracion",
    [float("inf"), float("nan"), 0, -1, 10**20],
)
def test_duracion_no_finita_o_absurda_se_trata_como_desconocida(cfg, duracion):
    montaje = cfg.estudio_dir / "public" / "lecciones" / "react-04" / "montaje.json"
    datos = json.loads(montaje.read_text(encoding="utf-8"))
    datos["duracion"] = duracion
    montaje.write_text(json.dumps(datos), encoding="utf-8")

    leccion = leer_leccion(cfg, "react", 4)

    assert leccion is not None
    assert leccion.duracion_s is None
    leccion.model_dump_json()


def test_duracion_de_escena_no_finita_se_trata_como_desconocida(cfg):
    montaje = cfg.estudio_dir / "public" / "lecciones" / "react-04" / "montaje.json"
    datos = json.loads(montaje.read_text(encoding="utf-8"))
    datos["escenas"][1]["duracion"] = float("inf")
    montaje.write_text(json.dumps(datos), encoding="utf-8")

    leccion = leer_leccion(cfg, "react", 4)

    assert leccion is not None
    escena = next(escena for escena in leccion.escenas if escena.id == "E03")
    assert escena.inicio_s is None
    assert escena.duracion_s is None
    leccion.model_dump_json()


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


def test_ids_estables_de_leccion_reel_unico_y_short(cfg):
    verticales = (
        cfg.cursos_dir
        / "REACT"
        / "04-importar-y-exportar"
        / "publicar"
        / "2-shorts-y-reels"
    )
    (verticales / "short-2-ejemplo.mp4").rename(
        verticales / "short-3-contenido-inventado.mp4"
    )

    leccion = leer_leccion(cfg, "react", 4)

    assert leccion is not None
    assert [pieza.id for pieza in leccion.piezas] == [
        "leccion",
        "reel-salida",
        "short-3",
    ]


def test_renombrar_reel_unico_no_cambia_su_id(cfg):
    verticales = (
        cfg.cursos_dir
        / "REACT"
        / "04-importar-y-exportar"
        / "publicar"
        / "2-shorts-y-reels"
    )
    (verticales / "reel-salida.mp4").rename(
        verticales / "reel-nombre-completamente-inventado.mp4"
    )

    leccion = leer_leccion(cfg, "react", 4)

    reel = next(pieza for pieza in leccion.piezas if pieza.tipo == "reel")
    assert reel.id == "reel-salida"
    assert reel.video.endswith("/reel-nombre-completamente-inventado.mp4")


def test_reel_unico_recibe_portadas_aunque_no_coincidan_los_nombres(cfg):
    verticales = (
        cfg.cursos_dir
        / "REACT"
        / "04-importar-y-exportar"
        / "publicar"
        / "2-shorts-y-reels"
    )
    (verticales / "reel-salida.mp4").unlink()
    (verticales / "reel-planeta-naranja.mp4").write_bytes(b"reel")
    (verticales / "portada-reel-planeta-marco.jpg").write_bytes(b"portada")

    leccion = leer_leccion(cfg, "react", 4)

    reel = next(pieza for pieza in leccion.piezas if pieza.tipo == "reel")
    assert [ruta.rsplit("/", 1)[-1] for ruta in reel.portadas] == [
        "portada-reel-planeta-marco.jpg"
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
    (verticales / "reel-bosque-azul.mp4").write_bytes(b"reel A")
    (verticales / "reel-planeta-rojo.mp4").write_bytes(b"reel B")
    (verticales / "portada-reel-bosque-azul-A-marco.jpg").write_bytes(b"portada A")
    (verticales / "portada-reel-planeta-rojo-B-circulo.jpg").write_bytes(b"portada B")

    leccion = leer_leccion(cfg, "react", 4)

    reels = {
        pieza.id: [ruta.rsplit("/", 1)[-1] for ruta in pieza.portadas]
        for pieza in leccion.piezas
        if pieza.tipo == "reel"
    }
    assert reels == {
        "reel-salida-1": ["portada-reel-bosque-azul-A-marco.jpg"],
        "reel-salida-2": ["portada-reel-planeta-rojo-B-circulo.jpg"],
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
        "previa-v1.mp4",
        "previa-v2.mp4",
        "previa-v10.mp4",
    ]


def test_ignora_anteriores_y_descartadas(cfg):
    leccion = leer_leccion(cfg, "react", 4)

    assert leccion is not None
    videos = [pieza.video for pieza in leccion.piezas if pieza.video]
    assert all("anterior" not in video for video in videos)
    assert all("descartad" not in video for video in videos)


def test_estado_calculado_desde_los_archivos(cfg):
    leccion = leer_leccion(cfg, "react", 4)

    assert leccion is not None
    assert leccion.estado.guion is True
    assert leccion.estado.voz.hechas == 0
    assert leccion.estado.voz.total == 1
    assert leccion.estado.camara.hechas == 0
    assert leccion.estado.camara.total == 1
    assert leccion.estado.video_final is True
    assert leccion.estado.previa.endswith("/previa/previa-v10.mp4")
    assert leccion.estado.publicado == {
        "youtube": False,
        "instagram": False,
        "tiktok": False,
        "linkedin": False,
    }


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
