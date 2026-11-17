import asyncio
import json
import logging
import os
import shutil
import struct
import threading
import time
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from estudio_api.app import crear_app
from estudio_api.rutas_teleprompter import subir_toma_voz
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


def test_content_type_wav_con_parametros_es_valido(tomas):
    _, cliente, grabaciones, _ = tomas
    cuerpo = _wav()

    respuesta = cliente.put(
        RUTA_TOMA.format(escena="E04"),
        headers={
            "Content-Type": "audio/wav; codecs=1",
            "X-Estudio-Token": TOKEN,
        },
        content=cuerpo,
    )

    assert respuesta.status_code == 201
    assert (grabaciones / "E04.wav").read_bytes() == cuerpo


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


@pytest.mark.parametrize(
    ("metodo", "ruta"),
    [
        ("POST", RUTA_TOMA.format(escena="E04")),
        ("PUT", f"{RUTA_TOMA.format(escena='E04')}/"),
        ("PUT", "/api/cursos/react/lecciones/04/grabaciones/E04"),
    ],
)
def test_variantes_de_ruta_no_reciben_el_limite_grande(tomas, metodo, ruta):
    _, cliente, grabaciones, original = tomas

    respuesta = cliente.request(
        metodo,
        ruta,
        headers=CABECERAS_WAV,
        content=_wav(300 * 1024),
    )

    assert respuesta.status_code == 413
    _assert_sin_restos(grabaciones, original)


def test_content_length_de_nueve_digitos_en_otra_ruta_se_rechaza(tomas):
    _, cliente, grabaciones, original = tomas

    respuesta = cliente.put(
        "/api/cursos/react/lecciones/4/publicacion",
        headers={
            "Content-Type": "application/json",
            "Content-Length": "100000000",
            "X-Estudio-Token": TOKEN,
        },
        content=b"",
    )

    assert respuesta.status_code == 413
    _assert_sin_restos(grabaciones, original)


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


def test_leccion_solo_con_guion_crea_su_carpeta_validada_si_el_curso_existe(tomas):
    _, cliente, grabaciones, _ = tomas
    carpeta = grabaciones.parent
    shutil.rmtree(carpeta)

    respuesta = cliente.put(
        RUTA_TOMA.format(escena="E04"),
        headers=CABECERAS_WAV,
        content=_wav(),
    )

    assert respuesta.status_code == 201
    assert (carpeta / "grabaciones" / "E04.wav").is_file()


def test_curso_sin_carpetas_de_leccion_no_existe_para_lecturas_ni_subida(tomas):
    config, cliente, grabaciones, _ = tomas
    shutil.rmtree(grabaciones.parent)
    shutil.rmtree(config.cursos_dir / "REACT" / "05-otra")

    detalle = cliente.get("/api/cursos/react/lecciones/4")
    teleprompter = cliente.get("/api/cursos/react/lecciones/4/teleprompter")
    subida = cliente.put(
        RUTA_TOMA.format(escena="E04"),
        headers=CABECERAS_WAV,
        content=_wav(),
    )

    assert detalle.status_code == 404
    assert teleprompter.status_code == 404
    assert subida.status_code == 404
    assert not grabaciones.parent.exists()


def test_subida_fallida_borra_las_carpetas_que_ha_creado(tomas):
    config, cliente, grabaciones, _ = tomas
    carpeta = grabaciones.parent
    shutil.rmtree(carpeta)

    respuesta = cliente.put(
        RUTA_TOMA.format(escena="E04"),
        headers=CABECERAS_WAV,
        content=b"no es wav",
    )

    assert respuesta.status_code == 422
    assert not carpeta.exists()
    assert (config.cursos_dir / "REACT" / "05-otra").is_dir()


def test_subida_fallida_conserva_la_leccion_existente_y_borra_grabaciones(tomas):
    _, cliente, grabaciones, _ = tomas
    carpeta = grabaciones.parent
    shutil.rmtree(grabaciones)

    respuesta = cliente.put(
        RUTA_TOMA.format(escena="E04"),
        headers=CABECERAS_WAV,
        content=b"no es wav",
    )

    assert respuesta.status_code == 422
    assert carpeta.is_dir()
    assert not grabaciones.exists()


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


@pytest.mark.parametrize("nombre", ["grabaciones", "tomas"])
def test_directorio_enlazado_fuera_se_rechaza_sin_escribir(tomas, nombre):
    config, cliente, grabaciones, original = tomas
    fuera = config.cursos_dir.parent / f"fuera-{nombre}"
    fuera.mkdir()
    if nombre == "grabaciones":
        shutil.rmtree(grabaciones)
        grabaciones.symlink_to(fuera, target_is_directory=True)
    else:
        (grabaciones / "tomas").symlink_to(fuera, target_is_directory=True)

    respuesta = cliente.put(
        RUTA_TOMA.format(escena="E04"),
        headers=CABECERAS_WAV,
        content=_wav(relleno=5),
    )

    assert respuesta.status_code == 503
    assert list(fuera.iterdir()) == []
    if nombre == "tomas":
        assert (grabaciones / "E03.wav").read_bytes() == original


def test_cuerpo_mas_largo_que_content_length_falla_sin_restos(tomas):
    _, cliente, grabaciones, original = tomas
    cuerpo = _wav()

    respuesta = cliente.put(
        RUTA_TOMA.format(escena="E03"),
        headers={**CABECERAS_WAV, "Content-Length": str(len(cuerpo) - 1)},
        content=cuerpo,
    )

    assert respuesta.status_code == 413
    _assert_sin_restos(grabaciones, original)


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


def test_si_falla_instalar_borra_el_temporal_antes_de_los_directorios(
    tomas, monkeypatch
):
    config, _, grabaciones, _ = tomas
    carpeta = grabaciones.parent
    shutil.rmtree(carpeta)
    cuerpo = _wav(relleno=4)

    def instalar_con_fallo(*_args):
        raise OSError("fallo ficticio al instalar")

    monkeypatch.setattr("estudio_api.tomas._instalar_temporal", instalar_con_fallo)

    async def completo():
        yield cuerpo

    with pytest.raises(OSError):
        asyncio.run(
            guardar_toma(
                config,
                "react",
                4,
                "E04",
                completo(),
                len(cuerpo),
            )
        )

    assert not carpeta.exists()


def test_un_fsync_fallido_no_cierra_dos_veces_el_descriptor(tomas, monkeypatch):
    config, _, grabaciones, _ = tomas
    cuerpo = _wav(relleno=4)
    cierres = []
    close_real = os.close

    def fsync_con_fallo(_descriptor):
        raise OSError("fallo ficticio al sincronizar")

    def close_contado(descriptor):
        cierres.append(descriptor)
        close_real(descriptor)

    monkeypatch.setattr("estudio_api.tomas.os.fsync", fsync_con_fallo)
    monkeypatch.setattr("estudio_api.tomas.os.close", close_contado)

    async def completo():
        yield cuerpo

    with pytest.raises(OSError):
        asyncio.run(
            guardar_toma(
                config,
                "react",
                4,
                "E04",
                completo(),
                len(cuerpo),
            )
        )

    assert len(cierres) == 1
    assert [ruta for ruta in grabaciones.iterdir() if ruta.name.startswith(".")] == []


def test_si_falla_el_fsync_tras_replace_se_restaura_la_toma_anterior(
    tomas, monkeypatch
):
    config, _, grabaciones, original = tomas
    cuerpo = _wav(relleno=4)
    fsync_real = __import__(
        "estudio_api.tomas", fromlist=["_fsync_directorio"]
    )._fsync_directorio
    fallo_pendiente = True

    def fsync_con_fallo(directorio):
        nonlocal fallo_pendiente
        if directorio == grabaciones and fallo_pendiente:
            fallo_pendiente = False
            raise OSError("fallo ficticio al sincronizar grabaciones")
        fsync_real(directorio)

    monkeypatch.setattr("estudio_api.tomas._fsync_directorio", fsync_con_fallo)

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


def test_archivar_toma_sincroniza_tomas_antes_de_instalar(tomas, monkeypatch):
    config, _, grabaciones, _ = tomas
    cuerpo = _wav(relleno=4)
    fsync_real = __import__(
        "estudio_api.tomas", fromlist=["_fsync_directorio"]
    )._fsync_directorio
    sincronizados = []

    def registrar_fsync(directorio):
        sincronizados.append(directorio)
        fsync_real(directorio)

    monkeypatch.setattr("estudio_api.tomas._fsync_directorio", registrar_fsync)

    async def completo():
        yield cuerpo

    asyncio.run(guardar_toma(config, "react", 4, "E03", completo(), len(cuerpo)))

    assert sincronizados[:2] == [grabaciones / "tomas", grabaciones]


def test_guardado_hace_escritura_e_instalacion_fuera_del_bucle(tomas, monkeypatch):
    config, _, _, _ = tomas
    cuerpo = _wav()
    hilo_bucle = threading.get_ident()
    hilos_trabajo = []
    import estudio_api.tomas as modulo_tomas

    escribir_real = modulo_tomas._escribir_trozo
    instalar_real = modulo_tomas._instalar_temporal

    def registrar_escritura(*args):
        hilos_trabajo.append(threading.get_ident())
        return escribir_real(*args)

    def registrar_instalacion(*args):
        hilos_trabajo.append(threading.get_ident())
        return instalar_real(*args)

    monkeypatch.setattr(modulo_tomas, "_escribir_trozo", registrar_escritura)
    monkeypatch.setattr(modulo_tomas, "_instalar_temporal", registrar_instalacion)

    async def completo():
        yield cuerpo

    asyncio.run(guardar_toma(config, "react", 4, "E04", completo(), len(cuerpo)))

    assert hilos_trabajo
    assert all(identificador != hilo_bucle for identificador in hilos_trabajo)


def test_al_guardar_borra_solo_temporales_de_mas_de_24_horas(tomas):
    _, cliente, grabaciones, _ = tomas
    antiguo = grabaciones / ".antiguo.wav.tmp"
    reciente = grabaciones / ".reciente.wav.tmp"
    antiguo.write_bytes(b"antiguo")
    reciente.write_bytes(b"reciente")
    hace_25_horas = time.time() - 25 * 60 * 60
    os.utime(antiguo, (hace_25_horas, hace_25_horas))

    respuesta = cliente.put(
        RUTA_TOMA.format(escena="E04"),
        headers=CABECERAS_WAV,
        content=_wav(),
    )

    assert respuesta.status_code == 201
    assert not antiguo.exists()
    assert reciente.read_bytes() == b"reciente"


def test_desconexion_del_cliente_limpia_y_responde_400_sin_log_de_error(tomas, caplog):
    config, _, grabaciones, original = tomas
    cuerpo = _wav()
    mensajes = iter(
        [
            {"type": "http.request", "body": cuerpo[:20], "more_body": True},
            {"type": "http.disconnect"},
        ]
    )

    async def recibir():
        return next(mensajes)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "PUT",
        "scheme": "http",
        "path": RUTA_TOMA.format(escena="E03"),
        "raw_path": RUTA_TOMA.format(escena="E03").encode(),
        "query_string": b"",
        "headers": [
            (b"content-type", b"audio/wav"),
            (b"content-length", str(len(cuerpo)).encode()),
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
        "app": SimpleNamespace(state=SimpleNamespace(config=config)),
    }
    peticion = Request(scope, recibir)

    with caplog.at_level(logging.ERROR), pytest.raises(HTTPException) as error:
        asyncio.run(subir_toma_voz(peticion, "react", 4, "E03"))

    assert error.value.status_code == 400
    assert error.value.detail == "La subida se ha cortado"
    assert not [
        registro for registro in caplog.records if registro.levelno >= logging.ERROR
    ]
    _assert_sin_restos(grabaciones, original)
