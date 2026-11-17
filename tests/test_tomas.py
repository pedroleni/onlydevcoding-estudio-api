import asyncio
import json
import os
import shutil
import struct
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from estudio_api.app import crear_app
from estudio_api.tomas import WavInvalido, guardar_toma
from tests.ayudas import TOKEN

CABECERAS_WAV = {
    "Content-Type": "audio/wav",
    "X-Estudio-Token": TOKEN,
}
RUTA_TOMA = "/api/cursos/react/lecciones/4/grabaciones/{escena}"


def _wav(tamano: int = 32_044, relleno: int = 0) -> bytes:
    assert tamano >= 44
    datos = bytes([relleno]) * (tamano - 44)
    return b"".join(
        [
            b"RIFF",
            struct.pack("<I", 36 + len(datos)),
            b"WAVEfmt ",
            struct.pack("<IHHIIHH", 16, 1, 1, 16_000, 32_000, 2, 16),
            b"data",
            struct.pack("<I", len(datos)),
            datos,
        ]
    )


@pytest.fixture
def tomas(cfg):
    ruta_guion = cfg.estudio_dir / "lecciones" / "react-04.json"
    guion = json.loads(ruta_guion.read_text(encoding="utf-8"))
    guion["escenas"] = [
        {"id": "E01", "modo": "camara", "cues": []},
        {"id": "E02", "modo": "animacion", "cues": []},
        {"id": "E03", "modo": "voz", "cues": [{"texto": "Texto ficticio."}]},
        {"id": "E04", "modo": "voz", "cues": [{"texto": "Otro texto."}]},
    ]
    ruta_guion.write_text(json.dumps(guion), encoding="utf-8")

    grabaciones = cfg.cursos_dir / "REACT" / "04-importar-y-exportar" / "grabaciones"
    grabaciones.mkdir()
    original = _wav(relleno=1)
    (grabaciones / "E03.wav").write_bytes(original)

    config = cfg.model_copy(update={"token_escritura": TOKEN})
    with TestClient(
        crear_app(config),
        base_url="http://127.0.0.1:8000",
    ) as cliente:
        yield config, cliente, grabaciones, original


def _assert_sin_restos(grabaciones, original):
    assert (grabaciones / "E03.wav").read_bytes() == original
    tomas = grabaciones / "tomas"
    assert not tomas.exists() or list(tomas.iterdir()) == []
    assert [ruta for ruta in grabaciones.iterdir() if ruta.name.startswith(".")] == []


def test_primera_toma_crea_wav_y_directorio_de_tomas_vacio(tomas):
    _, cliente, grabaciones, _ = tomas
    cuerpo = _wav()

    respuesta = cliente.put(
        RUTA_TOMA.format(escena="E04"),
        headers=CABECERAS_WAV,
        content=cuerpo,
    )

    destino = grabaciones / "E04.wav"
    assert respuesta.status_code == 201
    assert destino.read_bytes() == cuerpo
    assert list((grabaciones / "tomas").iterdir()) == []
    assert respuesta.json() == {
        "escena": "E04",
        "ruta": "cursos/REACT/04-importar-y-exportar/grabaciones/E04.wav",
        "version": destino.stat().st_mtime_ns,
        "bytes": len(cuerpo),
    }


def test_dos_repeticiones_no_pisan_tomas_anteriores_con_la_misma_hora(
    tomas, monkeypatch
):
    _, cliente, grabaciones, original = tomas
    primera = _wav(relleno=2)
    segunda = _wav(relleno=3)
    instante = datetime(2026, 11, 17, 12, 34, 56, 123456)
    monkeypatch.setattr("estudio_api.tomas._ahora_local", lambda: instante)

    respuesta_1 = cliente.put(
        RUTA_TOMA.format(escena="E03"),
        headers=CABECERAS_WAV,
        content=primera,
    )
    respuesta_2 = cliente.put(
        RUTA_TOMA.format(escena="E03"),
        headers=CABECERAS_WAV,
        content=segunda,
    )

    assert respuesta_1.status_code == respuesta_2.status_code == 201
    assert (grabaciones / "E03.wav").read_bytes() == segunda
    archivadas = sorted((grabaciones / "tomas").iterdir())
    assert [ruta.name for ruta in archivadas] == [
        "E03-20261117T123456123456-2.wav",
        "E03-20261117T123456123456.wav",
    ]
    assert {ruta.read_bytes() for ruta in archivadas} == {original, primera}


def test_cuerpo_que_no_es_wav_no_toca_la_toma_anterior(tomas):
    _, cliente, grabaciones, original = tomas

    respuesta = cliente.put(
        RUTA_TOMA.format(escena="E03"),
        headers=CABECERAS_WAV,
        content=b"esto no es un wav",
    )

    assert respuesta.status_code == 422
    assert respuesta.json()["detail"] == "El archivo no es un WAV válido"
    _assert_sin_restos(grabaciones, original)


def test_content_type_incorrecto_no_toca_la_toma_anterior(tomas):
    _, cliente, grabaciones, original = tomas

    respuesta = cliente.put(
        RUTA_TOMA.format(escena="E03"),
        headers={"Content-Type": "audio/mpeg", "X-Estudio-Token": TOKEN},
        content=_wav(),
    )

    assert respuesta.status_code == 415
    assert respuesta.json()["detail"] == "La toma tiene que ser un WAV (audio/wav)"
    _assert_sin_restos(grabaciones, original)


def test_cuerpo_cortado_en_guardar_toma_no_toca_la_toma_anterior(tomas):
    config, _, grabaciones, original = tomas
    cuerpo = _wav()

    async def cortado():
        yield cuerpo

    with pytest.raises(WavInvalido):
        asyncio.run(
            guardar_toma(
                config,
                "react",
                4,
                "E03",
                cortado(),
                len(cuerpo) + 20,
            )
        )

    _assert_sin_restos(grabaciones, original)


@pytest.mark.parametrize(
    ("escena", "estado", "mensaje"),
    [
        ("E01", 422, "Esa escena no se graba con voz"),
        ("E99", 404, "La escena no existe en el guion"),
    ],
)
def test_solo_se_guardan_escenas_de_voz(tomas, escena, estado, mensaje):
    _, cliente, grabaciones, original = tomas

    respuesta = cliente.put(
        RUTA_TOMA.format(escena=escena),
        headers=CABECERAS_WAV,
        content=_wav(),
    )

    assert respuesta.status_code == estado
    assert respuesta.json()["detail"] == mensaje
    _assert_sin_restos(grabaciones, original)


def test_ruta_de_tomas_admite_300_kb_y_las_demas_no(tomas):
    _, cliente, grabaciones, _ = tomas
    cuerpo = _wav(300 * 1024)

    toma = cliente.put(
        RUTA_TOMA.format(escena="E04"),
        headers=CABECERAS_WAV,
        content=cuerpo,
    )
    otra = cliente.put(
        "/api/cursos/react/lecciones/4/publicacion",
        headers={"Content-Type": "application/json", "X-Estudio-Token": TOKEN},
        content=b"x" * (300 * 1024),
    )

    assert toma.status_code == 201
    assert (grabaciones / "E04.wav").stat().st_size == 300 * 1024
    assert otra.status_code == 413


def test_content_length_superior_a_200_mib_se_rechaza_sin_leer(tomas):
    _, cliente, grabaciones, original = tomas

    respuesta = cliente.put(
        RUTA_TOMA.format(escena="E03"),
        headers={
            **CABECERAS_WAV,
            "Content-Length": "209715201",
        },
        content=b"",
    )

    assert respuesta.status_code == 413
    _assert_sin_restos(grabaciones, original)


def test_subida_sin_token_se_rechaza(tomas):
    _, cliente, grabaciones, original = tomas

    respuesta = cliente.put(
        RUTA_TOMA.format(escena="E03"),
        headers={"Content-Type": "audio/wav"},
        content=_wav(),
    )

    assert respuesta.status_code == 401
    _assert_sin_restos(grabaciones, original)


def test_leccion_solo_con_guion_crea_su_carpeta_validada(tomas):
    config, cliente, grabaciones, _ = tomas
    carpeta = grabaciones.parent
    shutil.rmtree(carpeta)
    shutil.rmtree(config.cursos_dir / "REACT" / "05-otra")

    respuesta = cliente.put(
        RUTA_TOMA.format(escena="E04"),
        headers=CABECERAS_WAV,
        content=_wav(),
    )

    assert respuesta.status_code == 201
    assert (carpeta / "grabaciones" / "E04.wav").is_file()


def test_carpeta_de_disco_tiene_preferencia_sobre_la_del_guion(tomas):
    config, cliente, grabaciones, _ = tomas
    ruta_guion = config.estudio_dir / "lecciones" / "react-04.json"
    guion = json.loads(ruta_guion.read_text(encoding="utf-8"))
    guion["carpeta"] = "REACT/04-otra-carpeta"
    ruta_guion.write_text(json.dumps(guion), encoding="utf-8")

    respuesta = cliente.put(
        RUTA_TOMA.format(escena="E04"),
        headers=CABECERAS_WAV,
        content=_wav(),
    )

    assert respuesta.status_code == 201
    assert (grabaciones / "E04.wav").is_file()
    assert not (config.cursos_dir / "REACT" / "04-otra-carpeta").exists()


def test_destino_enlazado_fuera_se_rechaza_sin_escribir(tomas):
    config, cliente, grabaciones, original = tomas
    destino = grabaciones / "E03.wav"
    fuera = config.cursos_dir.parent / "toma-fuera.wav"
    fuera.write_bytes(original)
    destino.unlink()
    destino.symlink_to(fuera)

    respuesta = cliente.put(
        RUTA_TOMA.format(escena="E03"),
        headers=CABECERAS_WAV,
        content=_wav(relleno=5),
    )

    assert respuesta.status_code == 503
    assert fuera.read_bytes() == original
    assert list((grabaciones / "tomas").iterdir()) == []
    assert [ruta for ruta in grabaciones.iterdir() if ruta.name.startswith(".")] == []


def test_si_falla_el_replace_final_se_restaura_la_toma_anterior(tomas, monkeypatch):
    config, _, grabaciones, original = tomas
    cuerpo = _wav(relleno=4)
    replace_real = os.replace

    def replace_con_fallo(origen, destino):
        if str(origen).endswith(".wav.tmp"):
            raise OSError("fallo ficticio al instalar la toma")
        replace_real(origen, destino)

    monkeypatch.setattr("estudio_api.tomas.os.replace", replace_con_fallo)

    async def completo():
        yield cuerpo

    with pytest.raises(OSError):
        asyncio.run(
            guardar_toma(
                config,
                "react",
                4,
                "E03",
                completo(),
                len(cuerpo),
            )
        )

    _assert_sin_restos(grabaciones, original)
