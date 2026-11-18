import asyncio
import logging
import shutil
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from estudio_api.app import crear_app
from estudio_api.entregas import guardar_entrega
from estudio_api.rutas_entregas import subir_entrega
from tests.ayudas import TOKEN

RUTA_ENTREGAS = "/api/cursos/react/lecciones/4/entregas"
CABECERAS_MOV = {
    "Content-Type": "video/quicktime",
    "X-Estudio-Token": TOKEN,
}


def _video(tamano: int = 3 * 1024 * 1024, relleno: int = 0) -> bytes:
    assert tamano >= 12
    return b"\x00\x00\x00\x18ftyp" + bytes([relleno]) * (tamano - 8)


@pytest.fixture
def entregas(cfg):
    config = cfg.model_copy(update={"token_escritura": TOKEN})
    leccion = cfg.cursos_dir / "REACT" / "04-importar-y-exportar"
    with TestClient(
        crear_app(config),
        base_url="http://127.0.0.1:8000",
    ) as cliente:
        yield config, cliente, leccion


def _subir(cliente, archivo: str, cuerpo: bytes, tipo: str | None = None):
    cabeceras = dict(CABECERAS_MOV)
    if tipo is not None:
        cabeceras["Content-Type"] = tipo
    nombre = quote(archivo, safe="")
    return cliente.put(
        f"{RUTA_ENTREGAS}/{nombre}",
        headers=cabeceras,
        content=cuerpo,
    )


def test_subir_mov_de_tres_mb_y_listarlo(entregas):
    _, cliente, leccion = entregas
    cuerpo = _video()

    respuesta = _subir(cliente, "IMG_1234.MOV", cuerpo)
    listado = cliente.get(RUTA_ENTREGAS)

    destino = leccion / "grabaciones" / "entregas" / "IMG_1234.MOV"
    assert respuesta.status_code == 201
    assert respuesta.json() == {"archivo": "IMG_1234.MOV", "bytes": len(cuerpo)}
    assert destino.read_bytes() == cuerpo
    assert listado.status_code == 200
    assert listado.json() == [{"archivo": "IMG_1234.MOV", "bytes": len(cuerpo)}]


@pytest.mark.parametrize(
    "archivo",
    ["../x.mov", ".oculto.mov", "Vídeo.mov", "a/b.mov", "x.exe"],
)
def test_nombres_no_admitidos_dan_422_sin_escribir(entregas, archivo):
    _, cliente, leccion = entregas

    respuesta = _subir(cliente, archivo, _video(32))

    assert respuesta.status_code == 422
    assert respuesta.json()["detail"] == (
        "Ese nombre de archivo no se admite: renómbralo con letras sin acentos, "
        "números, espacios, guiones o puntos"
    )
    carpeta = leccion / "grabaciones" / "entregas"
    assert not carpeta.exists() or list(carpeta.iterdir()) == []


@pytest.mark.parametrize(
    ("archivo", "tipo"),
    [
        ("Facetune0A1B2C3D-ejemplo 2.MOV", "video/quicktime"),
        ("IMG_1234.mp4", "video/mp4"),
    ],
)
def test_nombres_y_tipos_admitidos(entregas, archivo, tipo):
    _, cliente, leccion = entregas

    respuesta = _subir(cliente, archivo, _video(32), tipo)

    assert respuesta.status_code == 201
    assert (leccion / "grabaciones" / "entregas" / archivo).is_file()


def test_content_type_incorrecto_da_415(entregas):
    _, cliente, leccion = entregas

    respuesta = _subir(cliente, "IMG_1234.mov", _video(32), "text/plain")

    assert respuesta.status_code == 415
    assert respuesta.json()["detail"] == "La toma tiene que ser un vídeo MOV o MP4"
    assert not (leccion / "grabaciones" / "entregas").exists()


def test_content_length_de_once_digitos_se_rechaza_en_el_middleware(entregas):
    _, cliente, leccion = entregas

    respuesta = cliente.put(
        f"{RUTA_ENTREGAS}/IMG_1234.mov",
        headers={**CABECERAS_MOV, "Content-Length": "10000000000"},
        content=b"",
    )

    assert respuesta.status_code == 413
    assert respuesta.text == "Cuerpo demasiado grande"
    assert not (leccion / "grabaciones" / "entregas").exists()


def test_content_length_de_diez_digitos_superior_a_4_gib_da_413(entregas):
    _, cliente, leccion = entregas

    respuesta = cliente.put(
        f"{RUTA_ENTREGAS}/IMG_1234.mov",
        headers={**CABECERAS_MOV, "Content-Length": "4294967297"},
        content=b"",
    )

    assert respuesta.status_code == 413
    assert not (leccion / "grabaciones" / "entregas").exists()


def test_sin_ftyp_da_422_y_no_deja_temporal(entregas):
    _, cliente, leccion = entregas

    respuesta = _subir(cliente, "IMG_1234.mov", b"no es un video mov")

    assert respuesta.status_code == 422
    assert respuesta.json()["detail"] == "El archivo no es un vídeo MOV o MP4"
    carpeta = leccion / "grabaciones" / "entregas"
    assert not (carpeta / "IMG_1234.mov").exists()
    assert not (carpeta / ".IMG_1234.mov.subiendo").exists()


def test_repetir_nombre_da_409_y_conserva_el_primero(entregas):
    _, cliente, leccion = entregas
    primero = _video(64, relleno=1)

    inicial = _subir(cliente, "IMG_1234.mov", primero)
    repetida = _subir(cliente, "IMG_1234.mov", _video(64, relleno=2))

    destino = leccion / "grabaciones" / "entregas" / "IMG_1234.mov"
    assert inicial.status_code == 201
    assert repetida.status_code == 409
    assert repetida.json()["detail"] == "Ya hay una toma con ese nombre"
    assert destino.read_bytes() == primero
    assert not (destino.parent / ".IMG_1234.mov.subiendo").exists()


def test_nombre_ya_colocado_en_videos_da_409(entregas):
    _, cliente, leccion = entregas
    videos = leccion / "grabaciones" / "videos"
    videos.mkdir(parents=True)
    original = b"original colocado"
    (videos / "IMG_1234.mov").write_bytes(original)

    respuesta = _subir(cliente, "IMG_1234.mov", _video(64))

    assert respuesta.status_code == 409
    assert respuesta.json()["detail"] == "Ya hay una toma con ese nombre"
    assert (videos / "IMG_1234.mov").read_bytes() == original
    assert not (leccion / "grabaciones" / "entregas" / "IMG_1234.mov").exists()


def test_nombre_en_videos_se_compara_con_mayusculas_exactas(entregas):
    _, cliente, leccion = entregas
    videos = leccion / "grabaciones" / "videos"
    videos.mkdir(parents=True)
    (videos / "img_1234.mov").write_bytes(b"otro nombre")

    respuesta = _subir(cliente, "IMG_1234.mov", _video(64))

    assert respuesta.status_code == 201
    assert (leccion / "grabaciones" / "entregas" / "IMG_1234.mov").is_file()


def test_desconexion_limpia_el_temporal_y_responde_400(entregas, caplog):
    config, _, leccion = entregas
    cuerpo = _video(64)
    mensajes = iter(
        [
            {"type": "http.request", "body": cuerpo[:20], "more_body": True},
            {"type": "http.disconnect"},
        ]
    )

    async def recibir():
        return next(mensajes)

    ruta = f"{RUTA_ENTREGAS}/IMG_1234.mov"
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "PUT",
        "scheme": "http",
        "path": ruta,
        "raw_path": ruta.encode(),
        "query_string": b"",
        "headers": [
            (b"content-type", b"video/quicktime"),
            (b"content-length", str(len(cuerpo)).encode()),
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
        "app": SimpleNamespace(state=SimpleNamespace(config=config)),
    }

    with caplog.at_level(logging.ERROR), pytest.raises(HTTPException) as error:
        asyncio.run(subir_entrega(Request(scope, recibir), "react", 4, "IMG_1234.mov"))

    carpeta = leccion / "grabaciones" / "entregas"
    assert error.value.status_code == 400
    assert error.value.detail == "La subida se ha cortado"
    assert not (carpeta / "IMG_1234.mov").exists()
    assert not (carpeta / ".IMG_1234.mov.subiendo").exists()
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_delete_borra_toma_y_todos_sus_analisis(entregas):
    _, cliente, leccion = entregas
    assert _subir(cliente, "IMG_1234.mov", _video(64)).status_code == 201
    analisis = leccion / "grabaciones" / "entregas" / ".analisis"
    analisis.mkdir()
    (analisis / "IMG_1234.mov.json").write_text("{}", encoding="utf-8")
    (analisis / "IMG_1234.mov.wav").write_bytes(b"audio")
    (analisis / "otra.mov.json").write_text("{}", encoding="utf-8")

    respuesta = cliente.delete(
        f"{RUTA_ENTREGAS}/IMG_1234.mov",
        headers={"X-Estudio-Token": TOKEN, "Content-Length": "0"},
    )

    assert respuesta.status_code == 204
    carpeta = analisis.parent
    assert not (carpeta / "IMG_1234.mov").exists()
    assert not (analisis / "IMG_1234.mov.json").exists()
    assert not (analisis / "IMG_1234.mov.wav").exists()
    assert (analisis / "otra.mov.json").is_file()


def test_delete_inexistente_da_404(entregas):
    _, cliente, _ = entregas

    respuesta = cliente.delete(
        f"{RUTA_ENTREGAS}/IMG_1234.mov",
        headers={"X-Estudio-Token": TOKEN, "Content-Length": "0"},
    )

    assert respuesta.status_code == 404
    assert respuesta.json()["detail"] == "La toma entregada no existe"


def test_entregas_enlazado_no_escribe_fuera(entregas):
    config, cliente, leccion = entregas
    fuera = config.cursos_dir.parent / "entregas-fuera"
    fuera.mkdir()
    grabaciones = leccion / "grabaciones"
    grabaciones.mkdir()
    (grabaciones / "entregas").symlink_to(fuera, target_is_directory=True)

    respuesta = _subir(cliente, "IMG_1234.mov", _video(64))

    assert respuesta.status_code == 503
    assert respuesta.json()["detail"] == "No se ha podido guardar la toma"
    assert list(fuera.iterdir()) == []


def test_temporal_enlazado_no_escribe_fuera(entregas):
    config, cliente, leccion = entregas
    carpeta = leccion / "grabaciones" / "entregas"
    carpeta.mkdir(parents=True)
    fuera = config.cursos_dir.parent / "video-fuera.mov"
    original = b"fuera intacto"
    fuera.write_bytes(original)
    (carpeta / ".IMG_1234.mov.subiendo").symlink_to(fuera)

    respuesta = _subir(cliente, "IMG_1234.mov", _video(64))

    assert respuesta.status_code == 503
    assert respuesta.json()["detail"] == "No se ha podido guardar la toma"
    assert fuera.read_bytes() == original
    assert not (carpeta / "IMG_1234.mov").exists()


def test_listado_solo_incluye_videos_validos_ordenados(entregas):
    _, cliente, leccion = entregas
    carpeta = leccion / "grabaciones" / "entregas"
    carpeta.mkdir(parents=True)
    (carpeta / "z.MP4").write_bytes(b"z")
    (carpeta / "A.mov").write_bytes(b"aa")
    (carpeta / ".oculto.mov").write_bytes(b"oculto")
    (carpeta / "texto.txt").write_text("texto", encoding="utf-8")
    (carpeta / "subcarpeta.mp4").mkdir()

    respuesta = cliente.get(RUTA_ENTREGAS)

    assert respuesta.status_code == 200
    assert respuesta.json() == [
        {"archivo": "A.mov", "bytes": 2},
        {"archivo": "z.MP4", "bytes": 1},
    ]


def test_leccion_inexistente_da_404_en_las_tres_rutas(entregas):
    _, cliente, _ = entregas
    ruta = "/api/cursos/react/lecciones/999/entregas"

    listado = cliente.get(ruta)
    subida = cliente.put(
        f"{ruta}/IMG_1234.mov",
        headers=CABECERAS_MOV,
        content=_video(32),
    )
    borrado = cliente.delete(
        f"{ruta}/IMG_1234.mov",
        headers={"X-Estudio-Token": TOKEN, "Content-Length": "0"},
    )

    assert listado.status_code == subida.status_code == borrado.status_code == 404


def test_guardar_entrega_cortada_directamente_no_deja_restos(entregas):
    config, _, leccion = entregas
    cuerpo = _video(64)

    async def cortado():
        yield cuerpo[:20]

    with pytest.raises(ValueError):
        asyncio.run(
            guardar_entrega(
                config,
                "react",
                4,
                "IMG_1234.mov",
                cortado(),
                len(cuerpo),
            )
        )

    carpeta = leccion / "grabaciones" / "entregas"
    assert not (carpeta / "IMG_1234.mov").exists()
    assert not (carpeta / ".IMG_1234.mov.subiendo").exists()


def test_fallo_no_borra_la_leccion_existente(entregas):
    _, cliente, leccion = entregas
    shutil.rmtree(leccion / "previa")

    respuesta = _subir(cliente, "IMG_1234.mov", b"invalido")

    assert respuesta.status_code == 422
    assert leccion.is_dir()
