import json
import sys
from contextlib import closing
from datetime import datetime

import pytest

from estudio_api.app import crear_app
from estudio_api.decisiones import abrir_bd
from estudio_api.trabajos import (
    TrabajoEnMarcha,
    esperar,
    interrumpir_huerfanos,
    lanzar,
    leer_trabajo,
    ultimo_trabajo,
)


def _leer(ruta_bd, trabajo_id):
    with closing(abrir_bd(ruta_bd)) as bd:
        trabajo = leer_trabajo(bd, trabajo_id)
    assert trabajo is not None
    return trabajo


def test_trabajo_termina_bien_y_mueve_el_temporal(tmp_path):
    ruta_bd = tmp_path / "estudio.sqlite3"
    temporal = tmp_path / "salida.generando"
    destino = tmp_path / "salida.mp4"
    comando = [
        sys.executable,
        "-c",
        (
            "import sys,time; "
            "[print(f'{i}/4', flush=True) or time.sleep(0.05) "
            "for i in range(1,5)]; "
            "open(sys.argv[1],'w').write('x')"
        ),
        str(temporal),
    ]

    trabajo = lanzar(
        ruta_bd,
        "previa-grabacion",
        "curso-prueba",
        2,
        comando,
        tmp_path,
        temporal,
        destino,
    )
    esperar(trabajo.id, 5)

    terminado = _leer(ruta_bd, trabajo.id)
    assert terminado.estado == "hecho"
    assert terminado.progreso == 1.0
    assert terminado.inicio.tzinfo is not None
    assert terminado.fin is not None
    assert terminado.fin.tzinfo is not None
    assert destino.read_text(encoding="utf-8") == "x"
    assert not temporal.exists()
    assert "temporal" not in terminado.model_dump()
    with closing(abrir_bd(ruta_bd)) as bd:
        assert ultimo_trabajo(bd, "previa-grabacion", "curso-prueba", 2) == terminado


def test_trabajo_termina_mal_y_borra_el_temporal(tmp_path):
    ruta_bd = tmp_path / "estudio.sqlite3"
    temporal = tmp_path / "salida.generando"
    temporal.write_text("incompleta", encoding="utf-8")

    trabajo = lanzar(
        ruta_bd,
        "previa-grabacion",
        "curso-prueba",
        2,
        [sys.executable, "-c", "raise SystemExit(3)"],
        tmp_path,
        temporal,
        tmp_path / "salida.mp4",
    )
    esperar(trabajo.id, 5)

    terminado = _leer(ruta_bd, trabajo.id)
    assert terminado.estado == "error"
    assert terminado.error == "Remotion terminó con el código 3"
    assert terminado.fin is not None
    assert not temporal.exists()


def test_solo_admite_un_trabajo_en_marcha(tmp_path):
    ruta_bd = tmp_path / "estudio.sqlite3"
    primero = lanzar(
        ruta_bd,
        "lento",
        None,
        None,
        [sys.executable, "-c", "import time; time.sleep(0.5)"],
        tmp_path,
        None,
        None,
    )

    with pytest.raises(TrabajoEnMarcha):
        lanzar(
            ruta_bd,
            "segundo",
            None,
            None,
            [sys.executable, "-c", "pass"],
            tmp_path,
            None,
            None,
        )

    esperar(primero.id, 5)


def test_registro_conserva_40_lineas_y_recorta_cada_una(tmp_path):
    ruta_bd = tmp_path / "estudio.sqlite3"
    programa = (
        "for i in range(60): print(f'linea-{i}'); "
        "print('x' * 2000); "
        "[print(f'linea-{i}') for i in range(61, 100)]"
    )
    trabajo = lanzar(
        ruta_bd,
        "registro",
        None,
        None,
        [sys.executable, "-c", programa],
        tmp_path,
        None,
        None,
    )
    esperar(trabajo.id, 5)

    terminado = _leer(ruta_bd, trabajo.id)
    assert terminado.estado == "hecho"
    assert len(terminado.registro) == 40
    assert terminado.registro[0] == "x" * 500
    assert terminado.registro[-1] == "linea-99"


def test_salida_con_retorno_de_carro_actualiza_el_progreso(tmp_path):
    ruta_bd = tmp_path / "estudio.sqlite3"
    trabajo = lanzar(
        ruta_bd,
        "progreso",
        None,
        None,
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(b'1/2\\r2/2\\r'); sys.stdout.flush()",
        ],
        tmp_path,
        None,
        None,
    )
    esperar(trabajo.id, 5)

    terminado = _leer(ruta_bd, trabajo.id)
    assert terminado.progreso == 1.0
    assert terminado.registro == ["1/2", "2/2"]


def test_interrumpir_huerfanos_borra_temporal_y_libera_el_motor(tmp_path):
    ruta_bd = tmp_path / "estudio.sqlite3"
    temporal = tmp_path / "salida.generando"
    temporal.write_text("incompleta", encoding="utf-8")
    inicio = datetime.now().astimezone().isoformat()
    with closing(abrir_bd(ruta_bd)) as bd:
        cursor = bd.execute(
            """
            INSERT INTO trabajo
                (accion, estado, inicio, registro, temporal)
            VALUES (?, 'en_marcha', ?, '[]', ?)
            """,
            ("previa-grabacion", inicio, str(temporal)),
        )
        trabajo_id = cursor.lastrowid
        bd.commit()

        assert interrumpir_huerfanos(bd) == 1
        interrumpido = leer_trabajo(bd, trabajo_id)

    assert interrumpido is not None
    assert interrumpido.estado == "interrumpido"
    assert interrumpido.fin is not None
    assert not temporal.exists()

    nuevo = lanzar(
        ruta_bd,
        "nuevo",
        None,
        None,
        [sys.executable, "-c", "pass"],
        tmp_path,
        None,
        None,
    )
    esperar(nuevo.id, 5)
    assert _leer(ruta_bd, nuevo.id).estado == "hecho"


def test_crear_app_interrumpe_los_trabajos_huerfanos(cfg):
    temporal = cfg.estudio_dir / "salida.generando"
    temporal.write_text("incompleta", encoding="utf-8")
    with closing(abrir_bd(cfg.bd_ruta)) as bd:
        cursor = bd.execute(
            """
            INSERT INTO trabajo
                (accion, estado, inicio, registro, temporal)
            VALUES ('previa-grabacion', 'en_marcha', ?, '[]', ?)
            """,
            (datetime.now().astimezone().isoformat(), str(temporal)),
        )
        trabajo_id = cursor.lastrowid
        bd.commit()

    crear_app(cfg)

    assert _leer(cfg.bd_ruta, trabajo_id).estado == "interrumpido"
    assert not temporal.exists()


def test_fallo_al_arrancar_el_proceso_deja_error_y_libera_el_motor(tmp_path):
    ruta_bd = tmp_path / "estudio.sqlite3"
    trabajo = lanzar(
        ruta_bd,
        "sin-ejecutable",
        None,
        None,
        [str(tmp_path / "ejecutable-inexistente")],
        tmp_path,
        None,
        None,
    )
    esperar(trabajo.id, 5)

    fallido = _leer(ruta_bd, trabajo.id)
    assert fallido.estado == "error"
    assert fallido.error is not None
    assert fallido.error.startswith("No se pudo iniciar el trabajo:")
    assert fallido.fin is not None

    siguiente = lanzar(
        ruta_bd,
        "siguiente",
        None,
        None,
        [sys.executable, "-c", "pass"],
        tmp_path,
        None,
        None,
    )
    esperar(siguiente.id, 5)
    assert _leer(ruta_bd, siguiente.id).estado == "hecho"


def test_leer_trabajo_decodifica_el_registro_json(tmp_path):
    ruta_bd = tmp_path / "estudio.sqlite3"
    with closing(abrir_bd(ruta_bd)) as bd:
        cursor = bd.execute(
            """
            INSERT INTO trabajo
                (accion, estado, progreso, inicio, registro)
            VALUES ('prueba', 'hecho', 1, ?, ?)
            """,
            (
                datetime.now().astimezone().isoformat(),
                json.dumps(["línea ficticia"], ensure_ascii=False),
            ),
        )
        bd.commit()
        trabajo = leer_trabajo(bd, cursor.lastrowid)

    assert trabajo is not None
    assert trabajo.registro == ["línea ficticia"]


def test_leer_trabajo_inexistente_devuelve_none(tmp_path):
    with closing(abrir_bd(tmp_path / "estudio.sqlite3")) as bd:
        assert leer_trabajo(bd, 999) is None


def test_esquema_trabajo_tiene_los_valores_por_defecto(tmp_path):
    ruta_bd = tmp_path / "estudio.sqlite3"
    with closing(abrir_bd(ruta_bd)) as bd:
        cursor = bd.execute(
            "INSERT INTO trabajo (accion, estado, inicio) VALUES ('x', 'hecho', ?)",
            (datetime.now().astimezone().isoformat(),),
        )
        bd.commit()
        fila = bd.execute(
            "SELECT progreso, registro, curso, numero, fin, error, temporal "
            "FROM trabajo WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()

    assert fila == (0.0, "[]", None, None, None, None, None)
