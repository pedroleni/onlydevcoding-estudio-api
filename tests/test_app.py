import pytest
from fastapi.testclient import TestClient

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
    assert cliente.get("/api/salud").json() == {"ok": True}


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


def test_config_sin_rutas_falla(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CURSOS_DIR", raising=False)
    monkeypatch.delenv("ESTUDIO_DIR", raising=False)
    monkeypatch.delenv("ORIGEN_WEB", raising=False)

    with pytest.raises(ValueError, match="CURSOS_DIR"):
        cargar_config()
