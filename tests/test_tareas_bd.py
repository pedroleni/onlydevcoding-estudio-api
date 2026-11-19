import sqlite3
from contextlib import closing
from datetime import date, datetime
from threading import Event, Thread

import pytest
from pydantic import ValidationError

from estudio_api.decisiones import abrir_bd
from estudio_api.tareas import (
    CursoApp,
    EnlaceTarea,
    TareaNueva,
    TipoTarea,
    borrar_curso_app,
    borrar_tarea,
    borrar_tipo,
    completar_tareas_de_red,
    crear_curso_app,
    crear_tarea,
    crear_tipo,
    cursos_app,
    editar_tarea,
    editar_tipo,
    marcar_hecha,
    tareas_atrasadas,
    tareas_entre,
    tareas_sin_fecha,
    tipos,
)


def _nueva(
    fecha: str = "2026-11-17",
    texto: str = "Preparar la lección",
    tipo: str = "preparar",
    enlace: EnlaceTarea | None = None,
) -> TareaNueva:
    return TareaNueva(fecha=fecha, texto=texto, tipo=tipo, enlace=enlace)


def test_validacion_de_fecha_hora_texto_y_campos_extra():
    with pytest.raises(ValidationError):
        _nueva(fecha="2026-02-29")
    assert _nueva(fecha="2028-02-29").fecha == date(2028, 2, 29)
    for fecha in (0, datetime(2026, 11, 17)):
        with pytest.raises(ValidationError):
            TareaNueva.model_validate(
                {"fecha": fecha, "texto": "Texto", "tipo": "preparar"}
            )

    with pytest.raises(ValidationError):
        TareaNueva(
            fecha="2026-11-17",
            hora="24:00",
            texto="Texto",
            tipo="preparar",
        )
    with pytest.raises(ValidationError):
        TareaNueva(
            fecha="2026-11-17",
            hora="١٢:٣٠",
            texto="Texto",
            tipo="preparar",
        )
    for texto in ("", "   ", "una línea\ny otra", "x" * 301):
        with pytest.raises(ValidationError):
            _nueva(texto=texto)
    with pytest.raises(ValidationError):
        TareaNueva.model_validate(
            {
                "fecha": "2026-11-17",
                "texto": "Texto",
                "tipo": "preparar",
                "inesperado": True,
            }
        )


@pytest.mark.parametrize("separador", ["\v", "\x85", "\u2028", "\t", "\x00"])
def test_texto_rechaza_saltos_unicode_y_caracteres_de_control(separador):
    with pytest.raises(ValidationError):
        _nueva(texto=f"Primera parte{separador}segunda parte")


def test_validacion_jerarquica_y_patrones_del_enlace():
    with pytest.raises(ValidationError):
        EnlaceTarea.model_validate({"numero": 4, "pieza": "reel-salida"})
    with pytest.raises(ValidationError):
        EnlaceTarea(curso="react", pieza="reel-salida")
    with pytest.raises(ValidationError):
        EnlaceTarea(curso="react", numero=4, red="instagram")
    with pytest.raises(ValidationError):
        EnlaceTarea(curso="réact")
    with pytest.raises(ValidationError):
        EnlaceTarea(curso="react", numero=4, pieza="short-٠")

    enlace = EnlaceTarea(
        curso="react", numero=4, pieza="reel-salida-2", red="instagram"
    )
    assert enlace.red == "instagram"


def test_crear_editar_y_borrar_tarea_conserva_texto_literal(tmp_path):
    texto = "  Grabar «gancho» 🎬 <b>x</b>  "
    with closing(abrir_bd(tmp_path / "estudio.sqlite3")) as bd:
        creada = crear_tarea(bd, _nueva(texto=texto))
        assert creada.id > 0
        assert creada.texto == "Grabar «gancho» 🎬 <b>x</b>"
        assert creada.hecha is False
        assert creada.hecha_en is None

        editada = editar_tarea(
            bd,
            creada.id,
            TareaNueva(
                fecha="2026-11-18",
                hora="09:30",
                texto="Texto editado",
                tipo="editar",
                enlace=EnlaceTarea(curso="react", numero=4),
            ),
        )
        assert editada is not None
        assert editada.fecha == date(2026, 11, 18)
        assert editada.enlace == EnlaceTarea(curso="react", numero=4)
        assert editar_tarea(bd, 999, _nueva()) is None
        assert borrar_tarea(bd, creada.id) is True
        assert borrar_tarea(bd, creada.id) is False


def test_rangos_cruzan_el_ano_y_atrasadas_solo_incluye_pendientes(tmp_path):
    with closing(abrir_bd(tmp_path / "estudio.sqlite3")) as bd:
        fuera = crear_tarea(bd, _nueva(fecha="2025-12-28", texto="Fuera"))
        lunes = crear_tarea(bd, _nueva(fecha="2025-12-29", texto="Lunes"))
        domingo = crear_tarea(bd, _nueva(fecha="2026-01-04", texto="Domingo"))
        hoy = crear_tarea(bd, _nueva(fecha="2026-01-05", texto="Hoy"))
        hecha = crear_tarea(bd, _nueva(fecha="2026-01-03", texto="Hecha"))
        marcar_hecha(bd, hecha.id, True)

        semana = tareas_entre(bd, date(2025, 12, 29), date(2026, 1, 4))
        assert [tarea.id for tarea in semana] == [lunes.id, hecha.id, domingo.id]

        atrasadas = tareas_atrasadas(bd, date(2026, 1, 5))
        assert [tarea.id for tarea in atrasadas] == [
            fuera.id,
            lunes.id,
            domingo.id,
        ]
        assert hoy.id not in {tarea.id for tarea in atrasadas}


def test_marcar_hecha_rellena_fecha_local_sin_zona_y_desmarcar_la_vacia(tmp_path):
    with closing(abrir_bd(tmp_path / "estudio.sqlite3")) as bd:
        tarea = crear_tarea(bd, _nueva())

        hecha = marcar_hecha(bd, tarea.id, True)
        assert hecha is not None
        assert hecha.hecha is True
        assert hecha.hecha_en is not None
        assert hecha.hecha_en.tzinfo is None
        assert hecha.hecha_en.microsecond == 0
        guardada = bd.execute(
            "SELECT hecha_en FROM tarea WHERE id = ?", (tarea.id,)
        ).fetchone()[0]
        assert guardada == hecha.hecha_en.isoformat(timespec="seconds")

        pendiente = marcar_hecha(bd, tarea.id, False)
        assert pendiente is not None
        assert pendiente.hecha is False
        assert pendiente.hecha_en is None
        assert marcar_hecha(bd, 999, True) is None


def test_completar_tareas_de_red_solo_marca_la_coincidencia_exacta(tmp_path):
    instagram = EnlaceTarea(
        curso="react", numero=4, pieza="reel-salida", red="instagram"
    )
    tiktok = EnlaceTarea(curso="react", numero=4, pieza="reel-salida", red="tiktok")
    with closing(abrir_bd(tmp_path / "estudio.sqlite3")) as bd:
        primera = crear_tarea(bd, _nueva(texto="Uno", enlace=instagram))
        segunda = crear_tarea(bd, _nueva(texto="Dos", enlace=instagram))
        tercera = crear_tarea(bd, _nueva(texto="Tres", enlace=tiktok))

        assert completar_tareas_de_red(bd, "react", 4, "reel-salida", "instagram") == 2
        assert completar_tareas_de_red(bd, "react", 4, "reel-salida", "instagram") == 0

        por_id = {
            tarea.id: tarea
            for tarea in tareas_entre(bd, date(2026, 11, 17), date(2026, 11, 17))
        }
        assert por_id[primera.id].hecha is True
        assert por_id[segunda.id].hecha is True
        assert por_id[tercera.id].hecha is False


def test_tipos_se_ordenan_y_no_se_borran_si_tienen_tareas(tmp_path):
    with closing(abrir_bd(tmp_path / "estudio.sqlite3")) as bd:
        assert [tipo.id for tipo in tipos(bd)] == [
            "preparar",
            "grabar",
            "editar",
            "publicar",
            "otro",
        ]
        personalizada = crear_tipo(
            bd,
            TipoTarea(id="revisar", nombre="Revisar", color="#6CCBEF", orden=0),
        )
        assert personalizada.id == "revisar"
        editada = editar_tipo(
            bd,
            "revisar",
            TipoTarea(id="revisar", nombre="Revisión", color="#F778BA", orden=6),
        )
        assert editada is not None
        assert editada.nombre == "Revisión"
        assert (
            editar_tipo(
                bd,
                "no-existe",
                TipoTarea(id="no-existe", nombre="Nada", color="#F778BA", orden=6),
            )
            is None
        )

        tarea = crear_tarea(bd, _nueva(tipo="grabar"))
        assert borrar_tipo(bd, "grabar") == "en_uso"
        assert borrar_tarea(bd, tarea.id) is True
        assert borrar_tipo(bd, "grabar") == "borrado"
        assert borrar_tipo(bd, "grabar") == "no_existe"


def test_cursos_app_no_se_borran_si_tienen_tareas(tmp_path):
    with closing(abrir_bd(tmp_path / "estudio.sqlite3")) as bd:
        curso = crear_curso_app(bd, CursoApp(id="python", nombre="Python"))
        assert curso == CursoApp(id="python", nombre="Python")
        assert cursos_app(bd) == [curso]

        tarea = crear_tarea(
            bd, _nueva(enlace=EnlaceTarea(curso="python"), texto="Preparar Python")
        )
        assert borrar_curso_app(bd, "python") == "en_uso"
        assert borrar_tarea(bd, tarea.id) is True
        assert borrar_curso_app(bd, "python") == "borrado"
        assert borrar_curso_app(bd, "python") == "no_existe"


@pytest.mark.parametrize(
    ("objetivo", "consulta_dependencia"),
    [
        ("tipo", "SELECT 1 FROM tarea WHERE tipo"),
        ("curso", "SELECT 1 FROM tarea WHERE curso"),
    ],
)
def test_comprobar_y_borrar_es_atomico_frente_a_otra_escritura(
    tmp_path, objetivo, consulta_dependencia
):
    ruta_bd = tmp_path / "estudio.sqlite3"
    with closing(abrir_bd(ruta_bd)) as bd:
        crear_curso_app(bd, CursoApp(id="python", nombre="Python"))

    consulta_alcanzada = Event()
    escritor_terminado = Event()
    error_borrado = []
    error_escritura = []
    resultado = []

    class ConexionPausada(sqlite3.Connection):
        def execute(self, sql, parameters=(), /):
            cursor = super().execute(sql, parameters)
            if consulta_dependencia in " ".join(sql.split()):
                consulta_alcanzada.set()
                assert escritor_terminado.wait(timeout=5)
            return cursor

    def borrar():
        try:
            with closing(
                sqlite3.connect(ruta_bd, factory=ConexionPausada, timeout=1)
            ) as bd:
                bd.execute("PRAGMA foreign_keys = ON")
                funcion = borrar_tipo if objetivo == "tipo" else borrar_curso_app
                identificador = "preparar" if objetivo == "tipo" else "python"
                resultado.append(funcion(bd, identificador))
        except Exception as error:  # noqa: BLE001 - el hilo devuelve el fallo al test.
            error_borrado.append(error)

    def escribir():
        assert consulta_alcanzada.wait(timeout=5)
        try:
            with closing(sqlite3.connect(ruta_bd, timeout=0.2)) as bd:
                bd.execute("PRAGMA foreign_keys = ON")
                bd.execute(
                    """
                    INSERT INTO tarea (fecha, texto, tipo, curso)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        "2026-11-17",
                        "Escritura concurrente ficticia",
                        "preparar",
                        "python" if objetivo == "curso" else None,
                    ),
                )
                bd.commit()
        except sqlite3.Error as error:
            error_escritura.append(error)
        finally:
            escritor_terminado.set()

    hilo_borrado = Thread(target=borrar)
    hilo_escritura = Thread(target=escribir)
    hilo_borrado.start()
    hilo_escritura.start()
    hilo_borrado.join(timeout=5)
    hilo_escritura.join(timeout=5)

    assert not hilo_borrado.is_alive()
    assert not hilo_escritura.is_alive()
    assert not error_borrado
    assert resultado in (["borrado"], ["en_uso"])
    with closing(sqlite3.connect(ruta_bd)) as bd:
        tareas = bd.execute("SELECT COUNT(*) FROM tarea").fetchone()[0]
        tareas_huerfanas = bd.execute("PRAGMA foreign_key_check").fetchall()
        tabla = "tipo_tarea" if objetivo == "tipo" else "curso_app"
        identificador = "preparar" if objetivo == "tipo" else "python"
        existe = bd.execute(
            f"SELECT 1 FROM {tabla} WHERE id = ?", (identificador,)
        ).fetchone()

    if resultado == ["borrado"]:
        assert tareas == 0
        assert existe is None
    else:
        assert tareas == 1
        assert existe is not None
    assert not any(
        isinstance(error, sqlite3.IntegrityError)
        for error in [*error_borrado, *error_escritura]
    )
    assert tareas_huerfanas == []


def test_tareas_sin_fecha_no_salen_en_los_dias_y_se_ordenan_por_leccion(tmp_path):
    with closing(abrir_bd(tmp_path / "estudio.sqlite3")) as bd:
        sin_curso = crear_tarea(
            bd, TareaNueva(fecha=None, texto="Comprar micro", tipo="otro")
        )
        l8 = crear_tarea(
            bd,
            TareaNueva(
                texto="Grabar la voz",
                tipo="grabar",
                enlace=EnlaceTarea(curso="react", numero=8),
            ),
        )
        l7 = crear_tarea(
            bd,
            TareaNueva(
                fecha=None,
                texto="Grabar la voz",
                tipo="grabar",
                enlace=EnlaceTarea(curso="react", numero=7),
            ),
        )
        con_dia = crear_tarea(bd, _nueva(fecha="2026-11-17"))

        assert sin_curso.fecha is None
        assert [t.id for t in tareas_sin_fecha(bd)] == [l7.id, l8.id, sin_curso.id]
        assert [t.id for t in tareas_entre(bd, date(2000, 1, 1), date(2100, 1, 1))] == [
            con_dia.id
        ]
        assert tareas_atrasadas(bd, date(2100, 1, 1)) == [con_dia]

        # Asignarle día la saca de la lista; quitárselo la devuelve.
        con_fecha = editar_tarea(
            bd, l8.id, l8.model_copy(update={"fecha": date(2026, 11, 20)})
        )
        assert con_fecha is not None and con_fecha.fecha == date(2026, 11, 20)
        assert [t.id for t in tareas_sin_fecha(bd)] == [l7.id, sin_curso.id]
        editar_tarea(
            bd,
            l8.id,
            TareaNueva(**l8.model_dump(include={"hora", "texto", "tipo", "enlace"})),
        )
        assert [t.id for t in tareas_sin_fecha(bd)] == [l7.id, l8.id, sin_curso.id]

        # Las hechas siguen en la lista total.
        marcar_hecha(bd, l7.id, True)
        assert [t.hecha for t in tareas_sin_fecha(bd)] == [True, False, False]
