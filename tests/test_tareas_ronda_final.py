import json
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta

import pytest
from pydantic import ValidationError

import estudio_api.tareas as modulo_tareas
import estudio_api.vista_tareas as modulo_vista
from estudio_api.decisiones import abrir_bd
from estudio_api.tareas import (
    CursoApp,
    TareaNueva,
    TipoTarea,
    crear_tarea,
    marcar_hecha,
    tareas_atrasadas,
)
from tests.ayudas import TOKEN

CABECERAS = {"X-Estudio-Token": TOKEN}


def _nueva(**cambios) -> dict:
    datos = {
        "fecha": "2026-11-17",
        "hora": None,
        "texto": "Tarea ficticia",
        "tipo": "grabar",
        "enlace": None,
    }
    datos.update(cambios)
    return datos


def _guion_sin_carpeta(cfg, numero: int = 6) -> None:
    guion = {
        "ficha": "React",
        "numero": numero,
        "titulo": "Lección por grabar",
        "carpeta": f"REACT/{numero:02d}-por-grabar",
        "escenas": [],
    }
    (cfg.estudio_dir / "lecciones" / f"react-{numero:02d}.json").write_text(
        json.dumps(guion), encoding="utf-8"
    )


# I1: una lección que solo tiene guion se puede enlazar y no sale rota.
def test_enlace_a_leccion_solo_con_guion(cliente_con_token, cfg):
    _guion_sin_carpeta(cfg)
    numeros = [
        leccion["numero"]
        for leccion in cliente_con_token.get("/api/cursos/react/lecciones").json()
    ]
    assert 6 in numeros

    respuesta = cliente_con_token.post(
        "/api/tareas",
        headers=CABECERAS,
        json=_nueva(enlace={"curso": "react", "numero": 6}),
    )

    assert respuesta.status_code == 201
    assert respuesta.json()["enlace_vista"] == {
        "curso_nombre": "React",
        "leccion_titulo": "Lección por grabar",
        "pieza_titulo": None,
        "roto": False,
    }


# I2: el alta y el listado usan el mismo criterio de existencia.
def test_carpeta_de_curso_vacia_permite_el_alta_y_aparece_en_la_lista(
    cliente_con_token, cfg
):
    (cfg.cursos_dir / "PYTHON").mkdir()

    alta = cliente_con_token.post(
        "/api/cursos", headers=CABECERAS, json={"id": "python", "nombre": "Python"}
    )

    assert alta.status_code == 201
    cursos = {
        curso["id"]: curso for curso in cliente_con_token.get("/api/cursos").json()
    }
    assert cursos["python"]["nombre"] == "Python"
    assert cursos["python"]["en_disco"] is True
    assert cliente_con_token.get("/api/cursos/python/lecciones").json() == []


def test_carpeta_suelta_sin_alta_no_es_un_curso(cliente_con_token):
    respuesta = cliente_con_token.post(
        "/api/tareas",
        headers=CABECERAS,
        json=_nueva(enlace={"curso": "asset"}),
    )

    assert respuesta.status_code == 422
    assert respuesta.json()["detail"] == "El curso no existe"
    assert cliente_con_token.get("/api/cursos/asset/lecciones").status_code == 404


# M1: crear una tarea y borrar su curso de la app no pueden dejar una huérfana.
def test_alta_de_tarea_rechaza_un_curso_borrado_tras_validar(
    cliente_con_token, cfg, monkeypatch
):
    with closing(abrir_bd(cfg.bd_ruta)) as bd:
        modulo_tareas.crear_curso_app(bd, CursoApp(id="python", nombre="Python"))

    import estudio_api.rutas_tareas as rutas

    original = rutas._validar_tarea_nueva

    def validar_y_borrar(config, bd, nueva):
        original(config, bd, nueva)
        with closing(sqlite3.connect(cfg.bd_ruta)) as otra:
            otra.execute("DELETE FROM curso_app WHERE id = 'python'")
            otra.commit()

    monkeypatch.setattr(rutas, "_validar_tarea_nueva", validar_y_borrar)

    respuesta = cliente_con_token.post(
        "/api/tareas", headers=CABECERAS, json=_nueva(enlace={"curso": "python"})
    )

    assert respuesta.status_code == 422
    with closing(abrir_bd(cfg.bd_ruta)) as bd:
        assert bd.execute("SELECT COUNT(*) FROM tarea").fetchone()[0] == 0


# M2: con más de 200 atrasadas, las más recientes no desaparecen.
def test_atrasadas_conserva_las_mas_recientes(cfg):
    hoy = date(2026, 11, 17)
    with closing(abrir_bd(cfg.bd_ruta)) as bd:
        for dias in range(1, 206):
            crear_tarea(
                bd,
                TareaNueva(
                    fecha=hoy - timedelta(days=dias),
                    texto=f"Hace {dias}",
                    tipo="grabar",
                ),
            )
        lista = tareas_atrasadas(bd, hoy)

    assert len(lista) == 200
    assert lista[-1].fecha == hoy - timedelta(days=1)
    assert [tarea.fecha for tarea in lista] == sorted(tarea.fecha for tarea in lista)


# M3: un id enorme es un 422, no un 500.
@pytest.mark.parametrize(
    ("metodo", "ruta", "cuerpo"),
    [
        ("put", f"/api/tareas/{2**70}/hecha", {"hecha": True}),
        ("delete", f"/api/tareas/{2**70}", {}),
    ],
)
def test_id_de_tarea_enorme_da_422(cliente_con_token, metodo, ruta, cuerpo):
    respuesta = cliente_con_token.request(metodo, ruta, headers=CABECERAS, json=cuerpo)

    assert respuesta.status_code == 422


# M5: hecha_en es la hora local, no la UTC.
def test_hecha_en_usa_la_hora_local(cfg, monkeypatch):
    class RelojFalso(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 17, 20, 30, 0)

        @classmethod
        def utcnow(cls):
            return datetime(2026, 11, 17, 19, 30, 0)

    monkeypatch.setattr(modulo_tareas, "datetime", RelojFalso)
    with closing(abrir_bd(cfg.bd_ruta)) as bd:
        tarea = crear_tarea(
            bd, TareaNueva(fecha=date(2026, 11, 17), texto="x", tipo="grabar")
        )
        hecha = marcar_hecha(bd, tarea.id, True)

    assert hecha is not None
    assert hecha.hecha_en == datetime(2026, 11, 17, 20, 30, 0)


# Auditoría I5: los nombres de una línea no admiten saltos ni controles.
@pytest.mark.parametrize("nombre", ["Dos\nlíneas", "Tab\tulado", "Ra\u2028ro"])
def test_nombres_de_tipo_y_curso_sin_saltos(nombre):
    with pytest.raises(ValidationError):
        TipoTarea(id="x", nombre=nombre, color="#299BC6", orden=1)
    with pytest.raises(ValidationError):
        CursoApp(id="x", nombre=nombre)


# Auditoría L1: cada curso se lee una sola vez por petición, por muchas lecciones enlazadas.
def test_listado_lee_cada_curso_una_vez(cliente, cfg, monkeypatch):
    for numero in (6, 7, 8):
        _guion_sin_carpeta(cfg, numero)
    with closing(abrir_bd(cfg.bd_ruta)) as bd:
        for numero in (4, 6, 7, 8):
            crear_tarea(
                bd,
                TareaNueva.model_validate(
                    _nueva(
                        enlace={"curso": "react", "numero": numero, "pieza": "leccion"}
                    )
                ),
            )

    llamadas = []
    original = modulo_vista.datos_curso

    def contar(config, curso):
        llamadas.append(curso)
        return original(config, curso)

    monkeypatch.setattr(modulo_vista, "datos_curso", contar)

    respuesta = cliente.get(
        "/api/tareas", params={"desde": "2026-11-17", "hasta": "2026-11-17"}
    )

    assert respuesta.status_code == 200
    assert llamadas == ["react"]


# Auditoría I2: al migrar desde v1 se guarda una copia de la base anterior.
def test_migrar_desde_v1_guarda_una_copia(tmp_path):
    ruta = tmp_path / "estudio.sqlite3"
    with closing(sqlite3.connect(ruta)) as bd:
        bd.execute(
            "CREATE TABLE portada_elegida (curso TEXT, numero INTEGER, pieza TEXT, ruta TEXT,"
            " PRIMARY KEY (curso, numero, pieza))"
        )
        bd.execute(
            "CREATE TABLE estado_red (curso TEXT, numero INTEGER, pieza TEXT, red TEXT,"
            " estado TEXT, fecha TEXT, url TEXT, PRIMARY KEY (curso, numero, pieza, red))"
        )
        bd.execute(
            "INSERT INTO portada_elegida VALUES ('react', 4, 'leccion', 'a.jpg')"
        )
        bd.execute("PRAGMA user_version = 1")
        bd.commit()

    with closing(abrir_bd(ruta)):
        pass

    copia = tmp_path / "estudio.sqlite3.v1"
    assert copia.is_file()
    with closing(sqlite3.connect(copia)) as bd:
        assert bd.execute("PRAGMA user_version").fetchone()[0] == 1
        assert bd.execute("SELECT ruta FROM portada_elegida").fetchall() == [("a.jpg",)]


def test_la_copia_v1_no_se_sustituye_por_una_base_ya_migrada(tmp_path):
    # Si otra apertura migró entretanto, la copia leída sería v2: no debe instalarse.
    from estudio_api.decisiones import _copia_antes_de_migrar

    ruta = tmp_path / "estudio.sqlite3"
    with closing(sqlite3.connect(ruta)) as bd:
        bd.execute("PRAGMA user_version = 2")
        bd.commit()
        _copia_antes_de_migrar(bd, ruta)

    assert not (tmp_path / "estudio.sqlite3.v1").exists()
    assert list(tmp_path.glob(".estudio.sqlite3.v1.*")) == []
