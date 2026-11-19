import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime

import pytest
from pydantic import ValidationError

from estudio_api.decisiones import (
    abrir_bd,
    elegir_portada,
    estados,
    fijar_estado,
    ganchos_grabados,
    marcar_gancho_grabado,
    portadas_elegidas,
)
from estudio_api.modelos import EstadoRed


def _crear_bd_v1(ruta):
    with closing(sqlite3.connect(ruta)) as bd:
        bd.executescript(
            """
            CREATE TABLE portada_elegida (
                curso TEXT NOT NULL,
                numero INTEGER NOT NULL,
                pieza TEXT NOT NULL,
                ruta TEXT NOT NULL,
                PRIMARY KEY (curso, numero, pieza)
            );
            CREATE TABLE estado_red (
                curso TEXT NOT NULL,
                numero INTEGER NOT NULL,
                pieza TEXT NOT NULL,
                red TEXT NOT NULL,
                estado TEXT NOT NULL,
                fecha TEXT,
                url TEXT,
                PRIMARY KEY (curso, numero, pieza, red)
            );
            INSERT INTO portada_elegida
                (curso, numero, pieza, ruta)
            VALUES ('curso-prueba', 2, 'leccion', 'portada.jpg');
            INSERT INTO estado_red
                (curso, numero, pieza, red, estado, fecha, url)
            VALUES (
                'curso-prueba', 2, 'leccion', 'youtube', 'publicado',
                '2026-11-17T12:00:00+01:00', 'https://youtu.be/abc'
            );
            PRAGMA user_version = 1;
            """
        )


def _crear_bd_v2(ruta):
    _crear_bd_v1(ruta)
    with closing(sqlite3.connect(ruta)) as bd:
        bd.executescript(
            """
            CREATE TABLE tipo_tarea (
                id TEXT PRIMARY KEY,
                nombre TEXT NOT NULL,
                color TEXT NOT NULL,
                orden INTEGER NOT NULL
            );
            CREATE TABLE curso_app (
                id TEXT PRIMARY KEY,
                nombre TEXT NOT NULL
            );
            CREATE TABLE tarea (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT NOT NULL,
                hora TEXT,
                texto TEXT NOT NULL,
                tipo TEXT NOT NULL REFERENCES tipo_tarea(id),
                curso TEXT,
                numero INTEGER,
                pieza TEXT,
                red TEXT,
                hecha INTEGER NOT NULL DEFAULT 0,
                hecha_en TEXT
            );
            CREATE INDEX idx_tarea_fecha ON tarea(fecha);
            INSERT INTO tipo_tarea VALUES ('grabar', 'Grabar', '#E5534B', 1);
            INSERT INTO tarea
                (fecha, texto, tipo, curso, numero)
            VALUES ('2026-11-17', 'Tarea ficticia', 'grabar', 'curso-prueba', 2);
            PRAGMA user_version = 2;
            """
        )


def _crear_bd_v3(ruta):
    _crear_bd_v2(ruta)
    with closing(sqlite3.connect(ruta)) as bd:
        bd.executescript(
            """
            CREATE TABLE trabajo (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                accion TEXT NOT NULL,
                curso TEXT,
                numero INTEGER,
                estado TEXT NOT NULL,
                progreso REAL NOT NULL DEFAULT 0,
                inicio TEXT NOT NULL,
                fin TEXT,
                error TEXT,
                registro TEXT NOT NULL DEFAULT '[]',
                temporal TEXT
            );
            INSERT INTO trabajo
                (accion, curso, numero, estado, progreso, inicio, registro)
            VALUES (
                'previa-grabacion', 'curso-prueba', 2, 'hecho', 1,
                '2026-11-18T12:00:00+01:00', '["fin"]'
            );
            PRAGMA user_version = 3;
            """
        )


def test_abrir_bd_migra_v3_conserva_trabajos_y_guarda_copia(tmp_path):
    ruta_bd = tmp_path / "estudio.sqlite3"
    _crear_bd_v3(ruta_bd)

    with closing(abrir_bd(ruta_bd)) as bd:
        assert bd.execute("PRAGMA user_version").fetchone()[0] == 6
        assert bd.execute(
            "SELECT accion, curso, numero, estado, objetivo FROM trabajo"
        ).fetchall() == [("previa-grabacion", "curso-prueba", 2, "hecho", None)]

    copia = ruta_bd.with_name(f"{ruta_bd.name}.v3")
    assert copia.is_file()
    with closing(sqlite3.connect(copia)) as bd:
        assert bd.execute("PRAGMA user_version").fetchone()[0] == 3
        assert [fila[1] for fila in bd.execute("PRAGMA table_info(trabajo)")] == [
            "id",
            "accion",
            "curso",
            "numero",
            "estado",
            "progreso",
            "inicio",
            "fin",
            "error",
            "registro",
            "temporal",
        ]


def test_fallo_al_migrar_v3_deja_la_base_intacta(tmp_path, monkeypatch):
    ruta_bd = tmp_path / "estudio.sqlite3"
    _crear_bd_v3(ruta_bd)
    conectar_real = sqlite3.connect

    class ConexionConFallo(sqlite3.Connection):
        def execute(self, sql, parameters=(), /):
            if "ALTER TABLE trabajo ADD COLUMN objetivo" in sql:
                raise sqlite3.OperationalError("fallo forzado al añadir objetivo")
            return super().execute(sql, parameters)

    def conectar_con_fallo(ruta):
        return conectar_real(ruta, factory=ConexionConFallo)

    monkeypatch.setattr("estudio_api.decisiones.sqlite3.connect", conectar_con_fallo)

    with pytest.raises(sqlite3.OperationalError, match="fallo forzado"):
        abrir_bd(ruta_bd)

    with closing(conectar_real(ruta_bd)) as bd:
        assert bd.execute("PRAGMA user_version").fetchone()[0] == 3
        assert "objetivo" not in [
            fila[1] for fila in bd.execute("PRAGMA table_info(trabajo)")
        ]
        assert bd.execute("SELECT accion FROM trabajo").fetchall() == [
            ("previa-grabacion",)
        ]


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
        fijar_estado(
            bd,
            "curso-prueba",
            2,
            "leccion",
            "youtube",
            EstadoRed(estado="publicado", url="https://youtu.be/abc"),
        )
        assert bd.execute("PRAGMA user_version").fetchone()[0] == 6
        tablas = {
            fila[0]
            for fila in bd.execute(
                "SELECT name FROM sqlite_master WHERE type = ?", ("table",)
            )
        }
        assert {"portada_elegida", "estado_red"} <= tablas

    with closing(abrir_bd(ruta_bd)) as bd:
        assert portadas_elegidas(bd, "curso-prueba", 2) == {"leccion": "portada.jpg"}
        assert estados(bd, "curso-prueba", 2)[("leccion", "youtube")].estado == (
            "publicado"
        )


def test_abrir_bd_vacia_crea_version_5_y_siembra_tipos_una_vez(tmp_path):
    ruta_bd = tmp_path / "estudio.sqlite3"

    with closing(abrir_bd(ruta_bd)) as bd:
        assert bd.execute("PRAGMA user_version").fetchone()[0] == 6
        assert bd.execute(
            "SELECT id, nombre, color, orden FROM tipo_tarea ORDER BY orden"
        ).fetchall() == [
            ("preparar", "Preparar", "#A371F7", 1),
            ("grabar", "Grabar", "#E5534B", 2),
            ("editar", "Editar", "#E8A33D", 3),
            ("publicar", "Publicar", "#4BC98C", 4),
            ("otro", "Otro", "#9B9BA4", 5),
        ]
        bd.execute("DELETE FROM tipo_tarea WHERE id = ?", ("otro",))
        bd.commit()

    with closing(abrir_bd(ruta_bd)) as bd:
        assert (
            bd.execute("SELECT id FROM tipo_tarea WHERE id = ?", ("otro",)).fetchone()
            is None
        )


def test_abrir_bd_migra_v1_y_conserva_sus_filas(tmp_path):
    ruta_bd = tmp_path / "estudio.sqlite3"
    _crear_bd_v1(ruta_bd)

    with closing(abrir_bd(ruta_bd)) as bd:
        assert bd.execute("PRAGMA user_version").fetchone()[0] == 6
        assert bd.execute("SELECT * FROM portada_elegida").fetchall() == [
            ("curso-prueba", 2, "leccion", "portada.jpg")
        ]
        assert bd.execute("SELECT * FROM estado_red").fetchall() == [
            (
                "curso-prueba",
                2,
                "leccion",
                "youtube",
                "publicado",
                "2026-11-17T12:00:00+01:00",
                "https://youtu.be/abc",
            )
        ]
        tablas = {
            fila[0]
            for fila in bd.execute(
                "SELECT name FROM sqlite_master WHERE type = ?", ("table",)
            )
        }
        assert {"tipo_tarea", "curso_app", "tarea"} <= tablas
        assert bd.execute("SELECT id FROM tipo_tarea ORDER BY orden").fetchall() == [
            ("preparar",),
            ("grabar",),
            ("editar",),
            ("publicar",),
            ("otro",),
        ]
        assert bd.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'trabajo'"
        ).fetchone() == ("trabajo",)


def test_abrir_bd_migra_v2_conserva_filas_y_guarda_copia(tmp_path):
    ruta_bd = tmp_path / "estudio.sqlite3"
    _crear_bd_v2(ruta_bd)

    with closing(abrir_bd(ruta_bd)) as bd:
        assert bd.execute("PRAGMA user_version").fetchone()[0] == 6
        assert bd.execute(
            "SELECT curso, numero, pieza, ruta FROM portada_elegida"
        ).fetchall() == [("curso-prueba", 2, "leccion", "portada.jpg")]
        assert bd.execute(
            "SELECT fecha, texto, tipo, curso, numero FROM tarea"
        ).fetchall() == [("2026-11-17", "Tarea ficticia", "grabar", "curso-prueba", 2)]
        columnas = bd.execute("PRAGMA table_info(trabajo)").fetchall()
        assert [columna[1] for columna in columnas] == [
            "id",
            "accion",
            "curso",
            "numero",
            "estado",
            "progreso",
            "inicio",
            "fin",
            "error",
            "registro",
            "temporal",
            "objetivo",
        ]

    copia = ruta_bd.with_name(f"{ruta_bd.name}.v2")
    assert copia.is_file()
    with closing(sqlite3.connect(copia)) as bd:
        assert bd.execute("PRAGMA user_version").fetchone()[0] == 2
        assert bd.execute("SELECT texto FROM tarea").fetchall() == [("Tarea ficticia",)]
        assert (
            bd.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'trabajo'"
            ).fetchone()
            is None
        )


def test_fallo_al_crear_trabajo_deja_la_base_en_v2(tmp_path, monkeypatch):
    ruta_bd = tmp_path / "estudio.sqlite3"
    _crear_bd_v2(ruta_bd)
    conectar_real = sqlite3.connect

    class ConexionConFallo(sqlite3.Connection):
        def execute(self, sql, parameters=(), /):
            if "CREATE TABLE trabajo" in sql:
                raise sqlite3.OperationalError("fallo forzado al crear trabajo")
            return super().execute(sql, parameters)

    def conectar_con_fallo(ruta):
        return conectar_real(ruta, factory=ConexionConFallo)

    monkeypatch.setattr("estudio_api.decisiones.sqlite3.connect", conectar_con_fallo)

    with pytest.raises(sqlite3.OperationalError, match="fallo forzado"):
        abrir_bd(ruta_bd)

    with closing(conectar_real(ruta_bd)) as bd:
        assert bd.execute("PRAGMA user_version").fetchone()[0] == 2
        assert bd.execute("SELECT texto FROM tarea").fetchall() == [("Tarea ficticia",)]
        assert (
            bd.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'trabajo'"
            ).fetchone()
            is None
        )


def test_dos_aperturas_simultaneas_migran_v1_una_sola_vez(tmp_path, monkeypatch):
    ruta_bd = tmp_path / "estudio.sqlite3"
    _crear_bd_v1(ruta_bd)
    conectar_real = sqlite3.connect
    barrera = threading.Barrier(2)

    class ConexionSincronizada(sqlite3.Connection):
        primera_lectura_hecha = False

        def execute(self, sql, parameters=(), /):
            cursor = super().execute(sql, parameters)
            if sql.strip() == "PRAGMA user_version" and not self.primera_lectura_hecha:
                self.primera_lectura_hecha = True
                barrera.wait(timeout=5)
            return cursor

    def conectar_sincronizado(ruta):
        return conectar_real(ruta, factory=ConexionSincronizada, timeout=5)

    monkeypatch.setattr("estudio_api.decisiones.sqlite3.connect", conectar_sincronizado)

    def abrir_y_cerrar():
        with closing(abrir_bd(ruta_bd)) as bd:
            return bd.execute("PRAGMA user_version").fetchone()[0]

    with ThreadPoolExecutor(max_workers=2) as ejecutor:
        versiones = list(ejecutor.map(lambda _: abrir_y_cerrar(), range(2)))

    assert versiones == [6, 6]
    with closing(conectar_real(ruta_bd)) as bd:
        assert bd.execute("PRAGMA user_version").fetchone()[0] == 6
        assert bd.execute("SELECT COUNT(*) FROM tipo_tarea").fetchone()[0] == 5


def test_abrir_bd_restaura_el_aislamiento_para_revertir_bloques(tmp_path):
    with closing(abrir_bd(tmp_path / "estudio.sqlite3")) as bd:
        aislamiento_original = bd.isolation_level

        with pytest.raises(RuntimeError, match="fallo de prueba"), bd:
            bd.execute(
                "INSERT INTO portada_elegida VALUES (?, ?, ?, ?)",
                ("curso-prueba", 1, "leccion", "primera.jpg"),
            )
            bd.execute(
                "INSERT INTO portada_elegida VALUES (?, ?, ?, ?)",
                ("curso-prueba", 2, "leccion", "segunda.jpg"),
            )
            raise RuntimeError("fallo de prueba")

        assert bd.isolation_level == aislamiento_original
        assert bd.execute("SELECT COUNT(*) FROM portada_elegida").fetchone()[0] == 0


def test_fallo_de_migracion_revierte_ddl_siembra_y_version(tmp_path, monkeypatch):
    ruta_bd = tmp_path / "estudio.sqlite3"
    _crear_bd_v1(ruta_bd)
    conectar_real = sqlite3.connect

    class ConexionConFallo(sqlite3.Connection):
        def execute(self, sql, parameters=(), /):
            if "INSERT INTO tipo_tarea" in sql:
                raise sqlite3.OperationalError("fallo forzado durante la siembra")
            return super().execute(sql, parameters)

    def conectar_con_fallo(ruta):
        return conectar_real(ruta, factory=ConexionConFallo)

    monkeypatch.setattr("estudio_api.decisiones.sqlite3.connect", conectar_con_fallo)

    with pytest.raises(sqlite3.OperationalError, match="fallo forzado"):
        abrir_bd(ruta_bd)

    with closing(conectar_real(ruta_bd)) as bd:
        assert bd.execute("PRAGMA user_version").fetchone()[0] == 1
        assert bd.execute("SELECT * FROM portada_elegida").fetchall() == [
            ("curso-prueba", 2, "leccion", "portada.jpg")
        ]
        assert bd.execute("SELECT COUNT(*) FROM estado_red").fetchone()[0] == 1
        tablas = {
            fila[0]
            for fila in bd.execute(
                "SELECT name FROM sqlite_master WHERE type = ?", ("table",)
            )
        }
        assert tablas == {"portada_elegida", "estado_red"}


def test_abrir_bd_rechaza_version_7(tmp_path):
    ruta_bd = tmp_path / "estudio.sqlite3"
    with closing(sqlite3.connect(ruta_bd)) as bd:
        bd.execute("PRAGMA user_version = 7")

    with pytest.raises(
        RuntimeError, match="Versión de la base de datos no soportada: 7"
    ):
        abrir_bd(ruta_bd)


def test_abrir_bd_rechaza_version_no_soportada_y_la_conserva(tmp_path):
    ruta_bd = tmp_path / "estudio.sqlite3"
    with closing(sqlite3.connect(ruta_bd)) as bd:
        bd.execute("PRAGMA user_version = 8")

    with pytest.raises(
        RuntimeError, match="Versión de la base de datos no soportada: 8"
    ):
        abrir_bd(ruta_bd)

    with closing(sqlite3.connect(ruta_bd)) as bd:
        assert bd.execute("PRAGMA user_version").fetchone()[0] == 8


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


def test_abrir_bd_migra_v4_crea_ganchos_grabados_y_guarda_copia(tmp_path):
    ruta_bd = tmp_path / "estudio.sqlite3"
    _crear_bd_v3(ruta_bd)
    with closing(sqlite3.connect(ruta_bd)) as bd:
        bd.executescript(
            "ALTER TABLE trabajo ADD COLUMN objetivo TEXT; PRAGMA user_version = 4;"
        )

    with closing(abrir_bd(ruta_bd)) as bd:
        assert bd.execute("PRAGMA user_version").fetchone()[0] == 6
        assert bd.execute("SELECT accion FROM trabajo").fetchall() == [
            ("previa-grabacion",)
        ]
        marcar_gancho_grabado(bd, "react", 5, "S1", True, "2026-11-19T16:00:00+01:00")
        marcar_gancho_grabado(bd, "react", 5, "S1", True, "2026-11-19T17:00:00+01:00")
        marcar_gancho_grabado(bd, "react", 6, "S2", True, "2026-11-19T16:00:00+01:00")
        marcar_gancho_grabado(bd, "otro", 5, "S3", True, "2026-11-19T16:00:00+01:00")
        assert ganchos_grabados(bd, "react") == {(5, "S1"), (6, "S2")}
        marcar_gancho_grabado(bd, "react", 5, "S1", False, "2026-11-19T18:00:00+01:00")
        assert ganchos_grabados(bd, "react") == {(6, "S2")}

    copia = ruta_bd.with_name(f"{ruta_bd.name}.v4")
    with closing(sqlite3.connect(copia)) as bd:
        assert bd.execute("PRAGMA user_version").fetchone()[0] == 4


def test_abrir_bd_migra_v5_permite_tareas_sin_fecha_y_guarda_copia(tmp_path):
    ruta_bd = tmp_path / "estudio.sqlite3"
    _crear_bd_v3(ruta_bd)
    # La v5 real: la v3 más objetivo, ganchos grabados y una tarea con fecha.
    with closing(sqlite3.connect(ruta_bd)) as bd:
        bd.executescript(
            """
            ALTER TABLE trabajo ADD COLUMN objetivo TEXT;
            CREATE TABLE gancho_grabado (
                curso TEXT NOT NULL,
                numero INTEGER NOT NULL,
                gancho TEXT NOT NULL,
                fecha TEXT NOT NULL,
                PRIMARY KEY (curso, numero, gancho)
            );
            INSERT INTO tarea (fecha, texto, tipo, curso, numero)
            VALUES ('2026-11-17', 'Grabar la voz', 'grabar', 'react', 7);
            PRAGMA user_version = 5;
            """
        )
        assert bd.execute(
            "SELECT \"notnull\" FROM pragma_table_info('tarea') WHERE name = 'fecha'"
        ).fetchone() == (1,)

    with closing(abrir_bd(ruta_bd)) as bd:
        assert bd.execute("PRAGMA user_version").fetchone()[0] == 6
        assert bd.execute(
            "SELECT \"notnull\" FROM pragma_table_info('tarea') WHERE name = 'fecha'"
        ).fetchone() == (0,)
        assert bd.execute(
            "SELECT id, fecha, texto, tipo, curso, numero FROM tarea"
        ).fetchall() == [
            (1, "2026-11-17", "Tarea ficticia", "grabar", "curso-prueba", 2),
            (2, "2026-11-17", "Grabar la voz", "grabar", "react", 7),
        ]
        bd.execute("INSERT INTO tarea (texto, tipo) VALUES ('Sin día', 'grabar')")
        assert bd.execute(
            "SELECT id, fecha FROM tarea WHERE texto = 'Sin día'"
        ).fetchone() == (3, None)
        indices = {fila[1] for fila in bd.execute("PRAGMA index_list('tarea')")}
        assert "idx_tarea_fecha" in indices

    copia = ruta_bd.with_name(f"{ruta_bd.name}.v5")
    with closing(sqlite3.connect(copia)) as bd:
        assert bd.execute("PRAGMA user_version").fetchone()[0] == 5
