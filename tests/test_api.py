import pytest

from tests.test_publicar_api import RUTA_PUBLICACION, _carpeta_leccion


def test_cursos(cliente):
    respuesta = cliente.get("/api/cursos")

    assert respuesta.status_code == 200
    assert respuesta.json()[0]["id"] == "react"


def test_lecciones_de_curso(cliente):
    respuesta = cliente.get("/api/cursos/react/lecciones")

    assert respuesta.status_code == 200
    assert [leccion["numero"] for leccion in respuesta.json()] == [4, 5]


def test_detalle_de_leccion(cliente):
    respuesta = cliente.get("/api/cursos/react/lecciones/4")

    assert respuesta.status_code == 200
    assert respuesta.json()["titulo"] == "Importar componentes"


@pytest.mark.parametrize(
    "ruta",
    [
        "/api/cursos/no-existe/lecciones",
        "/api/cursos/react/lecciones/99",
    ],
)
def test_curso_o_leccion_inexistente_devuelve_404(cliente, ruta):
    assert cliente.get(ruta).status_code == 404


def test_curso_invalido(cliente):
    respuesta = cliente.get("/api/cursos/..%2Fx/lecciones")

    assert respuesta.status_code in (404, 422)


@pytest.mark.parametrize("numero", [0, 1000])
def test_numero_fuera_de_rango(cliente, numero):
    assert cliente.get(f"/api/cursos/react/lecciones/{numero}").status_code in (
        404,
        422,
    )


def test_publicacion_corrupta_no_rompe_los_endpoints_de_la_leccion(cliente, cfg):
    ruta = _carpeta_leccion(cfg) / "publicar" / "publicacion.json"
    ruta.write_text("{json roto", encoding="utf-8")

    publicacion = cliente.get(RUTA_PUBLICACION)
    detalle = cliente.get("/api/cursos/react/lecciones/4")
    lista = cliente.get("/api/cursos/react/lecciones")

    assert publicacion.status_code == 200
    assert publicacion.json()["error"] == "No se ha podido leer publicacion.json"
    assert detalle.status_code == 200
    assert lista.status_code == 200
