import json
import os
import threading
import time

import pytest

from estudio_api.propuesta import _leer_json_propuesta, leer_propuesta


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


@pytest.mark.parametrize(
    "cambios",
    [
        {"candidatos": [_candidato(desde=True)]},
        {"candidatos": [_candidato(hasta=False)]},
        {"candidatos": [_candidato(desde="0.5")]},
        {"candidatos": [_candidato(cues=[0.0, True, 3.0])]},
        {"bytes": True},
        {"duracion": "5"},
        {"duracion": "Infinity"},
    ],
)
def test_leer_propuesta_descarta_numeros_no_estrictos(cfg, cambios):
    entregas = _preparar_guion_y_entregas(cfg)
    (entregas / "invalida.mov").write_bytes(b"video-ficticio")
    (entregas / "propuesta.json").write_text(
        json.dumps(
            {
                "version": 1,
                "guion": "react-04",
                "archivos": [_toma("invalida.mov", **cambios)],
            }
        ),
        encoding="utf-8",
    )

    leida = leer_propuesta(cfg, "react", 4)

    assert leida is not None
    assert leida.archivos == []


def test_leer_propuesta_acepta_enteros_en_campos_float(cfg):
    entregas = _preparar_guion_y_entregas(cfg)
    (entregas / "valida.mov").write_bytes(b"video-ficticio")
    candidato = _candidato(
        puntuacion=1,
        desde=0,
        hasta=4,
        cues=[0, 1, 3],
    )
    (entregas / "propuesta.json").write_text(
        json.dumps(
            {
                "version": 1,
                "guion": "react-04",
                "archivos": [_toma("valida.mov", duracion=5, candidatos=[candidato])],
            }
        ),
        encoding="utf-8",
    )

    leida = leer_propuesta(cfg, "react", 4)

    assert leida is not None
    assert [toma.archivo for toma in leida.archivos] == ["valida.mov"]


def test_leer_json_propuesta_fifo_no_bloquea(tmp_path):
    os.mkfifo(tmp_path / "propuesta.json")
    resultado = []

    def leer():
        resultado.append(_leer_json_propuesta(tmp_path))

    hilo = threading.Thread(target=leer, daemon=True)
    inicio = time.monotonic()
    hilo.start()
    hilo.join(0.5)

    assert not hilo.is_alive()
    assert time.monotonic() - inicio < 0.5
    assert resultado == [None]


def test_leer_propuesta_conserva_la_primera_entrada_de_un_archivo(cfg):
    entregas = _preparar_guion_y_entregas(cfg)
    (entregas / "repetida.mov").write_bytes(b"video-ficticio")
    primera = _toma("repetida.mov", candidatos=[_candidato(puntuacion=0.8)])
    segunda = _toma("repetida.mov", candidatos=[_candidato(puntuacion=0.2)])
    (entregas / "propuesta.json").write_text(
        json.dumps(
            {
                "version": 1,
                "guion": "react-04",
                "archivos": [primera, segunda],
            }
        ),
        encoding="utf-8",
    )

    leida = leer_propuesta(cfg, "react", 4)

    assert leida is not None
    assert len(leida.archivos) == 1
    assert leida.archivos[0].candidatos[0].puntuacion == 0.8


def test_leer_propuesta_descarta_candidato_con_numero_incorrecto_de_cues(cfg):
    entregas = _preparar_guion_y_entregas(cfg)
    (entregas / "invalida.mov").write_bytes(b"video-ficticio")
    (entregas / "propuesta.json").write_text(
        json.dumps(
            {
                "version": 1,
                "guion": "react-04",
                "archivos": [
                    _toma("invalida.mov", candidatos=[_candidato(cues=[0.0])])
                ],
            }
        ),
        encoding="utf-8",
    )

    leida = leer_propuesta(cfg, "react", 4)

    assert leida is not None
    assert leida.archivos == []


def test_leer_propuesta_acepta_candidato_de_gancho_con_clave_cues(cfg):
    entregas = _preparar_guion_y_entregas(cfg)
    (entregas / "gancho.mov").write_bytes(b"video-ficticio")
    candidato = {
        "tipo": "gancho",
        "id": "g1",
        "puntuacion": 0.8,
        "desde": 0.0,
        "hasta": 4.5,
        "cues": [0.0],
    }
    toma = _toma(
        "gancho.mov",
        orientacion="vertical",
        propuesta={"tipo": "gancho", "id": "g1"},
        candidatos=[candidato],
    )
    (entregas / "propuesta.json").write_text(
        json.dumps({"version": 1, "guion": "react-04", "archivos": [toma]}),
        encoding="utf-8",
    )

    leida = leer_propuesta(cfg, "react", 4)

    assert leida is not None
    assert [entrada.archivo for entrada in leida.archivos] == ["gancho.mov"]
