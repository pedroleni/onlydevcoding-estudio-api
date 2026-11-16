import pytest


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
