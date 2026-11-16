from contextlib import closing
from datetime import datetime

import pytest
from pydantic import ValidationError

from estudio_api.decisiones import (
    abrir_bd,
    elegir_portada,
    estados,
    fijar_estado,
    portadas_elegidas,
)
from estudio_api.modelos import EstadoRed


def test_elegir_portada_sustituye_la_anterior(tmp_path):
    with closing(abrir_bd(tmp_path / "datos" / "estudio.sqlite3")) as bd:
        elegir_portada(bd, "curso-prueba", 2, "leccion", "portada-a.jpg")
        elegir_portada(bd, "curso-prueba", 2, "leccion", "portada-b.jpg")

        assert portadas_elegidas(bd, "curso-prueba", 2) == {"leccion": "portada-b.jpg"}


def test_programado_publicado_y_pendiente_borra_la_fila(tmp_path):
    ruta_bd = tmp_path / "estudio.sqlite3"
    fecha_programada = datetime.fromisoformat("2026-11-18T20:00:00+01:00")

    with closing(abrir_bd(ruta_bd)) as bd:
        fijar_estado(
            bd,
            "curso-prueba",
            2,
            "leccion",
            "youtube",
            EstadoRed(estado="programado", fecha=fecha_programada),
        )
        assert estados(bd, "curso-prueba", 2)[("leccion", "youtube")].estado == (
            "programado"
        )

        fijar_estado(
            bd,
            "curso-prueba",
            2,
            "leccion",
            "youtube",
            EstadoRed(estado="publicado", url="https://youtu.be/abc"),
        )
        publicado = estados(bd, "curso-prueba", 2)[("leccion", "youtube")]
        assert publicado.estado == "publicado"
        assert publicado.fecha is not None
        assert publicado.fecha.tzinfo is not None

        fijar_estado(
            bd,
            "curso-prueba",
            2,
            "leccion",
            "youtube",
            EstadoRed(estado="pendiente"),
        )
        assert estados(bd, "curso-prueba", 2) == {}


def test_programado_sin_fecha_no_valida():
    with pytest.raises(ValidationError):
        EstadoRed(estado="programado")


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "http://youtube.com/x",
        "https://evil.example/x",
    ],
)
def test_url_publicada_no_permitida_no_valida(url):
    with pytest.raises(ValidationError):
        EstadoRed(estado="publicado", url=url)


def test_url_publicada_permitida_valida():
    estado = EstadoRed(estado="publicado", url="https://youtu.be/abc")

    assert estado.url == "https://youtu.be/abc"


@pytest.mark.parametrize(
    ("fecha", "url"),
    [
        (datetime.fromisoformat("2026-11-18T20:00:00+01:00"), None),
        (None, "https://youtu.be/abc"),
    ],
)
def test_pendiente_no_admite_fecha_ni_url(fecha, url):
    with pytest.raises(ValidationError):
        EstadoRed(estado="pendiente", fecha=fecha, url=url)


def test_fecha_sin_zona_se_interpreta_como_hora_local_y_se_persiste_con_zona(
    tmp_path,
):
    fecha_local_sin_zona = datetime(2026, 11, 18, 20, 0)
    esperada = fecha_local_sin_zona.astimezone()

    with closing(abrir_bd(tmp_path / "estudio.sqlite3")) as bd:
        fijar_estado(
            bd,
            "curso-prueba",
            2,
            "leccion",
            "youtube",
            EstadoRed(estado="programado", fecha=fecha_local_sin_zona),
        )

        guardada = estados(bd, "curso-prueba", 2)[("leccion", "youtube")].fecha
        assert guardada == esperada
        assert guardada is not None
        assert guardada.tzinfo is not None

        fecha_sql = bd.execute(
            "SELECT fecha FROM estado_red WHERE curso = ? AND numero = ?",
            ("curso-prueba", 2),
        ).fetchone()[0]
        assert fecha_sql == esperada.isoformat()


def test_abrir_dos_veces_conserva_datos_y_esquema(tmp_path):
    ruta_bd = tmp_path / "datos" / "estudio.sqlite3"
    with closing(abrir_bd(ruta_bd)) as bd:
        elegir_portada(bd, "curso-prueba", 2, "leccion", "portada.jpg")
        assert bd.execute("PRAGMA user_version").fetchone()[0] == 1
        tablas = {
            fila[0]
            for fila in bd.execute(
                "SELECT name FROM sqlite_master WHERE type = ?", ("table",)
            )
        }
        assert {"portada_elegida", "estado_red"} <= tablas

    with closing(abrir_bd(ruta_bd)) as bd:
        assert portadas_elegidas(bd, "curso-prueba", 2) == {"leccion": "portada.jpg"}


def test_pieza_con_comillas_se_guarda_literalmente(tmp_path):
    pieza = "short-'especial\""
    with closing(abrir_bd(tmp_path / "estudio.sqlite3")) as bd:
        elegir_portada(bd, "curso-prueba", 2, pieza, "portada.jpg")
        fijar_estado(
            bd,
            "curso-prueba",
            2,
            pieza,
            "youtube",
            EstadoRed(estado="publicado"),
        )

        assert portadas_elegidas(bd, "curso-prueba", 2)[pieza] == "portada.jpg"
        assert estados(bd, "curso-prueba", 2)[(pieza, "youtube")].estado == (
            "publicado"
        )
