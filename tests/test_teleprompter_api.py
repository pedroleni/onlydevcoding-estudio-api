import hashlib
import json
import os
import sys
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from estudio_api.app import crear_app
from estudio_api.decisiones import abrir_bd
from estudio_api.teleprompter import comando_previa
from estudio_api.trabajos import esperar, leer_trabajo
from tests.ayudas import TOKEN

CABECERAS = {"X-Estudio-Token": TOKEN}
RUTA_TELEPROMPTER = "/api/cursos/react/lecciones/4/teleprompter"
RUTA_PREVIA = "/api/cursos/react/lecciones/4/previa-grabacion"


@pytest.fixture
def teleprompter(cfg):
    guion = {
        "ficha": "React",
        "numero": 4,
        "titulo": "Lección ficticia",
        "carpeta": "REACT/04-importar-y-exportar",
        "escenas": [
            {
                "id": "E01",
                "modo": "camara",
                "titulo": "Presentación",
                "cues": [{"texto": "Texto de cámara."}],
                "puntos": ["Primer punto", "Segundo punto"],
            },
            {
                "id": "E02",
                "modo": "animacion",
                "titulo": "Animación",
                "cues": [{"texto": "Texto que no se muestra."}],
            },
            {
                "id": "E03",
                "modo": "voz",
                "titulo": "Explicación",
                "cues": [
                    {"texto": "Primera frase.", "pausa": 1.25},
                    {"texto": "Segunda frase.", "pausa": 99},
                ],
            },
            {
                "id": "E04",
                "modo": "voz",
                "titulo": "Cierre",
                "cues": [{"texto": "Última frase."}],
            },
        ],
    }
    bytes_guion = json.dumps(guion, ensure_ascii=False).encode("utf-8")
    (cfg.estudio_dir / "lecciones" / "react-04.json").write_bytes(bytes_guion)

    grabaciones = cfg.cursos_dir / "REACT" / "04-importar-y-exportar" / "grabaciones"
    grabaciones.mkdir()
    toma = grabaciones / "E03.wav"
    toma.write_bytes(b"RIFFdatos-ficticios-WAVE")

    ruta_montaje = (
        cfg.estudio_dir / "public" / "lecciones" / "react-04" / "montaje.json"
    )
    montaje = {
        "fps": 30,
        "duracion": 300,
        "escenas": [
            {
                "id": "E01",
                "duracion": 60,
                "cues": [{"desde": 0}, {"desde": 20}],
            },
            {
                "id": "E03",
                "duracion": 90,
                "cues": [{"desde": 5}, {}],
            },
            {"id": "E04", "duracion": 150, "cues": []},
        ],
    }
    ruta_montaje.write_text(json.dumps(montaje), encoding="utf-8")

    directorio_previa = cfg.estudio_dir / "out" / "previas-grabacion"
    directorio_previa.mkdir(parents=True)
    ruta_previa = directorio_previa / "react-04.mp4"
    ruta_previa.write_bytes(b"0123456789")
    os.utime(ruta_previa, ns=(1_000_000_000, 1_000_000_000))
    os.utime(ruta_montaje, ns=(2_000_000_000, 2_000_000_000))

    config = cfg.model_copy(update={"token_escritura": TOKEN})
    with TestClient(
        crear_app(config),
        base_url="http://127.0.0.1:8000",
    ) as cliente:
        yield config, cliente, bytes_guion, toma, ruta_montaje, ruta_previa


def test_comando_previa_es_la_lista_cerrada_exacta(tmp_path):
    temporal = tmp_path / "react-04.generando.mp4"

    assert comando_previa("/ruta-ficticia/npx", temporal, "react-04") == [
        "/ruta-ficticia/npx",
        "--no",
        "remotion",
        "render",
        "src/index.ts",
        "Leccion",
        str(temporal),
        '--props={"leccion":"react-04"}',
        "--scale=0.5",
        "--muted",
        "--crf=30",
    ]


def test_get_teleprompter_reune_guion_tomas_montaje_y_previa(teleprompter):
    _, cliente, bytes_guion, toma, _, ruta_previa = teleprompter

    respuesta = cliente.get(RUTA_TELEPROMPTER)

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["curso"] == "react"
    assert datos["numero"] == 4
    assert datos["guion"] == "react-04"
    assert datos["titulo"] == "Lección ficticia"
    assert datos["version"] == hashlib.sha256(bytes_guion).hexdigest()
    assert [escena["id"] for escena in datos["escenas"]] == ["E01", "E03", "E04"]
    assert datos["escenas"][0]["puntos"] == ["Primer punto", "Segundo punto"]
    assert datos["escenas"][0]["grabada"] is False
    assert datos["escenas"][1]["grabada"] is True
    assert datos["escenas"][1]["toma"] == (
        "cursos/REACT/04-importar-y-exportar/grabaciones/E03.wav"
    )
    assert datos["escenas"][1]["version_toma"] == toma.stat().st_mtime_ns
    assert datos["escenas"][1]["cues"] == [
        {"texto": "Primera frase.", "pausa": 1.25},
        {"texto": "Segunda frase.", "pausa": 30.0},
    ]
    assert datos["escenas"][2]["cues"] == [{"texto": "Última frase.", "pausa": 0.0}]
    assert datos["montaje"] == {
        "fps": 30.0,
        "duracion": 300,
        "escenas": [
            {
                "id": "E01",
                "modo": "camara",
                "inicio": 0,
                "duracion": 60,
                "cues": [0, 20],
            },
            {
                "id": "E03",
                "modo": "voz",
                "inicio": 60,
                "duracion": 90,
                "cues": [5, 0],
            },
            {
                "id": "E04",
                "modo": "voz",
                "inicio": 150,
                "duracion": 150,
                "cues": [],
            },
        ],
    }
    assert datos["previa"] == {
        "ruta": "estudio/out/previas-grabacion/react-04.mp4",
        "existe": True,
        "desactualizada": True,
        "version": ruta_previa.stat().st_mtime_ns,
        "trabajo": None,
    }


def test_montaje_roto_se_devuelve_como_null(teleprompter):
    _, cliente, _, _, ruta_montaje, _ = teleprompter
    ruta_montaje.write_text("{roto", encoding="utf-8")

    respuesta = cliente.get(RUTA_TELEPROMPTER)

    assert respuesta.status_code == 200
    assert respuesta.json()["montaje"] is None


@pytest.mark.parametrize("escenas", [None, 5, {"E03": {"modo": "voz"}}])
def test_guion_con_escenas_que_no_son_lista_no_provoca_500_en_get_ni_post(
    teleprompter, escenas
):
    config, cliente, _, _, _, _ = teleprompter
    ruta_guion = config.estudio_dir / "lecciones" / "react-04.json"
    guion = json.loads(ruta_guion.read_text(encoding="utf-8"))
    guion["escenas"] = escenas
    ruta_guion.write_text(json.dumps(guion), encoding="utf-8")

    respuesta_get = cliente.get(RUTA_TELEPROMPTER)
    respuesta_post = cliente.post(RUTA_PREVIA, headers=CABECERAS, json={})

    assert respuesta_get.status_code == 200
    assert respuesta_get.json()["escenas"] == []
    assert respuesta_get.json()["montaje"] is None
    assert respuesta_post.status_code == 409
    assert respuesta_post.json()["detail"] == "Esta lección aún no tiene montaje"


@pytest.mark.parametrize(
    "montaje",
    [
        {
            "fps": 30,
            "duracion": 1,
            "escenas": [{"id": [], "duracion": 1}],
        },
        {"fps": 10**400, "duracion": 1, "escenas": []},
        {"fps": float("nan"), "duracion": 1, "escenas": []},
        {"fps": 30, "duracion": 10**400, "escenas": []},
        {
            "fps": 30,
            "duracion": 1,
            "escenas": [{"id": "E01", "duracion": 1, "cues": {}}],
        },
        {
            "fps": 30,
            "duracion": 1,
            "escenas": [{"id": "E01", "duracion": 1, "cues": [{"desde": []}]}],
        },
    ],
)
def test_montaje_con_estructura_danada_no_provoca_500_en_get_ni_post(
    teleprompter, montaje
):
    _, cliente, _, _, ruta_montaje, _ = teleprompter
    ruta_montaje.write_text(json.dumps(montaje), encoding="utf-8")

    respuesta_get = cliente.get(RUTA_TELEPROMPTER)
    respuesta_post = cliente.post(RUTA_PREVIA, headers=CABECERAS, json={})

    assert respuesta_get.status_code == 200
    assert respuesta_get.json()["montaje"] is None
    assert respuesta_post.status_code == 409
    assert respuesta_post.json()["detail"] == "Esta lección aún no tiene montaje"


def test_get_usa_el_nombre_real_del_unico_guion_de_tres_digitos(teleprompter):
    config, cliente, _, _, _, _ = teleprompter
    ruta_dos_digitos = config.estudio_dir / "lecciones" / "react-04.json"
    ruta_tres_digitos = config.estudio_dir / "lecciones" / "react-004.json"
    ruta_dos_digitos.replace(ruta_tres_digitos)

    respuesta = cliente.get(RUTA_TELEPROMPTER)

    assert respuesta.status_code == 200
    assert respuesta.json()["guion"] == "react-004"


def test_textos_y_version_salen_del_mismo_guion_elegido(teleprompter):
    config, cliente, _, _, _, _ = teleprompter
    ruta_tres_digitos = config.estudio_dir / "lecciones" / "react-004.json"
    guion = json.loads(
        (config.estudio_dir / "lecciones" / "react-04.json").read_text(encoding="utf-8")
    )
    guion["titulo"] = "Versión de tres dígitos"
    guion["escenas"][0]["cues"] = [{"texto": "Texto del archivo elegido."}]
    bytes_tres_digitos = json.dumps(guion, ensure_ascii=False).encode("utf-8")
    ruta_tres_digitos.write_bytes(bytes_tres_digitos)

    respuesta = cliente.get(RUTA_TELEPROMPTER)

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["guion"] == "react-004"
    assert datos["titulo"] == "Versión de tres dígitos"
    assert datos["escenas"][0]["cues"][0]["texto"] == "Texto del archivo elegido."
    assert datos["version"] == hashlib.sha256(bytes_tres_digitos).hexdigest()


def test_get_lee_los_bytes_del_guion_una_sola_vez(teleprompter, monkeypatch):
    config, cliente, _, _, _, _ = teleprompter
    ruta_guion = config.estudio_dir / "lecciones" / "react-04.json"
    open_real = Path.open
    lecturas = 0

    def abrir_contando(ruta, *args, **kwargs):
        nonlocal lecturas
        if ruta == ruta_guion:
            lecturas += 1
        return open_real(ruta, *args, **kwargs)

    monkeypatch.setattr(Path, "open", abrir_contando)

    assert cliente.get(RUTA_TELEPROMPTER).status_code == 200
    assert lecturas == 1


def test_get_filtra_ids_de_escena_fuera_del_patron(teleprompter):
    config, cliente, _, _, _, _ = teleprompter
    ruta_guion = config.estudio_dir / "lecciones" / "react-04.json"
    guion = json.loads(ruta_guion.read_text(encoding="utf-8"))
    guion["escenas"].extend(
        [
            {"id": "intro", "modo": "voz", "cues": [{"texto": "No sale."}]},
            {"id": "E123", "modo": "camara", "cues": []},
        ]
    )
    ruta_guion.write_text(json.dumps(guion), encoding="utf-8")

    respuesta = cliente.get(RUTA_TELEPROMPTER)

    assert respuesta.status_code == 200
    assert [escena["id"] for escena in respuesta.json()["escenas"]] == [
        "E01",
        "E03",
        "E04",
    ]


def test_previa_de_grabacion_se_sirve_con_range(teleprompter):
    _, cliente, _, _, _, _ = teleprompter

    respuesta = cliente.get(
        "/api/medios",
        params={"ruta": "estudio/out/previas-grabacion/react-04.mp4"},
        headers={"Range": "bytes=2-5"},
    )

    assert respuesta.status_code == 206
    assert respuesta.content == b"2345"
    assert respuesta.headers["content-type"] == "video/mp4"


def test_post_lanza_el_trabajo_y_coloca_la_previa(teleprompter, monkeypatch):
    config, cliente, _, _, _, ruta_previa = teleprompter
    ruta_previa.unlink()

    monkeypatch.setattr("estudio_api.rutas_teleprompter.shutil.which", lambda _: "/npx")

    def comando_falso(_npx, temporal, _guion):
        return [
            sys.executable,
            "-c",
            "import pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(b'video')",
            str(temporal),
        ]

    monkeypatch.setattr("estudio_api.rutas_teleprompter.comando_previa", comando_falso)

    respuesta = cliente.post(RUTA_PREVIA, headers=CABECERAS, json={})

    assert respuesta.status_code == 202
    trabajo_id = respuesta.json()["id"]
    esperar(trabajo_id, 5)
    consulta = cliente.get(f"/api/trabajos/{trabajo_id}")
    assert consulta.status_code == 200
    assert consulta.json()["estado"] == "hecho"
    assert ruta_previa.read_bytes() == b"video"
    with closing(abrir_bd(config.bd_ruta)) as bd:
        assert leer_trabajo(bd, trabajo_id).estado == "hecho"


def test_segundo_post_mientras_corre_devuelve_409(teleprompter, monkeypatch):
    config, cliente, _, _, _, _ = teleprompter
    continuar = config.estudio_dir / "continuar-render"
    monkeypatch.setattr("estudio_api.rutas_teleprompter.shutil.which", lambda _: "/npx")

    def comando_lento(_npx, temporal, _guion):
        return [
            sys.executable,
            "-c",
            (
                "import pathlib,sys,time; "
                "continuar=pathlib.Path(sys.argv[1]); "
                "salida=pathlib.Path(sys.argv[2]); "
                "\nwhile not continuar.exists(): time.sleep(.01)\n"
                "salida.write_bytes(b'video')"
            ),
            str(continuar),
            str(temporal),
        ]

    monkeypatch.setattr("estudio_api.rutas_teleprompter.comando_previa", comando_lento)
    primero = cliente.post(RUTA_PREVIA, headers=CABECERAS, json={})
    try:
        segundo = cliente.post(RUTA_PREVIA, headers=CABECERAS, json={})

        assert primero.status_code == 202
        assert segundo.status_code == 409
        assert segundo.json()["detail"] == "Ya hay un trabajo en marcha"
    finally:
        continuar.touch()
        if primero.status_code == 202:
            esperar(primero.json()["id"], 5)


def test_post_sin_npx_devuelve_503(teleprompter, monkeypatch):
    _, cliente, _, _, _, _ = teleprompter
    monkeypatch.setattr("estudio_api.rutas_teleprompter.shutil.which", lambda _: None)

    respuesta = cliente.post(RUTA_PREVIA, headers=CABECERAS, json={})

    assert respuesta.status_code == 503
    assert respuesta.json()["detail"] == "No se encuentra npx en el PATH de la API"


def test_post_sin_montaje_devuelve_409(teleprompter, monkeypatch):
    _, cliente, _, _, ruta_montaje, _ = teleprompter
    ruta_montaje.unlink()
    monkeypatch.setattr("estudio_api.rutas_teleprompter.shutil.which", lambda _: "/npx")

    respuesta = cliente.post(RUTA_PREVIA, headers=CABECERAS, json={})

    assert respuesta.status_code == 409
    assert respuesta.json()["detail"] == "Esta lección aún no tiene montaje"


def test_post_con_ruta_de_previa_invalida_devuelve_404(teleprompter, monkeypatch):
    _, cliente, _, _, _, _ = teleprompter
    monkeypatch.setattr("estudio_api.rutas_teleprompter.shutil.which", lambda _: "/npx")
    monkeypatch.setattr("estudio_api.rutas_teleprompter.rutas_previa", lambda *_: None)

    respuesta = cliente.post(RUTA_PREVIA, headers=CABECERAS, json={})

    assert respuesta.status_code == 404


def test_post_si_no_puede_preparar_la_carpeta_devuelve_503(teleprompter, monkeypatch):
    _, cliente, _, _, _, _ = teleprompter
    mkdir_real = Path.mkdir

    def mkdir_con_fallo(ruta, *args, **kwargs):
        if ruta.name == "previas-grabacion":
            raise OSError("fallo de disco ficticio")
        return mkdir_real(ruta, *args, **kwargs)

    monkeypatch.setattr("estudio_api.rutas_teleprompter.shutil.which", lambda _: "/npx")
    monkeypatch.setattr(Path, "mkdir", mkdir_con_fallo)

    respuesta = cliente.post(RUTA_PREVIA, headers=CABECERAS, json={})

    assert respuesta.status_code == 503
    assert respuesta.json()["detail"] == (
        "No se puede preparar la carpeta de la vista previa"
    )


def test_post_rechaza_cuerpo_con_campos_extra(teleprompter):
    _, cliente, _, _, _, _ = teleprompter

    respuesta = cliente.post(RUTA_PREVIA, headers=CABECERAS, json={"comando": "otro"})

    assert respuesta.status_code == 422


def test_post_sin_token_devuelve_401(teleprompter):
    _, cliente, _, _, _, _ = teleprompter

    respuesta = cliente.post(RUTA_PREVIA, json={})

    assert respuesta.status_code == 401


@pytest.mark.parametrize(
    "ruta",
    [
        "/api/cursos/react/lecciones/0/previa-grabacion",
        "/api/cursos/%2E%2E/lecciones/4/previa-grabacion",
    ],
)
def test_post_rechaza_identificadores_invalidos_sin_error_500(teleprompter, ruta):
    _, cliente, _, _, _, _ = teleprompter

    respuesta = cliente.post(ruta, headers=CABECERAS, json={})

    assert respuesta.status_code == 422


def test_get_teleprompter_y_trabajo_inexistentes_devuelven_404(teleprompter):
    _, cliente, _, _, _, _ = teleprompter

    assert (
        cliente.get("/api/cursos/no-existe/lecciones/4/teleprompter").status_code == 404
    )
    assert cliente.get("/api/trabajos/999").status_code == 404
    assert cliente.get("/api/trabajos/0").status_code == 422


def test_toma_de_camara_del_estudio_usa_el_nombre_real_del_guion(teleprompter):
    config, cliente, _, _, _, _ = teleprompter
    lecciones = config.estudio_dir / "lecciones"
    (lecciones / "react-04.json").replace(lecciones / "react-004.json")
    grabaciones = config.estudio_dir / "public" / "grabaciones" / "react-004"
    grabaciones.mkdir(parents=True)
    (grabaciones / "E01.mov").write_bytes(b"toma ficticia")

    teleprompter_leido = cliente.get(RUTA_TELEPROMPTER).json()
    ficha = cliente.get("/api/cursos/react/lecciones/4").json()

    assert teleprompter_leido["escenas"][0]["id"] == "E01"
    assert teleprompter_leido["escenas"][0]["grabada"] is True
    assert ficha["estado"]["camara"] == {"hechas": 1, "total": 1}


def test_get_teleprompter_inexistente_explica_el_404(teleprompter):
    _, cliente, _, _, _, _ = teleprompter

    respuesta = cliente.get("/api/cursos/react/lecciones/9/teleprompter")

    assert respuesta.status_code == 404
    assert respuesta.json() == {"detail": "La lección no existe o no tiene guion"}
