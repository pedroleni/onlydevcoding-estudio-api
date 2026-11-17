from contextlib import closing

import pytest

from estudio_api import rutas_api
from estudio_api.decisiones import abrir_bd
from estudio_api.tareas import (
    CursoApp,
    EnlaceTarea,
    TareaNueva,
    crear_curso_app,
    crear_tarea,
)
from tests.ayudas import TOKEN
from tests.test_publicar_api import RUTA_PUBLICACION, _carpeta_leccion


def test_cursos(cliente):
    respuesta = cliente.get("/api/cursos")

    assert respuesta.status_code == 200
    assert respuesta.json()[0]["id"] == "react"


def test_alta_curso_app_se_lista_despues_de_los_cursos_en_disco(
    cliente_con_token,
):
    respuesta = cliente_con_token.post(
        "/api/cursos",
        headers={"X-Estudio-Token": TOKEN},
        json={"id": "python", "nombre": "Python"},
    )

    assert respuesta.status_code == 201
    assert respuesta.json() == {
        "id": "python",
        "nombre": "Python",
        "carpeta": None,
        "lecciones": 0,
        "en_disco": False,
    }
    cursos = cliente_con_token.get("/api/cursos").json()
    assert [curso["id"] for curso in cursos] == ["react", "python"]
    assert cursos[0]["en_disco"] is True


def test_alta_curso_rechaza_ids_que_ya_existen_en_disco(cliente_con_token):
    respuesta = cliente_con_token.post(
        "/api/cursos",
        headers={"X-Estudio-Token": TOKEN},
        json={"id": "react", "nombre": "Otro React"},
    )

    assert respuesta.status_code == 409


def test_alta_curso_acepta_una_carpeta_de_curso_vacia_preexistente(
    cliente_con_token, cfg
):
    # Mismo criterio que el listado: una carpeta sin lecciones aún no es un curso.
    (cfg.cursos_dir / "PYTHON").mkdir()

    respuesta = cliente_con_token.post(
        "/api/cursos",
        headers={"X-Estudio-Token": TOKEN},
        json={"id": "python", "nombre": "Python"},
    )

    assert respuesta.status_code == 201
    assert respuesta.json()["en_disco"] is True


def test_alta_curso_rechaza_ids_que_ya_existen_en_la_app(cliente_con_token):
    datos = {"id": "python", "nombre": "Python"}
    cabeceras = {"X-Estudio-Token": TOKEN}
    assert (
        cliente_con_token.post("/api/cursos", headers=cabeceras, json=datos).status_code
        == 201
    )

    respuesta = cliente_con_token.post(
        "/api/cursos",
        headers=cabeceras,
        json={"id": "python", "nombre": "Otro nombre"},
    )

    assert respuesta.status_code == 409


def test_alta_curso_no_lee_los_guiones_para_comprobar_si_existe(
    cliente_con_token, monkeypatch
):
    def fallar_si_lee_cursos(*_args, **_kwargs):
        raise AssertionError("POST /api/cursos no debe leer los guiones")

    monkeypatch.setattr(rutas_api, "leer_cursos", fallar_si_lee_cursos)

    respuesta = cliente_con_token.post(
        "/api/cursos",
        headers={"X-Estudio-Token": TOKEN},
        json={"id": "python", "nombre": "Python"},
    )

    assert respuesta.status_code == 201


def test_alta_curso_sin_token_devuelve_401(cliente_con_token):
    respuesta = cliente_con_token.post(
        "/api/cursos",
        json={"id": "python", "nombre": "Python"},
    )

    assert respuesta.status_code == 401


def test_carpeta_de_curso_vacia_sin_alta_no_es_un_curso(cliente_con_token, cfg):
    # Mismo criterio que el listado: sin lecciones ni alta en la app, no existe.
    (cfg.cursos_dir / "VACIO").mkdir()

    respuesta = cliente_con_token.get("/api/cursos/vacio/lecciones")

    assert respuesta.status_code == 404
    assert "vacio" not in {
        curso["id"] for curso in cliente_con_token.get("/api/cursos").json()
    }


def test_curso_app_con_carpeta_vacia_posterior_devuelve_lecciones_vacias(
    cliente_con_token, cfg
):
    alta = cliente_con_token.post(
        "/api/cursos",
        headers={"X-Estudio-Token": TOKEN},
        json={"id": "python", "nombre": "Python"},
    )
    assert alta.status_code == 201
    (cfg.cursos_dir / "PYTHON").mkdir()

    respuesta = cliente_con_token.get("/api/cursos/python/lecciones")

    assert respuesta.status_code == 200
    assert respuesta.json() == []
    assert cliente_con_token.get("/api/cursos/python/lecciones/1").status_code == 404


def test_curso_inexistente_sigue_devolviendo_404_al_listar_lecciones(
    cliente_con_token,
):
    respuesta = cliente_con_token.get("/api/cursos/no-existe/lecciones")

    assert respuesta.status_code == 404


def test_curso_app_que_aparece_en_disco_se_lista_una_vez(cliente_con_token, cfg):
    alta = cliente_con_token.post(
        "/api/cursos",
        headers={"X-Estudio-Token": TOKEN},
        json={"id": "python", "nombre": "Python"},
    )
    assert alta.status_code == 201
    (cfg.cursos_dir / "PYTHON").mkdir()

    cursos = cliente_con_token.get("/api/cursos").json()
    python = [curso for curso in cursos if curso["id"] == "python"]

    assert len(python) == 1
    assert python[0]["en_disco"] is True
    assert python[0]["carpeta"] == "cursos/PYTHON"


def test_curso_app_que_coincide_con_curso_de_disco_con_lecciones_no_se_duplica(
    cliente_con_token, cfg
):
    with closing(abrir_bd(cfg.bd_ruta)) as bd:
        crear_curso_app(bd, CursoApp(id="react", nombre="React desde la app"))

    cursos = cliente_con_token.get("/api/cursos").json()
    react = [curso for curso in cursos if curso["id"] == "react"]

    assert len(react) == 1
    assert react[0]["en_disco"] is True
    assert react[0]["lecciones"] == 2


def test_borrar_curso_app_con_tarea_da_409_y_sin_tarea_da_204(cliente_con_token, cfg):
    cabeceras = {"X-Estudio-Token": TOKEN}
    alta = cliente_con_token.post(
        "/api/cursos",
        headers=cabeceras,
        json={"id": "python", "nombre": "Python"},
    )
    assert alta.status_code == 201
    with closing(abrir_bd(cfg.bd_ruta)) as bd:
        tarea = crear_tarea(
            bd,
            TareaNueva(
                fecha="2026-11-17",
                texto="Preparar curso ficticio",
                tipo="preparar",
                enlace=EnlaceTarea(curso="python"),
            ),
        )

    bloqueado = cliente_con_token.request(
        "DELETE", "/api/cursos/python", headers=cabeceras, json={}
    )
    assert bloqueado.status_code == 409
    with closing(abrir_bd(cfg.bd_ruta)) as bd:
        assert bd.execute("SELECT id FROM tarea WHERE id = ?", (tarea.id,)).fetchone()
        bd.execute("DELETE FROM tarea WHERE id = ?", (tarea.id,))
        bd.commit()

    borrado = cliente_con_token.request(
        "DELETE", "/api/cursos/python", headers=cabeceras, json={}
    )
    assert borrado.status_code == 204
    no_existe = cliente_con_token.request(
        "DELETE", "/api/cursos/python", headers=cabeceras, json={}
    )
    assert no_existe.status_code == 404


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
