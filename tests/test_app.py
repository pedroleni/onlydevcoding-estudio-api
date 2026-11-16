import asyncio

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from estudio_api.app import crear_app
from estudio_api.config import Config, cargar_config


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
        mensaje
        for mensaje in mensajes
        if mensaje["type"] == "http.response.start"
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
        headers={"Origin": "http://localhost:3000"},
    )

    assert respuesta.status_code == 200


def test_preflight_origen_web_aceptado(cliente):
    respuesta = cliente.options(
        "/api/salud",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert respuesta.status_code == 200
    assert (
        respuesta.headers["access-control-allow-origin"]
        == "http://localhost:3000"
    )


def test_preflight_origen_ajeno_rechazado(cliente):
    respuesta = cliente.options(
        "/api/salud",
        headers={
            "Origin": "https://evil.com",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert respuesta.status_code == 403


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
