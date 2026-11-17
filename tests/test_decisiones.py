import sqlite3
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
        " https://youtu.be/a",
        "https://youtu.be/a ",
        "https://youtu.be/a b",
        "https://you\ntube.com/x",
        "https://youtube.com/\x00",
        "https://youtube.com/\x7f",
        "https://youtube.com:",
        "https://youtube.com.evil.example",
        "https://evil.example" + chr(64) + "youtube.com",
        "https://youtube.com:444",
        "https:///youtube.com",
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


def test_url_publicada_admite_mayusculas_en_esquema_y_host():
    estado = EstadoRed(estado="publicado", url="HTTPS://YouTube.COM/x")

    assert estado.url == "HTTPS://YouTube.COM/x"


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


def test_abrir_bd_rechaza_version_no_soportada_y_la_conserva(tmp_path):
    ruta_bd = tmp_path / "estudio.sqlite3"
    with closing(sqlite3.connect(ruta_bd)) as bd:
        bd.execute("PRAGMA user_version = 7")

    with pytest.raises(
        RuntimeError, match="Versión de la base de datos no soportada: 7"
    ):
        abrir_bd(ruta_bd)

    with closing(sqlite3.connect(ruta_bd)) as bd:
        assert bd.execute("PRAGMA user_version").fetchone()[0] == 7


def test_abrir_bd_no_repite_ddl_si_el_esquema_ya_esta_creado(tmp_path, monkeypatch):
    sentencias = []

    class ConexionRegistrada(sqlite3.Connection):
        def execute(self, sql, parameters=(), /):
            sentencias.append(sql)
            return super().execute(sql, parameters)

    conectar_real = sqlite3.connect

    def conectar_registrando(ruta):
        return conectar_real(ruta, factory=ConexionRegistrada)

    monkeypatch.setattr("estudio_api.decisiones.sqlite3.connect", conectar_registrando)
    ruta_bd = tmp_path / "estudio.sqlite3"

    with closing(abrir_bd(ruta_bd)):
        pass
    sentencias.clear()
    with closing(abrir_bd(ruta_bd)):
        pass

    assert not any("CREATE TABLE" in sentencia for sentencia in sentencias)
    assert not any("PRAGMA user_version =" in sentencia for sentencia in sentencias)


def test_estados_omite_fila_inconsistente_y_registra_aviso(tmp_path, caplog):
    with closing(abrir_bd(tmp_path / "estudio.sqlite3")) as bd:
        bd.execute(
            """
            INSERT INTO estado_red
                (curso, numero, pieza, red, estado, fecha, url)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "curso-prueba",
                2,
                "leccion",
                "youtube",
                "publicado",
                "2026-11-17T12:00:00+01:00",
                "https://evil.example/x",
            ),
        )
        fijar_estado(
            bd,
            "curso-prueba",
            2,
            "short-1",
            "youtube",
            EstadoRed(estado="publicado"),
        )

        resultado = estados(bd, "curso-prueba", 2)

    assert set(resultado) == {("short-1", "youtube")}
    assert "Fila de estado de red inconsistente omitida" in caplog.text


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
