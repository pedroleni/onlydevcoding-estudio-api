import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from estudio_api.app import crear_app
from estudio_api.config import Config
from tests import ayudas


@pytest.fixture
def datos_falsos(tmp_path, monkeypatch):
    """Un ``datos/`` de mentira en el directorio actual: nunca el del repo."""
    repo_falso = tmp_path / "repo"
    datos = repo_falso / "datos"
    datos.mkdir(parents=True)
    monkeypatch.chdir(repo_falso)
    monkeypatch.setattr(ayudas, "DATOS_REALES", datos)
    return datos


def test_sqlite3_connect_esta_vigilado_en_cada_test():
    assert sqlite3.connect.__name__ == "conectar"
    assert sqlite3.connect.__module__ == "tests.ayudas"


def test_abrir_una_base_de_datos_falla_al_instante_sin_crearla(datos_falsos):
    with pytest.raises(ayudas.BaseRealProtegida):
        sqlite3.connect(datos_falsos / "estudio.sqlite3")
    with pytest.raises(ayudas.BaseRealProtegida):
        sqlite3.connect("datos/estudio.sqlite3")
    with pytest.raises(ayudas.BaseRealProtegida):
        sqlite3.connect(f"file:{datos_falsos / 'estudio.sqlite3'}?mode=ro", uri=True)

    assert list(datos_falsos.iterdir()) == []


def test_el_cliente_viejo_de_test_app_sin_bd_ruta_falla_al_instante(
    tmp_path, datos_falsos
):
    # Así era el fixture ``cliente`` de test_app.py que migró la base real:
    # un Config sin ``bd_ruta`` usa ``datos/estudio.sqlite3`` del directorio
    # actual.
    config = Config(cursos_dir=tmp_path, estudio_dir=tmp_path)

    # ``crear_app`` ya abre la base para recoger los trabajos huérfanos: el
    # error salta ahí, antes de la primera petición.
    with pytest.raises(ayudas.BaseRealProtegida):
        TestClient(crear_app(config), base_url="http://127.0.0.1:8000")

    assert list(datos_falsos.iterdir()) == []


def test_las_bases_fuera_de_datos_se_abren_con_normalidad(tmp_path, datos_falsos):
    ruta = tmp_path / "otra" / "estudio.sqlite3"
    ruta.parent.mkdir()

    with closing(sqlite3.connect(ruta)) as bd:
        assert bd.execute("SELECT 1").fetchone() == (1,)
    with closing(sqlite3.connect(":memory:")) as bd:
        assert bd.execute("SELECT 2").fetchone() == (2,)
