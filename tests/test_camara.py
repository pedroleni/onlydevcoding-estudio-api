import json
import os

import pytest

RUTA = "/api/cursos/react/lecciones/4/camara"


def _guion(cfg, escenas, ganchos):
    ruta = cfg.estudio_dir / "lecciones" / "react-04.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["escenas"] = escenas
    datos["ganchos"] = ganchos
    ruta.write_text(json.dumps(datos), encoding="utf-8")


def _escritura(ruta, contenido=b"x", mtime_ns=None):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(contenido)
    if mtime_ns is not None:
        os.utime(ruta, ns=(mtime_ns, mtime_ns))


def _shorts(cfg, entregados):
    carpeta = cfg.estudio_dir / "shorts" / "l4"
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "shorts.json").write_text(
        json.dumps({"leccion": "react-04", "ganchosEntregados": entregados}),
        encoding="utf-8",
    )


def _escenas():
    return [
        {"id": "E01", "modo": "camara", "titulo": "Con toma", "cues": []},
        {"id": "E02", "modo": "camara", "titulo": "Sin toma", "cues": []},
        {"id": "E03", "modo": "voz", "titulo": "Voz", "cues": []},
    ]


def test_escena_con_toma_e_ia_y_escena_sin_toma(cfg, cliente):
    escenas = _escenas()
    escenas[0]["toma"] = {
        "original": "grabaciones/videos/Facetune 1.MOV",
        "video": "grabaciones/react-04/E01.mov",
    }
    _guion(cfg, escenas, [])
    leccion = cfg.cursos_dir / "REACT" / "04-importar-y-exportar"
    _escritura(leccion / "grabaciones" / "videos" / "ia" / "E01.mov")
    _escritura(cfg.estudio_dir / "public" / "grabaciones" / "react-04" / "E01.mov")

    cuerpo = cliente.get(RUTA).json()

    uno, dos = cuerpo["escenas"]
    assert [e["id"] for e in cuerpo["escenas"]] == ["E01", "E02"]
    assert uno["video"] == "estudio/public/grabaciones/react-04/E01.mov"
    assert isinstance(uno["version"], int)
    assert uno["original"] == "Facetune 1.MOV"
    assert uno["mejorada"] is True
    assert dos == {
        "id": "E02",
        "titulo": "Sin toma",
        "video": None,
        "version": None,
        "original": None,
        "mejorada": False,
    }
    assert cliente.get("/api/medios", params={"ruta": uno["video"]}).status_code == 200


def test_original_solo_aporta_el_nombre(cfg, cliente):
    escenas = _escenas()
    escenas[0]["toma"] = {"original": "../../secreto/Facetune 9.MOV"}
    _guion(cfg, escenas, [])
    assert cliente.get(RUTA).json()["escenas"][0]["original"] == "Facetune 9.MOV"


def test_color_depende_de_que_el_color_sea_posterior_al_mov(cfg, cliente):
    _guion(cfg, [], [{"id": "S2", "titulo": "Gancho dos", "texto": "t"}])
    _shorts(cfg, {"S2": "B0C045C7"})
    tomas = cfg.estudio_dir / "public" / "shorts" / "l4" / "tomas"
    _escritura(tomas / "B0C045C7.mov", mtime_ns=1_000_000_000_000)
    _escritura(
        cfg.estudio_dir / "shorts" / "l4" / "tomas" / "B0C045C7.color",
        mtime_ns=2_000_000_000_000,
    )

    gancho = cliente.get(RUTA).json()["ganchos"][0]
    assert gancho["id"] == "S2"
    assert gancho["toma"] == "B0C045C7"
    assert gancho["video"] == "estudio/public/shorts/l4/tomas/B0C045C7.mov"
    assert gancho["color"] is True

    _escritura(tomas / "B0C045C7.mov", mtime_ns=3_000_000_000_000)
    gancho = cliente.get(RUTA).json()["ganchos"][0]
    assert gancho["color"] is False
    assert gancho["version"] == 3_000_000_000_000


def test_ganchos_sin_entrega_o_con_id_manipulado(cfg, cliente):
    _guion(
        cfg,
        [],
        [
            {"id": "S1", "titulo": "Uno", "texto": "t"},
            {"id": "S2", "titulo": "Dos", "texto": "t"},
        ],
    )
    _shorts(cfg, {"S2": "../../x"})
    ganchos = cliente.get(RUTA).json()["ganchos"]
    vacio = {"toma": None, "video": None, "version": None, "color": False}
    assert [{k: g[k] for k in vacio} for g in ganchos] == [vacio, vacio]


def test_toma_entregada_sin_mov_no_da_video(cfg, cliente):
    _guion(cfg, [], [{"id": "S2", "titulo": "Dos", "texto": "t"}])
    _shorts(cfg, {"S2": "B0C045C7"})
    gancho = cliente.get(RUTA).json()["ganchos"][0]
    assert gancho["toma"] == "B0C045C7"
    assert gancho["video"] is None
    assert gancho["color"] is False


def test_enlace_simbolico_fuera_no_se_sirve(cfg, cliente, tmp_path):
    _guion(cfg, [], [{"id": "S2", "titulo": "Dos", "texto": "t"}])
    _shorts(cfg, {"S2": "B0C045C7"})
    fuera = tmp_path / "fuera.mov"
    fuera.write_bytes(b"x")
    tomas = cfg.estudio_dir / "public" / "shorts" / "l4" / "tomas"
    tomas.mkdir(parents=True)
    (tomas / "B0C045C7.mov").symlink_to(fuera)
    gancho = cliente.get(RUTA).json()["ganchos"][0]
    assert gancho["video"] is None


def test_leccion_a_mano_sin_ganchos_entregados(cfg, cliente):
    escenas = _escenas()
    for escena in escenas[:2]:
        identificador = escena["id"]
        escena["toma"] = {
            "original": f"grabaciones/videos/Toma {identificador}.MOV",
            "video": f"grabaciones/react-04/{identificador}.mov",
            "momentos": [],
        }
        _escritura(
            cfg.estudio_dir
            / "public"
            / "grabaciones"
            / "react-04"
            / f"{identificador}.mov"
        )
    _guion(cfg, escenas, [{"id": "S1", "titulo": "Uno", "texto": "t"}])
    leccion = cfg.cursos_dir / "REACT" / "04-importar-y-exportar"
    _escritura(leccion / "grabaciones" / "videos" / "ia" / "E02.mov")

    respuesta = cliente.get(RUTA)

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert [e["video"] is not None for e in cuerpo["escenas"]] == [True, True]
    assert [e["mejorada"] for e in cuerpo["escenas"]] == [False, True]
    assert cuerpo["ganchos"][0]["toma"] is None


@pytest.mark.parametrize("ruta", ["/api/cursos/react/lecciones/9/camara"])
def test_leccion_inexistente_da_404(cliente, ruta):
    assert cliente.get(ruta).status_code == 404
