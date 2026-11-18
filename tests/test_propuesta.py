import json

from estudio_api.propuesta import leer_propuesta


def _candidato(**cambios):
    candidato = {
        "tipo": "camara",
        "id": "E17",
        "puntuacion": 0.8,
        "desde": 0.0,
        "hasta": 4.5,
        "cues": [0.0, 1.5, 3.0],
    }
    candidato.update(cambios)
    return candidato


def _toma(archivo, **cambios):
    toma = {
        "archivo": archivo,
        "bytes": 16,
        "orientacion": "horizontal",
        "duracion": 5.0,
        "texto": "Texto reconocido ficticio.",
        "propuesta": {"tipo": "camara", "id": "E17"},
        "repite": None,
        "candidatos": [_candidato()],
    }
    toma.update(cambios)
    return toma


def _preparar_guion_y_entregas(cfg):
    guion_ruta = cfg.estudio_dir / "lecciones" / "react-04.json"
    guion = json.loads(guion_ruta.read_text(encoding="utf-8"))
    guion["escenas"] = [
        {
            "id": "E17",
            "modo": "camara",
            "titulo": "Escena ficticia",
            "cues": [
                {"texto": "Primera frase."},
                {"texto": "Segunda frase."},
                {"texto": "Tercera frase."},
            ],
        }
    ]
    guion["ganchos"] = [{"id": "g1", "texto": "Gancho ficticio."}]
    guion_ruta.write_text(json.dumps(guion), encoding="utf-8")
    entregas = (
        cfg.cursos_dir / "REACT" / "04-importar-y-exportar" / "grabaciones" / "entregas"
    )
    entregas.mkdir(parents=True)
    return entregas


def test_leer_propuesta_descarta_entradas_manipuladas_o_desfasadas(cfg):
    entregas = _preparar_guion_y_entregas(cfg)
    nombres = ["negativa.mov", "nan.mov", "id.mov", "valida.mov"]
    for nombre in nombres:
        (entregas / nombre).write_bytes(b"video-ficticio")
    propuesta = {
        "version": 1,
        "guion": "react-04",
        "archivos": [
            _toma("../../x.mov"),
            _toma("negativa.mov", candidatos=[_candidato(desde=-1)]),
            _toma("nan.mov", candidatos=[_candidato(cues=[0.0, float("nan"), 3.0])]),
            _toma(
                "id.mov",
                propuesta={"tipo": "camara", "id": "E1"},
                candidatos=[_candidato(id="E1")],
            ),
            _toma("ya-no-esta.mov"),
            _toma("valida.mov", extra_ignorado=True),
        ],
    }
    (entregas / "propuesta.json").write_text(json.dumps(propuesta), encoding="utf-8")

    leida = leer_propuesta(cfg, "react", 4)

    assert leida is not None
    assert [toma.archivo for toma in leida.archivos] == ["valida.mov"]
    assert leida.archivos[0].candidatos[0].cues == [0.0, 1.5, 3.0]


def test_leer_propuesta_json_roto_devuelve_none(cfg):
    entregas = _preparar_guion_y_entregas(cfg)
    (entregas / "propuesta.json").write_text("{roto", encoding="utf-8")

    assert leer_propuesta(cfg, "react", 4) is None


def test_leer_propuesta_de_otro_guion_devuelve_none(cfg):
    entregas = _preparar_guion_y_entregas(cfg)
    (entregas / "propuesta.json").write_text(
        json.dumps({"version": 1, "guion": "react-05", "archivos": []}),
        encoding="utf-8",
    )

    assert leer_propuesta(cfg, "react", 4) is None


def test_leer_propuesta_no_sigue_un_enlace_fuera_de_entregas(cfg, tmp_path):
    entregas = _preparar_guion_y_entregas(cfg)
    fuera = tmp_path / "propuesta-fuera.json"
    fuera.write_text(
        json.dumps({"version": 1, "guion": "react-04", "archivos": []}),
        encoding="utf-8",
    )
    (entregas / "propuesta.json").symlink_to(fuera)

    assert leer_propuesta(cfg, "react", 4) is None
