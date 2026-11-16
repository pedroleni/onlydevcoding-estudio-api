import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from estudio_api.app import crear_app
from estudio_api.config import Config, cargar_config
from tests.conftest import TOKEN


@pytest.fixture
def cliente(tmp_path):
    config = Config(cursos_dir=tmp_path, estudio_dir=tmp_path)
    return TestClient(
        crear_app(config),
        base_url="http://127.0.0.1:8000",
    )


def test_salud(cliente):
    respuesta = cliente.get("/api/salud")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"ok": True}


def test_peticion_sin_host_rechazada(cliente):
    async def ejecutar_peticion():
        mensajes = []

        async def recibir():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def enviar(mensaje):
            mensajes.append(mensaje)

        await cliente.app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/api/salud",
                "raw_path": b"/api/salud",
                "query_string": b"",
                "headers": [],
                "client": ("127.0.0.1", 50000),
                "server": ("127.0.0.1", 8000),
                "root_path": "",
            },
            recibir,
            enviar,
        )
        return mensajes

    mensajes = asyncio.run(ejecutar_peticion())

    inicio_respuesta = next(
        mensaje for mensaje in mensajes if mensaje["type"] == "http.response.start"
    )
    assert inicio_respuesta["status"] == 400


def test_host_localhost_aceptado(cliente):
    respuesta = cliente.get(
        "/api/salud",
        headers={"Host": "localhost:8000"},
    )

    assert respuesta.status_code == 200


def test_host_ajeno_rechazado(cliente):
    respuesta = cliente.get("/api/salud", headers={"Host": "evil.com"})

    assert respuesta.status_code == 400


def test_origen_ajeno_rechazado(cliente):
    respuesta = cliente.get(
        "/api/salud",
        headers={"Origin": "https://evil.com"},
    )

    assert respuesta.status_code == 403


def test_origen_web_aceptado(cliente):
    respuesta = cliente.get(
        "/api/salud",
        headers={"Origin": "http://127.0.0.1:3000"},
    )

    assert respuesta.status_code == 200


def test_preflight_origen_web_aceptado(cliente):
    respuesta = cliente.options(
        "/api/salud",
        headers={
            "Origin": "http://127.0.0.1:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert respuesta.status_code == 200
    assert respuesta.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"


def test_preflight_origen_ajeno_rechazado(cliente):
    respuesta = cliente.options(
        "/api/salud",
        headers={
            "Origin": "https://evil.com",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert respuesta.status_code == 403


def test_put_sin_token_401(cliente_con_token):
    assert cliente_con_token.put("/api/salud").status_code == 401


def test_put_token_malo_401(cliente_con_token):
    respuesta = cliente_con_token.put(
        "/api/salud",
        headers={"X-Estudio-Token": "otro"},
    )

    assert respuesta.status_code == 401


def test_put_sin_configurar_503(cliente):
    respuesta = cliente.put(
        "/api/salud",
        headers={"X-Estudio-Token": "x"},
    )

    assert respuesta.status_code == 503
    assert respuesta.text == "Escrituras desactivadas: falta ESTUDIO_TOKEN"


def test_put_token_bueno_pasa(cliente_con_token):
    respuesta = cliente_con_token.put(
        "/api/salud",
        headers={"X-Estudio-Token": TOKEN},
    )

    assert respuesta.status_code == 405


def test_cuerpo_grande_413(cliente_con_token):
    respuesta = cliente_con_token.put(
        "/api/salud",
        headers={"X-Estudio-Token": TOKEN},
        content=b"x" * (256 * 1024 + 1),
    )

    assert respuesta.status_code == 413


def test_escritura_sin_content_length_411(cliente_con_token):
    async def ejecutar_peticion():
        mensajes = []

        async def recibir():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def enviar(mensaje):
            mensajes.append(mensaje)

        await cliente_con_token.app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "PUT",
                "scheme": "http",
                "path": "/api/salud",
                "raw_path": b"/api/salud",
                "query_string": b"",
                "headers": [
                    (b"host", b"127.0.0.1:8000"),
                    (b"x-estudio-token", TOKEN.encode()),
                ],
                "client": ("127.0.0.1", 50000),
                "server": ("127.0.0.1", 8000),
                "root_path": "",
            },
            recibir,
            enviar,
        )
        return mensajes

    mensajes = asyncio.run(ejecutar_peticion())
    inicio = next(
        mensaje for mensaje in mensajes if mensaje["type"] == "http.response.start"
    )

    assert inicio["status"] == 411


def test_escritura_con_content_length_invalido_411(cliente_con_token):
    respuesta = cliente_con_token.put(
        "/api/salud",
        headers={
            "X-Estudio-Token": TOKEN,
            "Content-Length": "invalido",
        },
    )

    assert respuesta.status_code == 411


def test_cors_no_permite_put(cliente_con_token):
    respuesta = cliente_con_token.options(
        "/api/salud",
        headers={
            "Origin": "http://127.0.0.1:3000",
            "Access-Control-Request-Method": "PUT",
        },
    )

    assert "PUT" not in respuesta.headers.get("access-control-allow-methods", "")


@pytest.mark.parametrize(
    "cabeceras",
    [
        {"Host": "evil.com"},
        {"Origin": "https://evil.com"},
    ],
)
def test_websocket_ajeno_rechazado(cliente, cabeceras):
    with (
        pytest.raises(WebSocketDisconnect) as error,
        cliente.websocket_connect("/ws", headers=cabeceras),
    ):
        pass

    assert error.value.code == 1008


def test_config_sin_rutas_falla(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CURSOS_DIR", raising=False)
    monkeypatch.delenv("ESTUDIO_DIR", raising=False)
    monkeypatch.delenv("ORIGEN_WEB", raising=False)

    with pytest.raises(ValueError, match="CURSOS_DIR"):
        cargar_config()


def test_origen_web_por_defecto_usa_127_0_0_1(tmp_path):
    config = Config(cursos_dir=tmp_path, estudio_dir=tmp_path)

    assert config.origen_web == "http://127.0.0.1:3000"


def test_config_escritura_por_defecto(tmp_path):
    config = Config(cursos_dir=tmp_path, estudio_dir=tmp_path)

    assert config.token_escritura is None
    assert config.bd_ruta == Path("datos/estudio.sqlite3")


def test_config_carga_token_y_ruta_bd(monkeypatch, tmp_path):
    cursos_dir = tmp_path / "cursos"
    estudio_dir = tmp_path / "estudio"
    cursos_dir.mkdir()
    estudio_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CURSOS_DIR", str(cursos_dir))
    monkeypatch.setenv("ESTUDIO_DIR", str(estudio_dir))
    monkeypatch.setenv("ESTUDIO_TOKEN", TOKEN)
    monkeypatch.setenv("BD_RUTA", "datos-prueba/api.sqlite3")

    config = cargar_config()

    assert config.token_escritura == TOKEN
    assert config.bd_ruta == Path("datos-prueba/api.sqlite3")


@pytest.mark.parametrize("ruta", ["/docs", "/redoc", "/openapi.json"])
def test_documentacion_interactiva_desactivada(cliente, ruta):
    # /docs y /redoc cargan JavaScript de un CDN en el mismo origen que la API.
    assert cliente.get(ruta).status_code == 404
