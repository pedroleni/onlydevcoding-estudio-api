import asyncio
import inspect
import json
import logging
import shutil
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from estudio_api import entregas as modulo_entregas
from estudio_api.app import crear_app
from estudio_api.entregas import carpeta_entregas, guardar_entrega
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
    assert listado.json()["archivos"] == [
        {"archivo": "IMG_1234.MOV", "bytes": len(cuerpo)}
    ]
    assert listado.json()["propuesta"] is None
    assert listado.json()["destinos"]["camara"] == [
        {"id": "E01", "titulo": "Presentación", "tiene_toma": False}
    ]


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
    assert respuesta.text == "La toma supera el límite de 4 GiB"
    assert not (leccion / "grabaciones" / "entregas").exists()


def test_content_length_de_diez_digitos_superior_a_4_gib_da_413(entregas):
    _, cliente, leccion = entregas

    respuesta = cliente.put(
        f"{RUTA_ENTREGAS}/IMG_1234.mov",
        headers={**CABECERAS_MOV, "Content-Length": "4294967297"},
        content=b"",
    )

    assert respuesta.status_code == 413
    assert respuesta.text == "La toma supera el límite de 4 GiB"
    assert not (leccion / "grabaciones" / "entregas").exists()


def test_content_length_de_diez_digitos_depende_de_la_ruta(entregas):
    _, cliente, _ = entregas

    async def llamar(ruta: str, tipo: bytes) -> list[dict]:
        mensajes: list[dict] = []
        peticiones = iter(
            [
                {"type": "http.request", "body": b"", "more_body": True},
                {"type": "http.disconnect"},
            ]
        )

        async def recibir() -> dict:
            return next(peticiones)

        async def enviar(mensaje: dict) -> None:
            mensajes.append(mensaje)

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
                (b"host", b"127.0.0.1:8000"),
                (b"content-type", tipo),
                (b"content-length", b"1000000000"),
                (b"x-estudio-token", TOKEN.encode()),
            ],
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 8000),
            "root_path": "",
        }
        await cliente.app(scope, recibir, enviar)
        return mensajes

    ruta_entrega = f"{RUTA_ENTREGAS}/IMG_1234.mov"
    ruta_voz = "/api/cursos/react/lecciones/4/grabaciones/E03"
    mensajes_entrega = asyncio.run(llamar(ruta_entrega, b"video/quicktime"))
    mensajes_voz = asyncio.run(llamar(ruta_voz, b"audio/wav"))

    estado_entrega = next(
        mensaje["status"]
        for mensaje in mensajes_entrega
        if mensaje["type"] == "http.response.start"
    )
    estado_voz = next(
        mensaje["status"]
        for mensaje in mensajes_voz
        if mensaje["type"] == "http.response.start"
    )
    assert estado_entrega == 400
    assert estado_voz == 413


def test_sin_ftyp_da_422_y_no_deja_temporal(entregas):
    _, cliente, leccion = entregas

    respuesta = _subir(cliente, "IMG_1234.mov", b"no es un video mov")

    assert respuesta.status_code == 422
    assert respuesta.json()["detail"] == "El archivo no es un vídeo MOV o MP4"
    carpeta = leccion / "grabaciones" / "entregas"
    assert not (carpeta / "IMG_1234.mov").exists()
    assert not (carpeta / ".IMG_1234.mov.subiendo").exists()


def test_ftyp_invalido_corta_la_lectura_en_cuanto_recibe_ocho_bytes(entregas):
    config, _, leccion = entregas
    trozos_leidos = 0

    async def cuerpo_grande():
        nonlocal trozos_leidos
        trozos_leidos += 1
        yield b"sin_tipo"
        trozos_leidos += 1
        yield b"x" * (5 * 1024 * 1024)

    with pytest.raises(ValueError):
        asyncio.run(
            guardar_entrega(
                config,
                "react",
                4,
                "IMG_1234.mov",
                cuerpo_grande(),
                5 * 1024 * 1024 + 8,
            )
        )

    carpeta = leccion / "grabaciones" / "entregas"
    assert trozos_leidos == 1
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


def test_temporal_regular_huerfano_se_reemplaza_y_no_queda_al_final(entregas):
    _, cliente, leccion = entregas
    carpeta = leccion / "grabaciones" / "entregas"
    carpeta.mkdir(parents=True)
    temporal = carpeta / ".IMG_1234.mov.subiendo"
    temporal.write_bytes(b"subida interrumpida")
    cuerpo = _video(64)

    respuesta = _subir(cliente, "IMG_1234.mov", cuerpo)

    assert respuesta.status_code == 201
    assert (carpeta / "IMG_1234.mov").read_bytes() == cuerpo
    assert not temporal.exists()


def test_una_segunda_subida_del_mismo_nombre_en_curso_da_conflicto(entregas):
    config, _, _ = entregas
    primera_pausada = asyncio.Event()
    terminar_primera = asyncio.Event()
    cuerpo = _video(64)
    lecturas_primera = 0

    def peticion(recibir):
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
        return Request(scope, recibir)

    async def recibir_primera():
        nonlocal lecturas_primera
        lecturas_primera += 1
        if lecturas_primera == 1:
            primera_pausada.set()
            return {"type": "http.request", "body": cuerpo[:8], "more_body": True}
        await terminar_primera.wait()
        return {"type": "http.request", "body": cuerpo[8:], "more_body": False}

    async def recibir_segunda():
        return {"type": "http.request", "body": cuerpo, "more_body": False}

    async def escenario():
        tarea = asyncio.create_task(
            subir_entrega(
                peticion(recibir_primera),
                "react",
                4,
                "IMG_1234.mov",
            )
        )
        await primera_pausada.wait()
        with pytest.raises(HTTPException) as error:
            await subir_entrega(
                peticion(recibir_segunda),
                "react",
                4,
                "IMG_1234.mov",
            )
        assert error.value.status_code == 409
        terminar_primera.set()
        return await tarea

    resultado = asyncio.run(escenario())

    assert resultado.archivo == "IMG_1234.mov"


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


def test_delete_borra_analisis_antes_que_video(entregas, monkeypatch):
    _, cliente, leccion = entregas
    assert _subir(cliente, "IMG_1234.mov", _video(64)).status_code == 201
    carpeta = leccion / "grabaciones" / "entregas"
    analisis = carpeta / ".analisis"
    analisis.mkdir()
    (analisis / "IMG_1234.mov.json").write_text("{}", encoding="utf-8")
    borrados: list[str] = []
    unlink_real = modulo_entregas.os.unlink

    def registrar_unlink(ruta, *args, **kwargs):
        borrados.append(str(ruta))
        return unlink_real(ruta, *args, **kwargs)

    monkeypatch.setattr(modulo_entregas.os, "unlink", registrar_unlink)

    respuesta = cliente.delete(
        f"{RUTA_ENTREGAS}/IMG_1234.mov",
        headers={"X-Estudio-Token": TOKEN, "Content-Length": "0"},
    )

    assert respuesta.status_code == 204
    assert borrados == ["IMG_1234.mov.json", "IMG_1234.mov"]


def test_delete_exige_el_nombre_con_mayusculas_exacto(entregas):
    _, cliente, leccion = entregas
    carpeta = leccion / "grabaciones" / "entregas"
    carpeta.mkdir(parents=True)
    original = carpeta / "img_1234.mov"
    original.write_bytes(b"original")

    respuesta = cliente.delete(
        f"{RUTA_ENTREGAS}/IMG_1234.mov",
        headers={"X-Estudio-Token": TOKEN, "Content-Length": "0"},
    )

    assert respuesta.status_code == 404
    assert original.read_bytes() == b"original"


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
    assert respuesta.json()["archivos"] == [
        {"archivo": "A.mov", "bytes": 2},
        {"archivo": "z.MP4", "bytes": 1},
    ]


def test_listado_incluye_destinos_y_estado_de_ganchos(entregas):
    config, cliente, _ = entregas
    guion_ruta = config.estudio_dir / "lecciones" / "react-04.json"
    guion = json.loads(guion_ruta.read_text(encoding="utf-8"))
    guion["escenas"][0]["toma"] = {"original": "grabaciones/videos/toma.mov"}
    guion["ganchos"] = [
        {"id": "g1", "titulo": "Gancho uno", "texto": "Texto ficticio."},
        {"id": "g2", "texto": "Gancho dos ficticio."},
    ]
    guion_ruta.write_text(json.dumps(guion), encoding="utf-8")
    shorts = config.estudio_dir / "shorts" / "l4" / "shorts.json"
    shorts.parent.mkdir(parents=True)
    shorts.write_text(
        json.dumps(
            {
                "leccion": "react-04",
                "ganchosEntregados": {"g1": "12345678"},
            }
        ),
        encoding="utf-8",
    )

    respuesta = cliente.get(RUTA_ENTREGAS)

    assert respuesta.status_code == 200
    assert respuesta.json()["destinos"] == {
        "camara": [{"id": "E01", "titulo": "Presentación", "tiene_toma": True}],
        "ganchos": [
            {"id": "g1", "titulo": "Gancho uno", "entregado": True},
            {"id": "g2", "titulo": "Gancho dos ficticio.", "entregado": False},
        ],
    }


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


def test_limpieza_no_borra_entregas_si_hay_otra_subida_en_curso(entregas):
    _, _, leccion = entregas
    carpeta = leccion / "grabaciones" / "entregas"
    carpeta.mkdir(parents=True)
    clave = (carpeta, "OTRA.mov")
    with modulo_entregas._BLOQUEO_INSTALACION:
        modulo_entregas._SUBIDAS_EN_CURSO.add(clave)
    try:
        modulo_entregas._borrar_directorios_vacios((carpeta,))
        assert carpeta.is_dir()
    finally:
        with modulo_entregas._BLOQUEO_INSTALACION:
            modulo_entregas._SUBIDAS_EN_CURSO.discard(clave)


def test_docstring_carpeta_entregas_documenta_none_y_enlaces_simbolicos():
    documentacion = inspect.getdoc(carpeta_entregas) or ""

    assert "None" in documentacion
    assert "OSError" in documentacion
    assert "enlace" in documentacion.casefold()
