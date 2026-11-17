from contextlib import closing
from datetime import date, timedelta

import pytest

from estudio_api.decisiones import abrir_bd
from estudio_api.tareas import (
    CursoApp,
    TareaNueva,
    crear_curso_app,
    crear_tarea,
    marcar_hecha,
)
from tests.ayudas import TOKEN

CABECERAS = {"X-Estudio-Token": TOKEN}


def _nueva(
    *,
    fecha: str = "2026-11-17",
    texto: str = "Tarea ficticia",
    tipo: str = "grabar",
    enlace: dict | None = None,
) -> dict:
    return {
        "fecha": fecha,
        "hora": None,
        "texto": texto,
        "tipo": tipo,
        "enlace": enlace,
    }


def _crear_en_bd(cfg, **cambios):
    datos = _nueva(**cambios)
    with closing(abrir_bd(cfg.bd_ruta)) as bd:
        return crear_tarea(bd, TareaNueva.model_validate(datos))


def test_get_tareas_limita_el_rango_a_las_fechas_inclusivas(cliente, cfg):
    _crear_en_bd(cfg, fecha="2026-11-16", texto="Lunes")
    _crear_en_bd(cfg, fecha="2026-11-22", texto="Domingo")
    _crear_en_bd(cfg, fecha="2026-11-23", texto="Lunes siguiente")

    respuesta = cliente.get(
        "/api/tareas", params={"desde": "2026-11-16", "hasta": "2026-11-22"}
    )

    assert respuesta.status_code == 200
    assert [tarea["texto"] for tarea in respuesta.json()["tareas"]] == [
        "Lunes",
        "Domingo",
    ]
    assert respuesta.json()["atrasadas"] == []


@pytest.mark.parametrize(
    ("desde", "hasta"),
    [
        ("2026-01-01", "2026-03-04"),  # 63 días inclusive.
        ("2026-11-18", "2026-11-17"),
        ("no-es-fecha", "2026-11-17"),
        ("2026-11-17", "2026-02-29"),
    ],
)
def test_get_tareas_rechaza_rangos_invalidos(cliente, desde, hasta):
    respuesta = cliente.get("/api/tareas", params={"desde": desde, "hasta": hasta})

    assert respuesta.status_code == 422


def test_get_tareas_admite_exactamente_62_dias_inclusive(cliente):
    desde = date(2026, 1, 1)
    hasta = desde + timedelta(days=61)

    respuesta = cliente.get(
        "/api/tareas",
        params={"desde": desde.isoformat(), "hasta": hasta.isoformat()},
    )

    assert respuesta.status_code == 200


def test_get_tareas_devuelve_solo_las_atrasadas_pendientes(cliente, cfg):
    pendiente = _crear_en_bd(cfg, fecha="2026-11-16", texto="Pendiente")
    hecha = _crear_en_bd(cfg, fecha="2026-11-16", texto="Hecha")
    _crear_en_bd(cfg, fecha="2026-11-17", texto="Hoy")
    with closing(abrir_bd(cfg.bd_ruta)) as bd:
        assert marcar_hecha(bd, hecha.id, True) is not None

    respuesta = cliente.get(
        "/api/tareas",
        params={
            "desde": "2026-11-17",
            "hasta": "2026-11-17",
            "atrasadas": "true",
        },
    )

    assert respuesta.status_code == 200
    assert [tarea["id"] for tarea in respuesta.json()["atrasadas"]] == [pendiente.id]
    assert [tarea["texto"] for tarea in respuesta.json()["tareas"]] == ["Hoy"]


def test_crear_tarea_con_enlace_valido_resuelve_los_titulos(cliente_con_token):
    respuesta = cliente_con_token.post(
        "/api/tareas",
        headers=CABECERAS,
        json=_nueva(
            enlace={
                "curso": "react",
                "numero": 4,
                "pieza": "reel-salida",
                "red": "instagram",
            }
        ),
    )

    assert respuesta.status_code == 201
    assert respuesta.json()["enlace_vista"] == {
        "curso_nombre": "React",
        "leccion_titulo": "Importar componentes",
        "pieza_titulo": "Reel salida",
        "roto": False,
    }


@pytest.mark.parametrize(
    ("enlace", "detalle"),
    [
        ({"curso": "no-existe"}, "El curso no existe"),
        ({"curso": "react", "numero": 99}, "La lección no existe"),
        (
            {"curso": "react", "numero": 4, "pieza": "short-7"},
            "La pieza no existe",
        ),
    ],
)
def test_crear_tarea_rechaza_enlaces_inexistentes(cliente_con_token, enlace, detalle):
    respuesta = cliente_con_token.post(
        "/api/tareas", headers=CABECERAS, json=_nueva(enlace=enlace)
    )

    assert respuesta.status_code == 422
    assert respuesta.json()["detail"] == detalle


def test_curso_sin_carpeta_solo_se_enlaza_a_nivel_de_curso(cliente_con_token, cfg):
    with closing(abrir_bd(cfg.bd_ruta)) as bd:
        crear_curso_app(bd, CursoApp(id="python", nombre="Python"))

    invalida = cliente_con_token.post(
        "/api/tareas",
        headers=CABECERAS,
        json=_nueva(enlace={"curso": "python", "numero": 1}),
    )
    valida = cliente_con_token.post(
        "/api/tareas",
        headers=CABECERAS,
        json=_nueva(enlace={"curso": "python"}),
    )

    assert invalida.status_code == 422
    assert (
        invalida.json()["detail"]
        == "Un curso sin carpeta solo se puede enlazar a nivel de curso"
    )
    assert valida.status_code == 201
    assert valida.json()["enlace_vista"] == {
        "curso_nombre": "Python",
        "leccion_titulo": None,
        "pieza_titulo": None,
        "roto": False,
    }


def test_crear_y_editar_rechazan_un_tipo_inexistente(cliente_con_token):
    creacion = cliente_con_token.post(
        "/api/tareas",
        headers=CABECERAS,
        json=_nueva(tipo="inventado"),
    )
    creada = cliente_con_token.post("/api/tareas", headers=CABECERAS, json=_nueva())
    assert creada.status_code == 201

    edicion = cliente_con_token.put(
        f"/api/tareas/{creada.json()['id']}",
        headers=CABECERAS,
        json=_nueva(tipo="inventado"),
    )

    assert creacion.status_code == 422
    assert creacion.json()["detail"] == "El tipo de tarea no existe"
    assert edicion.status_code == 422
    assert edicion.json()["detail"] == "El tipo de tarea no existe"


def test_editar_valida_el_enlace_igual_que_crear(cliente_con_token):
    creada = cliente_con_token.post("/api/tareas", headers=CABECERAS, json=_nueva())
    assert creada.status_code == 201

    respuesta = cliente_con_token.put(
        f"/api/tareas/{creada.json()['id']}",
        headers=CABECERAS,
        json=_nueva(enlace={"curso": "react", "numero": 99}),
    )

    assert respuesta.status_code == 422
    assert respuesta.json()["detail"] == "La lección no existe"


def test_enlace_a_pieza_borrada_se_conserva_como_roto(cliente, cfg):
    tarea = _crear_en_bd(
        cfg,
        enlace={
            "curso": "react",
            "numero": 4,
            "pieza": "reel-salida",
            "red": "instagram",
        },
    )
    reel = (
        cfg.cursos_dir
        / "REACT"
        / "04-importar-y-exportar"
        / "publicar"
        / "2-shorts-y-reels"
        / "reel-salida.mp4"
    )
    reel.unlink()

    respuesta = cliente.get(
        "/api/tareas",
        params={"desde": "2026-11-17", "hasta": "2026-11-17"},
    )

    assert respuesta.status_code == 200
    vista = next(t for t in respuesta.json()["tareas"] if t["id"] == tarea.id)
    assert vista["enlace_vista"] == {
        "curso_nombre": "React",
        "leccion_titulo": "Importar componentes",
        "pieza_titulo": None,
        "roto": True,
    }


def test_enlace_a_leccion_renombrada_se_conserva_como_roto(cliente, cfg):
    tarea = _crear_en_bd(
        cfg,
        enlace={"curso": "react", "numero": 4, "pieza": "leccion"},
    )
    origen = cfg.cursos_dir / "REACT" / "04-importar-y-exportar"
    origen.rename(cfg.cursos_dir / "REACT" / "06-renombrada")

    respuesta = cliente.get(
        "/api/tareas",
        params={"desde": "2026-11-17", "hasta": "2026-11-17"},
    )

    assert respuesta.status_code == 200
    vista = next(t for t in respuesta.json()["tareas"] if t["id"] == tarea.id)
    assert vista["enlace_vista"]["roto"] is True
    assert vista["enlace_vista"]["leccion_titulo"] is None
    assert vista["enlace_vista"]["pieza_titulo"] is None


def test_excepcion_al_leer_guion_no_tumba_el_listado(cliente, cfg, monkeypatch):
    from estudio_api import vista_tareas

    tarea = _crear_en_bd(
        cfg,
        enlace={"curso": "react", "numero": 4, "pieza": "reel-salida"},
    )

    def lectura_corrupta(*_args, **_kwargs):
        raise ValueError("guion ficticio corrupto")

    monkeypatch.setattr(vista_tareas, "leer_leccion", lectura_corrupta)

    respuesta = cliente.get(
        "/api/tareas",
        params={"desde": "2026-11-17", "hasta": "2026-11-17"},
    )

    assert respuesta.status_code == 200
    vista = next(t for t in respuesta.json()["tareas"] if t["id"] == tarea.id)
    assert vista["enlace_vista"]["roto"] is True
    assert vista["enlace_vista"]["pieza_titulo"] is None


def test_vista_lee_una_leccion_una_sola_vez_por_peticion(cliente, cfg, monkeypatch):
    from estudio_api import vista_tareas

    for indice in range(3):
        _crear_en_bd(
            cfg,
            texto=f"Tarea {indice}",
            enlace={"curso": "react", "numero": 4, "pieza": "reel-salida"},
        )

    original = vista_tareas.leer_leccion
    llamadas = 0

    def contar(*args, **kwargs):
        nonlocal llamadas
        llamadas += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(vista_tareas, "leer_leccion", contar)

    respuesta = cliente.get(
        "/api/tareas",
        params={"desde": "2026-11-17", "hasta": "2026-11-17"},
    )

    assert respuesta.status_code == 200
    assert len(respuesta.json()["tareas"]) == 3
    assert llamadas == 1


def test_crud_de_tarea_y_booleano_de_hecha_es_estricto(cliente_con_token):
    creada = cliente_con_token.post("/api/tareas", headers=CABECERAS, json=_nueva())
    assert creada.status_code == 201
    tarea_id = creada.json()["id"]

    editada = cliente_con_token.put(
        f"/api/tareas/{tarea_id}",
        headers=CABECERAS,
        json=_nueva(texto="Tarea editada"),
    )
    cadena = cliente_con_token.put(
        f"/api/tareas/{tarea_id}/hecha",
        headers=CABECERAS,
        json={"hecha": "true"},
    )
    hecha = cliente_con_token.put(
        f"/api/tareas/{tarea_id}/hecha",
        headers=CABECERAS,
        json={"hecha": True},
    )
    borrada = cliente_con_token.request(
        "DELETE", f"/api/tareas/{tarea_id}", headers=CABECERAS, json={}
    )
    ausente = cliente_con_token.request(
        "DELETE", f"/api/tareas/{tarea_id}", headers=CABECERAS, json={}
    )

    assert editada.status_code == 200
    assert editada.json()["texto"] == "Tarea editada"
    assert cadena.status_code == 422
    assert hecha.status_code == 200
    assert hecha.json()["hecha"] is True
    assert hecha.json()["hecha_en"] is not None
    assert borrada.status_code == 204
    assert borrada.content == b""
    assert ausente.status_code == 404


@pytest.mark.parametrize("ruta", ["/api/tareas/0", "/api/tareas/-1"])
def test_ids_de_tarea_deben_ser_positivos(cliente_con_token, ruta):
    respuesta = cliente_con_token.put(ruta, headers=CABECERAS, json=_nueva())

    assert respuesta.status_code == 422


def test_operaciones_sobre_tarea_inexistente_devuelven_404(cliente_con_token):
    edicion = cliente_con_token.put("/api/tareas/999", headers=CABECERAS, json=_nueva())
    hecha = cliente_con_token.put(
        "/api/tareas/999/hecha", headers=CABECERAS, json={"hecha": True}
    )

    assert edicion.status_code == 404
    assert hecha.status_code == 404


def test_crud_de_tipos_y_orden_del_listado(cliente_con_token):
    iniciales = cliente_con_token.get("/api/tipos-tarea")
    creada = cliente_con_token.post(
        "/api/tipos-tarea",
        headers=CABECERAS,
        json={
            "id": "revisar",
            "nombre": "Revisar",
            "color": "#299BC6",
            "orden": 0,
        },
    )
    ordenados = cliente_con_token.get("/api/tipos-tarea")
    duplicada = cliente_con_token.post(
        "/api/tipos-tarea",
        headers=CABECERAS,
        json={
            "id": "revisar",
            "nombre": "Otra",
            "color": "#6CCBEF",
            "orden": 8,
        },
    )
    editada = cliente_con_token.put(
        "/api/tipos-tarea/revisar",
        headers=CABECERAS,
        json={"nombre": "Revisión", "color": "#6CCBEF", "orden": 7},
    )
    ausente = cliente_con_token.put(
        "/api/tipos-tarea/no-existe",
        headers=CABECERAS,
        json={"nombre": "Nada", "color": "#6CCBEF", "orden": 7},
    )
    borrada = cliente_con_token.request(
        "DELETE", "/api/tipos-tarea/revisar", headers=CABECERAS, json={}
    )

    assert iniciales.status_code == 200
    assert [tipo["id"] for tipo in iniciales.json()] == [
        "preparar",
        "grabar",
        "editar",
        "publicar",
        "otro",
    ]
    assert creada.status_code == 201
    assert creada.json()["id"] == "revisar"
    assert ordenados.json()[0]["id"] == "revisar"
    assert duplicada.status_code == 409
    assert duplicada.json()["detail"] == "Ya existe un tipo con ese id"
    assert editada.status_code == 200
    assert editada.json() == {
        "id": "revisar",
        "nombre": "Revisión",
        "color": "#6CCBEF",
        "orden": 7,
    }
    assert ausente.status_code == 404
    assert borrada.status_code == 204
    assert borrada.content == b""
    assert (
        cliente_con_token.request(
            "DELETE", "/api/tipos-tarea/revisar", headers=CABECERAS, json={}
        ).status_code
        == 404
    )


def test_borrar_tipo_en_uso_da_409_y_conserva_la_tarea(cliente_con_token, cfg):
    tarea = _crear_en_bd(cfg, tipo="grabar")

    respuesta = cliente_con_token.request(
        "DELETE", "/api/tipos-tarea/grabar", headers=CABECERAS, json={}
    )

    assert respuesta.status_code == 409
    assert (
        respuesta.json()["detail"]
        == "Hay tareas de este tipo; cámbialas antes de borrarlo"
    )
    with closing(abrir_bd(cfg.bd_ruta)) as bd:
        assert bd.execute("SELECT id FROM tarea WHERE id = ?", (tarea.id,)).fetchone()


@pytest.mark.parametrize(
    ("metodo", "ruta", "json"),
    [
        ("post", "/api/tareas", _nueva()),
        ("delete", "/api/tareas/1", None),
    ],
)
def test_escrituras_de_tareas_sin_token_devuelven_401(
    cliente_con_token, metodo, ruta, json
):
    respuesta = cliente_con_token.request(metodo, ruta, json=json)

    assert respuesta.status_code == 401


def test_origin_ajeno_devuelve_403(cliente_con_token):
    respuesta = cliente_con_token.get(
        "/api/tareas",
        headers={"Origin": "https://ejemplo.invalid"},
        params={"desde": "2026-11-17", "hasta": "2026-11-17"},
    )

    assert respuesta.status_code == 403


@pytest.mark.parametrize(
    ("ruta", "cuerpo"),
    [
        ("/api/tareas", {**_nueva(), "extra": "no"}),
        (
            "/api/tipos-tarea",
            {
                "id": "revisar",
                "nombre": "Revisar",
                "color": "#299BC6",
                "orden": 9,
                "extra": "no",
            },
        ),
    ],
)
def test_cuerpos_con_campos_extra_devuelven_422(cliente_con_token, ruta, cuerpo):
    respuesta = cliente_con_token.post(ruta, headers=CABECERAS, json=cuerpo)

    assert respuesta.status_code == 422
