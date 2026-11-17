from contextlib import closing
from datetime import date, datetime

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
