import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from contextlib import closing
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import estudio_api.trabajos as modulo_trabajos
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


def _registro(ruta_bd, trabajo_id):
    with closing(abrir_bd(ruta_bd)) as bd:
        fila = bd.execute(
            "SELECT registro FROM trabajo WHERE id = ?", (trabajo_id,)
        ).fetchone()
    assert fila is not None
    return json.loads(fila[0])


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
    registro = _registro(ruta_bd, trabajo.id)
    assert terminado.estado == "hecho"
    assert len(registro) == 40
    assert registro[0] == "x" * 500
    assert registro[-1] == "linea-99"


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
            (
                "import sys; "
                "sys.stdout.buffer.write(b'Bundling\\n\\rRendered 1/2\\rRendered 2/2\\n'); "
                "sys.stdout.flush()"
            ),
        ],
        tmp_path,
        None,
        None,
    )
    esperar(trabajo.id, 5)

    terminado = _leer(ruta_bd, trabajo.id)
    assert terminado.progreso == 1.0
    assert _registro(ruta_bd, trabajo.id) == ["Bundling", "Rendered 2/2"]


def test_salida_utf8_partida_entre_trozos_se_decodifica_una_sola_vez(
    tmp_path, monkeypatch
):
    ruta_bd = tmp_path / "estudio.sqlite3"

    class SalidaPartida:
        def __init__(self):
            self.trozos = [b"Espa\xc3", b"\xb1a\n", b""]
            self.closed = False

        def read1(self, _tamano):
            return self.trozos.pop(0)

        def close(self):
            self.closed = True

    class ProcesoFalso:
        def __init__(self):
            self.stdout = SalidaPartida()

        def wait(self):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(
        modulo_trabajos.subprocess, "Popen", lambda *a, **k: ProcesoFalso()
    )
    trabajo = lanzar(
        ruta_bd,
        "utf8",
        None,
        None,
        ["ejecutable-ficticio"],
        tmp_path,
        None,
        None,
    )
    esperar(trabajo.id, 5)

    assert _registro(ruta_bd, trabajo.id) == ["España"]


def test_texto_pendiente_sin_separador_se_recorta_a_500(tmp_path, monkeypatch):
    ruta_bd = tmp_path / "estudio.sqlite3"
    longitudes = []
    incorporar_real = modulo_trabajos._incorporar_linea

    def incorporar_limitado(linea, registro, progreso, *args, **kwargs):
        longitudes.append(len(linea))
        return incorporar_real(linea, registro, progreso, *args, **kwargs)

    monkeypatch.setattr(modulo_trabajos, "_incorporar_linea", incorporar_limitado)
    trabajo = lanzar(
        ruta_bd,
        "pendiente",
        None,
        None,
        [sys.executable, "-c", "print('x' * 2000, end='')"],
        tmp_path,
        None,
        None,
    )
    esperar(trabajo.id, 5)

    assert _registro(ruta_bd, trabajo.id) == ["x" * 500]
    assert max(longitudes) == 500


def test_fallo_al_guardar_avance_no_mata_el_render_y_se_reintenta(
    tmp_path, monkeypatch
):
    ruta_bd = tmp_path / "estudio.sqlite3"
    llamadas = 0
    guardar_real = modulo_trabajos._guardar_avance

    def guardar_inestable(*args):
        nonlocal llamadas
        llamadas += 1
        if llamadas == 1:
            raise OSError("fallo transitorio ficticio")
        guardar_real(*args)

    tiempos = iter([0.0, 2.0, 4.0])
    monkeypatch.setattr(modulo_trabajos, "_guardar_avance", guardar_inestable)
    monkeypatch.setattr(modulo_trabajos, "monotonic", lambda: next(tiempos))

    class Salida:
        def __init__(self):
            self.trozos = [b"1/2\n", b"2/2\n", b""]

        def read1(self, _tamano):
            return self.trozos.pop(0)

        def close(self):
            pass

    class Proceso:
        stdout = Salida()

        def wait(self):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(modulo_trabajos.subprocess, "Popen", lambda *a, **k: Proceso())
    trabajo = lanzar(
        ruta_bd,
        "avance",
        None,
        None,
        ["ejecutable-ficticio"],
        tmp_path,
        None,
        None,
    )
    esperar(trabajo.id, 5)

    terminado = _leer(ruta_bd, trabajo.id)
    assert llamadas == 2
    assert terminado.estado == "hecho"
    assert terminado.progreso == 1.0


def test_fallo_al_arrancar_hilo_deja_error_y_libera_bloqueo(tmp_path, monkeypatch):
    ruta_bd = tmp_path / "estudio.sqlite3"
    start_real = threading.Thread.start

    def fallar_start(_hilo):
        raise RuntimeError("fallo ficticio del hilo")

    monkeypatch.setattr(threading.Thread, "start", fallar_start)
    fallido = lanzar(
        ruta_bd,
        "hilo-roto",
        None,
        None,
        [sys.executable, "-c", "pass"],
        tmp_path,
        None,
        None,
    )

    guardado = _leer(ruta_bd, fallido.id)
    assert guardado.estado == "error"
    assert guardado.error == "No se pudo arrancar el render"
    monkeypatch.setattr(threading.Thread, "start", start_real)

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


def test_finalizar_no_modifica_un_trabajo_ya_interrumpido(tmp_path):
    ruta_bd = tmp_path / "estudio.sqlite3"
    inicio = datetime.now().astimezone().isoformat()
    with closing(abrir_bd(ruta_bd)) as bd:
        cursor = bd.execute(
            "INSERT INTO trabajo (accion, estado, inicio) VALUES (?, ?, ?)",
            ("interrumpido", "interrumpido", inicio),
        )
        bd.commit()
        trabajo_id = cursor.lastrowid

    modulo_trabajos._finalizar(
        ruta_bd, trabajo_id, "hecho", 1.0, ["no debe guardarse"], None
    )

    trabajo = _leer(ruta_bd, trabajo_id)
    assert trabajo.estado == "interrumpido"
    assert trabajo.progreso == 0.0
    assert _registro(ruta_bd, trabajo_id) == []


def test_finalizar_se_reintenta_tras_un_fallo_transitorio(tmp_path, monkeypatch):
    ruta_bd = tmp_path / "estudio.sqlite3"
    finalizar_real = modulo_trabajos._finalizar
    llamadas = 0

    def finalizar_inestable(*args):
        nonlocal llamadas
        llamadas += 1
        if llamadas == 1:
            raise OSError("fallo transitorio ficticio")
        finalizar_real(*args)

    monkeypatch.setattr(modulo_trabajos, "_finalizar", finalizar_inestable)
    trabajo = lanzar(
        ruta_bd,
        "finalizacion-inestable",
        None,
        None,
        [sys.executable, "-c", "pass"],
        tmp_path,
        None,
        None,
    )
    esperar(trabajo.id, 5)

    assert llamadas == 2
    assert _leer(ruta_bd, trabajo.id).estado == "hecho"


def test_doble_fallo_al_finalizar_no_bloquea_lanzamientos(tmp_path, monkeypatch):
    ruta_bd = tmp_path / "estudio.sqlite3"
    finalizar_real = modulo_trabajos._finalizar
    llamadas = 0

    def finalizar_roto(*_args):
        nonlocal llamadas
        llamadas += 1
        raise OSError("fallo persistente ficticio")

    monkeypatch.setattr(modulo_trabajos, "_finalizar", finalizar_roto)
    primero = lanzar(
        ruta_bd,
        "finalizacion-rota",
        None,
        None,
        [sys.executable, "-c", "pass"],
        tmp_path,
        None,
        None,
    )
    esperar(primero.id, 5)
    assert llamadas == 2
    assert _leer(ruta_bd, primero.id).estado == "en_marcha"

    monkeypatch.setattr(modulo_trabajos, "_finalizar", finalizar_real)
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

    assert _leer(ruta_bd, primero.id).estado == "interrumpido"
    assert _leer(ruta_bd, siguiente.id).estado == "hecho"


def test_popen_recibe_stdin_devnull(tmp_path, monkeypatch):
    ruta_bd = tmp_path / "estudio.sqlite3"
    popen_real = subprocess.Popen
    parametros = {}

    def abrir(*args, **kwargs):
        parametros.update(kwargs)
        return popen_real(*args, **kwargs)

    monkeypatch.setattr(modulo_trabajos.subprocess, "Popen", abrir)
    trabajo = lanzar(
        ruta_bd,
        "stdin",
        None,
        None,
        [sys.executable, "-c", "pass"],
        tmp_path,
        None,
        None,
    )
    esperar(trabajo.id, 5)

    assert parametros["stdin"] is subprocess.DEVNULL
    assert parametros["start_new_session"] is True
    assert parametros["shell"] is False


def test_stdout_se_cierra_al_terminar_el_hilo(tmp_path, monkeypatch):
    ruta_bd = tmp_path / "estudio.sqlite3"
    popen_real = subprocess.Popen
    procesos = []

    def abrir(*args, **kwargs):
        proceso = popen_real(*args, **kwargs)
        procesos.append(proceso)
        return proceso

    monkeypatch.setattr(modulo_trabajos.subprocess, "Popen", abrir)
    trabajo = lanzar(
        ruta_bd,
        "stdout",
        None,
        None,
        [sys.executable, "-c", "print('fin')"],
        tmp_path,
        None,
        None,
    )
    esperar(trabajo.id, 5)

    assert procesos[0].stdout is not None
    assert procesos[0].stdout.closed


def test_hilo_se_borra_del_registro_y_esperar_sigue_siendo_seguro(tmp_path):
    ruta_bd = tmp_path / "estudio.sqlite3"
    trabajo = lanzar(
        ruta_bd,
        "limpieza",
        None,
        None,
        [sys.executable, "-c", "pass"],
        tmp_path,
        None,
        None,
    )

    esperar(trabajo.id, 5)
    assert trabajo.id not in modulo_trabajos._HILOS
    esperar(trabajo.id, 5)


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
    assert fallido.error == "No se pudo arrancar el render"
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


def test_el_modelo_trabajo_no_expone_el_registro_guardado(tmp_path):
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
    assert "registro" not in trabajo.model_dump()
    assert _registro(ruta_bd, trabajo.id) == ["línea ficticia"]


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


# --- Ronda final de la fase 4: timeout, apagado, errores sin rutas y entorno ---

_HIJO_CON_NIETO = (
    "import os, pathlib, subprocess, sys, time\n"
    "pathlib.Path(sys.argv[2]).write_text('a medias')\n"
    "nieto = subprocess.Popen(['sleep', '60'])\n"
    "pathlib.Path(sys.argv[1]).write_text(f'{os.getpid()} {nieto.pid}')\n"
    "time.sleep(60)\n"
)


def _vivo(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _esperar_que_mueran(pids, plazo=5.0):
    limite = time.monotonic() + plazo
    while time.monotonic() < limite:
        if not any(_vivo(pid) for pid in pids):
            return True
        time.sleep(0.05)
    return False


def _esperar_pids(ruta, plazo=10.0):
    limite = time.monotonic() + plazo
    while time.monotonic() < limite:
        if ruta.exists() and len(ruta.read_text().split()) == 2:
            return [int(pid) for pid in ruta.read_text().split()]
        time.sleep(0.02)
    raise AssertionError("El proceso hijo no ha escrito sus pids")


def _matar_si_quedan(pids):
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError, PermissionError:
            pass


def test_timeout_mata_al_hijo_y_al_nieto_y_deja_error_generico(tmp_path, monkeypatch):
    monkeypatch.setattr(modulo_trabajos, "_GRACIA_TERMINAR", 2.0)
    ruta_bd = tmp_path / "estudio.sqlite3"
    pids_ruta = tmp_path / "pids"
    temporal = tmp_path / "salida.generando"

    trabajo = lanzar(
        ruta_bd,
        "colgado",
        None,
        None,
        [sys.executable, "-c", _HIJO_CON_NIETO, str(pids_ruta), str(temporal)],
        tmp_path,
        temporal,
        tmp_path / "salida.mp4",
        tiempo_maximo=1.5,
    )
    pids = _esperar_pids(pids_ruta)
    try:
        esperar(trabajo.id, 20)

        terminado = _leer(ruta_bd, trabajo.id)
        assert terminado.estado == "error"
        assert terminado.error == (
            "La vista previa ha tardado demasiado y se ha cancelado"
        )
        assert not temporal.exists()
        assert _esperar_que_mueran(pids)
        assert trabajo.id not in modulo_trabajos._HILOS
    finally:
        _matar_si_quedan(pids)


def test_el_tiempo_maximo_por_defecto_es_de_dos_horas():
    assert modulo_trabajos.TIEMPO_MAXIMO_RENDER == 2 * 60 * 60
    assert modulo_trabajos._GRACIA_TERMINAR == 10


def test_apagar_la_api_mata_el_render_y_lo_marca_interrumpido(cfg):
    pids_ruta = cfg.estudio_dir / "pids"
    temporal = cfg.estudio_dir / "salida.generando"
    pids = []
    try:
        with TestClient(crear_app(cfg), base_url="http://127.0.0.1:8000"):
            trabajo = lanzar(
                cfg.bd_ruta,
                "previa-grabacion",
                "react",
                4,
                [
                    sys.executable,
                    "-c",
                    _HIJO_CON_NIETO,
                    str(pids_ruta),
                    str(temporal),
                ],
                cfg.estudio_dir,
                temporal,
                cfg.estudio_dir / "salida.mp4",
            )
            pids = _esperar_pids(pids_ruta)
            assert all(_vivo(pid) for pid in pids)

        assert _esperar_que_mueran(pids)
        interrumpido = _leer(cfg.bd_ruta, trabajo.id)
        assert interrumpido.estado == "interrumpido"
        assert interrumpido.error == (
            "La vista previa se ha interrumpido al cerrar la API"
        )
        assert interrumpido.fin is not None
        assert not temporal.exists()
        assert not (cfg.estudio_dir / "salida.mp4").exists()
    finally:
        _matar_si_quedan(pids)


def test_apagar_una_app_no_toca_los_trabajos_de_otra_base(cfg, tmp_path):
    otra_bd = tmp_path / "otra" / "estudio.sqlite3"
    continuar = tmp_path / "continuar"
    trabajo = lanzar(
        otra_bd,
        "otra-app",
        None,
        None,
        [
            sys.executable,
            "-c",
            (
                "import pathlib,sys,time\n"
                "while not pathlib.Path(sys.argv[1]).exists(): time.sleep(.01)\n"
            ),
            str(continuar),
        ],
        tmp_path,
        None,
        None,
    )
    try:
        with TestClient(crear_app(cfg), base_url="http://127.0.0.1:8000"):
            pass
        assert _leer(otra_bd, trabajo.id).estado == "en_marcha"
    finally:
        continuar.touch()
        esperar(trabajo.id, 5)
    assert _leer(otra_bd, trabajo.id).estado == "hecho"


def test_cwd_inexistente_da_error_generico_sin_rutas(tmp_path, caplog):
    ruta_bd = tmp_path / "estudio.sqlite3"
    temporal = tmp_path / "salida.generando"

    with caplog.at_level(logging.ERROR, logger="estudio_api.trabajos"):
        trabajo = lanzar(
            ruta_bd,
            "sin-cwd",
            None,
            None,
            [sys.executable, "-c", "pass"],
            tmp_path / "no-existe",
            temporal,
            tmp_path / "salida.mp4",
        )
        esperar(trabajo.id, 5)

    fallido = _leer(ruta_bd, trabajo.id)
    assert fallido.estado == "error"
    assert fallido.error == "No se pudo arrancar el render"
    assert "/" not in fallido.error
    assert any(registro.exc_info for registro in caplog.records)


def test_fallo_de_os_replace_da_error_generico_sin_rutas(tmp_path, caplog):
    ruta_bd = tmp_path / "estudio.sqlite3"
    temporal = tmp_path / "salida.generando"

    with caplog.at_level(logging.ERROR, logger="estudio_api.trabajos"):
        trabajo = lanzar(
            ruta_bd,
            "sin-video",
            None,
            None,
            [sys.executable, "-c", f"print({str(tmp_path)!r})"],
            tmp_path,
            temporal,
            tmp_path / "salida.mp4",
        )
        esperar(trabajo.id, 5)

    fallido = _leer(ruta_bd, trabajo.id)
    assert fallido.estado == "error"
    assert fallido.error == "No se pudo guardar la vista previa"
    assert "/" not in fallido.error
    assert any(registro.exc_info for registro in caplog.records)


def test_la_api_no_devuelve_registro_ni_rutas_en_el_trabajo(cfg):
    trabajo = lanzar(
        cfg.bd_ruta,
        "previa-grabacion",
        "react",
        4,
        [sys.executable, "-c", f"print({str(cfg.estudio_dir)!r})"],
        cfg.estudio_dir,
        cfg.estudio_dir / "salida.generando",
        cfg.estudio_dir / "salida.mp4",
    )
    esperar(trabajo.id, 5)

    with TestClient(crear_app(cfg), base_url="http://127.0.0.1:8000") as cliente:
        respuesta = cliente.get(f"/api/trabajos/{trabajo.id}")

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert "registro" not in datos
    assert datos["error"] == "No se pudo guardar la vista previa"
    assert str(cfg.estudio_dir) not in respuesta.text


def test_el_render_recibe_un_entorno_minimo(tmp_path, monkeypatch):
    monkeypatch.setenv("ESTUDIO_TOKEN", "token-ficticio-que-no-debe-verse")
    monkeypatch.setenv("OTRA_VARIABLE", "tampoco")
    monkeypatch.setenv("NODE_ENV", "production")
    monkeypatch.setenv("LANG", "es_ES.UTF-8")
    ruta_bd = tmp_path / "estudio.sqlite3"
    salida = tmp_path / "entorno.json"

    trabajo = lanzar(
        ruta_bd,
        "entorno",
        None,
        None,
        [
            sys.executable,
            "-c",
            "import json,os,sys; open(sys.argv[1],'w').write(json.dumps(dict(os.environ)))",
            str(salida),
        ],
        tmp_path,
        None,
        None,
    )
    esperar(trabajo.id, 5)

    assert _leer(ruta_bd, trabajo.id).estado == "hecho"
    entorno = json.loads(salida.read_text())
    assert "ESTUDIO_TOKEN" not in entorno
    assert "OTRA_VARIABLE" not in entorno
    assert entorno["PATH"] == os.environ["PATH"]
    assert entorno["HOME"] == os.environ["HOME"]
    assert entorno["LANG"] == "es_ES.UTF-8"
    assert entorno["NODE_ENV"] == "production"


def test_entorno_del_render_solo_copia_las_variables_permitidas(monkeypatch):
    for nombre in ("TMPDIR", "USER", "NODE_ENV"):
        monkeypatch.delenv(nombre, raising=False)
    monkeypatch.setenv("PATH", "/bin")
    monkeypatch.setenv("HOME", "/casa-ficticia")
    monkeypatch.setenv("LANG", "C")
    monkeypatch.setenv("ESTUDIO_TOKEN", "x" * 40)

    assert modulo_trabajos._entorno_render() == {
        "PATH": "/bin",
        "HOME": "/casa-ficticia",
        "LANG": "C",
    }


def test_reciclar_una_fila_sin_hilo_borra_su_temporal(tmp_path):
    ruta_bd = tmp_path / "estudio.sqlite3"
    temporal = tmp_path / "huerfano.generando"
    temporal.write_text("a medias", encoding="utf-8")
    with closing(abrir_bd(ruta_bd)) as bd:
        cursor = bd.execute(
            """
            INSERT INTO trabajo (accion, estado, inicio, registro, temporal)
            VALUES ('previa-grabacion', 'en_marcha', ?, '[]', ?)
            """,
            (datetime.now().astimezone().isoformat(), str(temporal)),
        )
        huerfano = cursor.lastrowid
        bd.commit()

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

    assert _leer(ruta_bd, huerfano).estado == "interrumpido"
    assert not temporal.exists()
    assert _leer(ruta_bd, nuevo.id).estado == "hecho"
