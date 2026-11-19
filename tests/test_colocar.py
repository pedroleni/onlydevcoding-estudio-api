import hashlib
import json
import sys
import threading
from contextlib import closing
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import estudio_api.colocar as modulo_colocar
from estudio_api.app import crear_app
from estudio_api.colocar import (
    Asignacion,
    ColocacionNoValida,
    colocar_tomas,
    id_toma_vertical,
)
from estudio_api.decisiones import abrir_bd
from estudio_api.rutas_acciones import lanzar_plan
from estudio_api.trabajos import PlanTrabajo, esperar
from tests.ayudas import TOKEN


def _guion(cfg) -> Path:
    ruta = cfg.estudio_dir / "lecciones" / "react-04.json"
    datos = {
        "ficha": "React",
        "numero": 4,
        "titulo": "Lección ficticia",
        "carpeta": "REACT/04-importar-y-exportar",
        "escenas": [
            {
                "id": "E17",
                "modo": "camara",
                "titulo": "Escena ficticia",
                "cues": [
                    {"texto": "Primera frase."},
                    {"texto": "Segunda frase."},
                ],
            }
        ],
        "ganchos": [{"id": "S2", "titulo": "Gancho dos", "texto": "Gancho ficticio."}],
    }
    ruta.write_text(
        json.dumps(datos, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return ruta


def _candidato_camara() -> dict:
    return {
        "tipo": "camara",
        "id": "E17",
        "puntuacion": 0.91,
        "desde": 0.25,
        "hasta": 4.75,
        "cues": [0.25, 2.5],
    }


def _toma(archivo: str, orientacion: str = "horizontal") -> dict:
    if orientacion == "horizontal":
        propuesta = {"tipo": "camara", "id": "E17"}
        candidatos = [_candidato_camara()]
    else:
        propuesta = {"tipo": "gancho", "id": "S2"}
        candidatos = [
            {
                "tipo": "gancho",
                "id": "S2",
                "puntuacion": 0.85,
                "desde": 0.1,
                "hasta": 3.8,
            }
        ]
    return {
        "archivo": archivo,
        "bytes": 13,
        "orientacion": orientacion,
        "duracion": 5.0,
        "texto": "Texto reconocido ficticio.",
        "propuesta": propuesta,
        "repite": None,
        "candidatos": candidatos,
    }


def _preparar(cfg, tomas: list[dict]) -> tuple[Path, Path]:
    guion = _guion(cfg)
    entregas = (
        cfg.cursos_dir / "REACT" / "04-importar-y-exportar" / "grabaciones" / "entregas"
    )
    analisis = entregas / ".analisis"
    analisis.mkdir(parents=True)
    for toma in tomas:
        archivo = toma["archivo"]
        contenido = f"video:{archivo}".encode()
        (entregas / archivo).write_bytes(contenido)
        # La propuesta solo vale para el archivo que se analizó (mismo tamaño).
        toma["bytes"] = len(contenido)
        (analisis / f"{archivo}.json").write_text(
            '[{"t":"texto","desde":0.1,"dura":0.5}]',
            encoding="utf-8",
        )
        if toma["orientacion"] == "vertical":
            (analisis / f"{archivo}.wav").write_bytes(b"audio-ficticio")
    (entregas / "propuesta.json").write_text(
        json.dumps({"version": 1, "guion": "react-04", "archivos": tomas}),
        encoding="utf-8",
    )
    return guion, entregas


def _colocar(cfg, asignaciones: list[Asignacion]):
    with closing(abrir_bd(cfg.bd_ruta)) as bd:
        return colocar_tomas(cfg, bd, "react", 4, asignaciones)


def _huella_arbol(*raices: Path) -> str:
    resumen = hashlib.sha256()
    for raiz in raices:
        if not raiz.exists():
            continue
        for ruta in sorted(raiz.rglob("*")):
            resumen.update(str(ruta.relative_to(raiz)).encode())
            if ruta.is_symlink():
                resumen.update(b"symlink")
                resumen.update(str(ruta.readlink()).encode())
            elif ruta.is_file():
                resumen.update(ruta.read_bytes())
    return resumen.hexdigest()


def test_coloca_camara_y_escribe_guion_con_copia_y_formato(cfg):
    toma = _toma("toma-a.mov")
    guion, entregas = _preparar(cfg, [toma])
    bytes_guion = guion.read_bytes()
    origen = (entregas / "toma-a.mov").read_bytes()

    resultado = _colocar(cfg, [Asignacion(archivo="toma-a.mov", destino="E17")])

    videos = entregas.parent / "videos"
    assert not (entregas / "toma-a.mov").exists()
    assert (videos / "toma-a.mov").read_bytes() == origen
    assert (
        cfg.estudio_dir / "public" / "grabaciones" / "react-04" / "E17.mov"
    ).read_bytes() == origen
    assert (
        cfg.estudio_dir / "lecciones" / "tomas" / "react-04" / "E17-camara.json"
    ).is_file()
    guardado = json.loads(guion.read_text(encoding="utf-8"))
    assert guardado["escenas"][0]["toma"] == {
        "original": "grabaciones/videos/toma-a.mov",
        "video": "grabaciones/react-04/E17.mov",
        "desde": 0.25,
        "hasta": 4.75,
        "cues": [0.25, 2.5],
    }
    assert guion.read_bytes().endswith(b"\n")
    assert b'\n  "ficha"' in guion.read_bytes()
    assert guion.with_name("react-04.json.antes-de-editar").read_bytes() == bytes_guion
    assert resultado.model_dump() == {
        "colocadas": [{"archivo": "toma-a.mov", "destino": "E17"}],
        "ganchos": 0,
    }


def test_sustituye_toma_sin_momentos_y_archiva_el_video_anterior(cfg):
    toma = _toma("toma-nueva.mov")
    guion, _ = _preparar(cfg, [toma])
    datos = json.loads(guion.read_text(encoding="utf-8"))
    datos["escenas"][0]["toma"] = {
        "original": "grabaciones/videos/toma-vieja.mov",
        "video": "grabaciones/react-04/E17.mov",
        "desde": 0,
        "hasta": 2,
        "cues": [0, 1],
        "momentos": [{"desde": 1}],
        "cortes": [{"desde": 1.2}],
    }
    guion.write_text(json.dumps(datos, indent=2) + "\n", encoding="utf-8")
    destino = cfg.estudio_dir / "public" / "grabaciones" / "react-04" / "E17.mov"
    destino.parent.mkdir(parents=True)
    destino.write_bytes(b"video-anterior")

    _colocar(cfg, [Asignacion(archivo="toma-nueva.mov", destino="E17")])

    anteriores = list((destino.parent / "anteriores").glob("E17-*.mov"))
    assert len(anteriores) == 1
    assert anteriores[0].read_bytes() == b"video-anterior"
    nueva = json.loads(guion.read_text(encoding="utf-8"))["escenas"][0]["toma"]
    assert "momentos" not in nueva
    assert "cortes" not in nueva


def test_coloca_gancho_y_conserva_el_resto_de_shorts(cfg):
    archivo = "Facetune0A1B2C3D-demo 2.MOV"
    _, entregas = _preparar(cfg, [_toma(archivo, "vertical")])
    shorts = cfg.estudio_dir / "shorts" / "l4" / "shorts.json"
    shorts.parent.mkdir(parents=True)
    existente = {
        "leccion": "react-04",
        "numero": 4,
        "tomas": {"OTRA": "Texto anterior."},
        "ganchosEntregados": {"S1": "OTRA"},
        "frases": {"se_conserva": True},
        "shorts": [{"id": "ficticio"}],
        "extra": "también",
    }
    shorts.write_text(json.dumps(existente, indent=2) + "\n", encoding="utf-8")
    bytes_anteriores = shorts.read_bytes()

    resultado = _colocar(cfg, [Asignacion(archivo=archivo, destino="S2")])

    carpeta_publica = cfg.estudio_dir / "public" / "shorts" / "l4" / "tomas"
    origen = entregas.parent / "videos" / archivo
    assert (carpeta_publica / "original" / "0A1B2C3D.mov").read_bytes() == (
        origen.read_bytes()
    )
    assert (carpeta_publica / "0A1B2C3D.mov").read_bytes() == origen.read_bytes()
    tomas = cfg.estudio_dir / "shorts" / "l4" / "tomas"
    assert (tomas / "0A1B2C3D.json").is_file()
    assert (tomas / "0A1B2C3D.wav").read_bytes() == b"audio-ficticio"
    guardado = json.loads(shorts.read_text(encoding="utf-8"))
    assert guardado["tomas"] == {
        "OTRA": "Texto anterior.",
        "0A1B2C3D": "Gancho ficticio.",
    }
    assert guardado["ganchosEntregados"] == {"S1": "OTRA", "S2": "0A1B2C3D"}
    assert guardado["frases"] == existente["frases"]
    assert guardado["shorts"] == existente["shorts"]
    assert guardado["extra"] == "también"
    assert (
        shorts.with_name("shorts.json.antes-de-editar").read_bytes() == bytes_anteriores
    )
    assert resultado.ganchos == 1


def test_coloca_cierre_con_texto_reconocido_y_sin_gancho_entregado(cfg):
    archivo = "cierre.mov"
    toma = _toma(archivo, "vertical")
    toma["texto"] = "Cierre reconocido ficticio."
    _, _ = _preparar(cfg, [toma])

    resultado = _colocar(cfg, [Asignacion(archivo=archivo, destino="cierre")])

    identificador = id_toma_vertical(archivo)
    shorts = json.loads(
        (cfg.estudio_dir / "shorts" / "l4" / "shorts.json").read_text(encoding="utf-8")
    )
    assert shorts["tomas"][identificador] == "Cierre reconocido ficticio."
    assert shorts["ganchosEntregados"] == {}
    assert resultado.ganchos == 0


def test_shorts_recien_creado_tiene_la_forma_completa(cfg):
    archivo = "cierre-nuevo.mov"
    toma = _toma(archivo, "vertical")
    toma["texto"] = "Cierre reconocido ficticio."
    _preparar(cfg, [toma])

    _colocar(cfg, [Asignacion(archivo=archivo, destino="cierre")])

    identificador = id_toma_vertical(archivo)
    shorts = json.loads(
        (cfg.estudio_dir / "shorts" / "l4" / "shorts.json").read_text(encoding="utf-8")
    )
    assert shorts == {
        "leccion": "react-04",
        "numero": 4,
        "tomas": {identificador: "Cierre reconocido ficticio."},
        "ganchosEntregados": {},
        "frases": {},
        "shorts": [],
    }


def test_dos_cierres_se_colocan_en_la_misma_operacion(cfg):
    primero = _toma("cierre-uno.mov", "vertical")
    segundo = _toma("cierre-dos.mov", "vertical")
    _preparar(cfg, [primero, segundo])

    resultado = _colocar(
        cfg,
        [
            Asignacion(archivo="cierre-uno.mov", destino="cierre"),
            Asignacion(archivo="cierre-dos.mov", destino="cierre"),
        ],
    )

    assert resultado.model_dump() == {
        "colocadas": [
            {"archivo": "cierre-uno.mov", "destino": "cierre"},
            {"archivo": "cierre-dos.mov", "destino": "cierre"},
        ],
        "ganchos": 0,
    }
    shorts = json.loads(
        (cfg.estudio_dir / "shorts" / "l4" / "shorts.json").read_text(encoding="utf-8")
    )
    assert set(shorts["tomas"]) == {
        id_toma_vertical("cierre-uno.mov"),
        id_toma_vertical("cierre-dos.mov"),
    }


@pytest.mark.parametrize(
    ("preparar", "asignaciones", "estado", "mensaje"),
    [
        (
            lambda cfg: _guion(cfg),
            [Asignacion(archivo="toma-a.mov", destino="E17")],
            409,
            "Identifica las tomas antes de colocarlas",
        ),
        (
            lambda cfg: _preparar(cfg, [_toma("vertical.mov", "vertical")]),
            [Asignacion(archivo="vertical.mov", destino="E17")],
            422,
            "Esa toma no encaja con ese destino",
        ),
        (
            lambda cfg: _preparar(cfg, [_toma("horizontal.mov")]),
            [Asignacion(archivo="horizontal.mov", destino="S2")],
            422,
            "Esa toma no encaja con ese destino",
        ),
        (
            lambda cfg: _preparar(cfg, [_toma("toma-a.mov"), _toma("toma-b.mov")]),
            [
                Asignacion(archivo="toma-a.mov", destino="E17"),
                Asignacion(archivo="toma-b.mov", destino="E17"),
            ],
            422,
            "Hay dos tomas para el mismo destino",
        ),
        (
            lambda cfg: _preparar(cfg, [_toma("toma-a.mov")]),
            [Asignacion(archivo="no-entregada.mov", destino="E17")],
            422,
            "Esa toma no está entregada",
        ),
        (
            lambda cfg: _preparar(cfg, [_toma("toma-a.mov")]),
            [Asignacion(archivo="toma-a.mov", destino="E99")],
            422,
            "Ese destino no existe",
        ),
    ],
)
def test_validacion_no_toca_el_disco(cfg, preparar, asignaciones, estado, mensaje):
    preparar(cfg)
    with closing(abrir_bd(cfg.bd_ruta)) as bd:
        antes = _huella_arbol(cfg.cursos_dir, cfg.estudio_dir)
        with pytest.raises(ColocacionNoValida) as captura:
            colocar_tomas(cfg, bd, "react", 4, asignaciones)
        despues = _huella_arbol(cfg.cursos_dir, cfg.estudio_dir)

    assert captura.value.estado_http == estado
    assert captura.value.mensaje == mensaje
    assert despues == antes


def test_un_trabajo_en_marcha_impide_colocar_sin_tocar_el_disco(cfg):
    _preparar(cfg, [_toma("toma-a.mov")])
    with closing(abrir_bd(cfg.bd_ruta)) as bd, bd:
        bd.execute(
            """
            INSERT INTO trabajo (accion, estado, inicio)
            VALUES ('otra-leccion', 'en_marcha', '2026-11-18T10:00:00+01:00')
            """
        )
    with closing(abrir_bd(cfg.bd_ruta)) as bd:
        antes = _huella_arbol(cfg.cursos_dir, cfg.estudio_dir)
        with pytest.raises(ColocacionNoValida) as captura:
            colocar_tomas(
                cfg,
                bd,
                "react",
                4,
                [Asignacion(archivo="toma-a.mov", destino="E17")],
            )
        despues = _huella_arbol(cfg.cursos_dir, cfg.estudio_dir)

    assert captura.value.estado_http == 409
    assert captura.value.mensaje == "Ya hay un trabajo en marcha"
    assert despues == antes


def test_no_pisa_un_original_que_ya_existe_en_videos(cfg):
    _preparar(cfg, [_toma("toma-a.mov")])
    videos = (
        cfg.cursos_dir / "REACT" / "04-importar-y-exportar" / "grabaciones" / "videos"
    )
    videos.mkdir()
    existente = videos / "toma-a.mov"
    existente.write_bytes(b"original-anterior")

    with closing(abrir_bd(cfg.bd_ruta)) as bd:
        antes = _huella_arbol(cfg.cursos_dir, cfg.estudio_dir)
        with pytest.raises(ColocacionNoValida) as captura:
            colocar_tomas(
                cfg,
                bd,
                "react",
                4,
                [Asignacion(archivo="toma-a.mov", destino="E17")],
            )
        despues = _huella_arbol(cfg.cursos_dir, cfg.estudio_dir)

    assert captura.value.estado_http == 409
    assert captura.value.mensaje == "Ya hay una toma con ese nombre"
    assert existente.read_bytes() == b"original-anterior"
    assert despues == antes


def test_toma_de_la_propuesta_que_ya_no_esta_en_disco_da_422(cfg):
    _, entregas = _preparar(cfg, [_toma("borrada.mov")])
    (entregas / "borrada.mov").unlink()

    with pytest.raises(ColocacionNoValida) as captura:
        _colocar(cfg, [Asignacion(archivo="borrada.mov", destino="E17")])

    assert captura.value.estado_http == 422
    assert captura.value.mensaje == "Esa toma no está entregada"


def test_dos_verticales_con_el_mismo_id_rechazan_la_ruta_de_salida_repetida(cfg):
    primero = "Facetune0A1B2C3D-demo.MOV"
    segundo = "Facetune0A1B2C3D-demo 2.MOV"
    _preparar(cfg, [_toma(primero, "vertical"), _toma(segundo, "vertical")])
    antes = _huella_arbol(cfg.cursos_dir, cfg.estudio_dir)

    with pytest.raises(ColocacionNoValida) as captura:
        _colocar(
            cfg,
            [
                Asignacion(archivo=primero, destino="S2"),
                Asignacion(archivo=segundo, destino="cierre"),
            ],
        )

    assert captura.value.estado_http == 422
    assert captura.value.mensaje == "Hay dos tomas para el mismo destino"
    assert _huella_arbol(cfg.cursos_dir, cfg.estudio_dir) == antes


def test_limpia_analisis_y_propuesta_pero_conserva_asignacion_nula(cfg):
    usadas = _toma("usar.mov")
    ignorada = _toma("guardar.mov")
    _, entregas = _preparar(cfg, [usadas, ignorada])

    _colocar(
        cfg,
        [
            Asignacion(archivo="usar.mov", destino="E17"),
            Asignacion(archivo="guardar.mov", destino=None),
        ],
    )

    assert not (entregas / ".analisis" / "usar.mov.json").exists()
    assert (entregas / ".analisis" / "guardar.mov.json").exists()
    assert (entregas / "guardar.mov").is_file()
    propuesta = json.loads((entregas / "propuesta.json").read_text(encoding="utf-8"))
    assert [toma["archivo"] for toma in propuesta["archivos"]] == ["guardar.mov"]

    _colocar(cfg, [Asignacion(archivo="guardar.mov", destino="E17")])

    assert not (entregas / "propuesta.json").exists()
    assert not any(
        ruta.suffix.lower() in {".mov", ".mp4"} for ruta in entregas.iterdir()
    )


def test_limpia_solo_los_tres_analisis_exactos_del_archivo(cfg):
    usada = _toma("toma.mov")
    parecida = _toma("toma.mov.b.mov")
    _, entregas = _preparar(cfg, [usada, parecida])
    analisis = entregas / ".analisis"
    (analisis / "toma.mov.wav").write_bytes(b"audio")
    (analisis / "toma.mov.origen").write_text("origen", encoding="utf-8")
    (analisis / "toma.mov.extra").write_text("conservar", encoding="utf-8")
    (analisis / "toma.mov.b.mov.wav").write_bytes(b"audio parecido")
    (analisis / "toma.mov.b.mov.origen").write_text("parecido", encoding="utf-8")

    _colocar(cfg, [Asignacion(archivo="toma.mov", destino="E17")])

    for extension in ("json", "wav", "origen"):
        assert not (analisis / f"toma.mov.{extension}").exists()
        assert (analisis / f"toma.mov.b.mov.{extension}").exists()
    assert (analisis / "toma.mov.extra").read_text(encoding="utf-8") == "conservar"


def test_fallo_al_instalar_la_segunda_copia_revierte_y_permite_reintentar(
    cfg, monkeypatch
):
    archivo = "Facetune0A1B2C3D-demo.MOV"
    _preparar(cfg, [_toma(archivo, "vertical")])
    antes = _huella_arbol(cfg.cursos_dir, cfg.estudio_dir)
    instalar_real = modulo_colocar.instalar_archivando
    llamadas = 0

    def fallar_segunda(temporal, destino):
        nonlocal llamadas
        llamadas += 1
        if llamadas == 2:
            raise OSError("fallo simulado al instalar")
        return instalar_real(temporal, destino)

    monkeypatch.setattr(modulo_colocar, "instalar_archivando", fallar_segunda)

    with pytest.raises(ColocacionNoValida) as captura:
        _colocar(cfg, [Asignacion(archivo=archivo, destino="S2")])

    assert captura.value.estado_http == 503
    assert captura.value.mensaje == "No se han podido colocar las tomas"
    assert _huella_arbol(cfg.cursos_dir, cfg.estudio_dir) == antes
    assert not list(cfg.cursos_dir.rglob("*.colocando.*"))
    assert not list(cfg.estudio_dir.rglob("*.colocando.*"))

    monkeypatch.setattr(modulo_colocar, "instalar_archivando", instalar_real)
    resultado = _colocar(cfg, [Asignacion(archivo=archivo, destino="S2")])

    assert resultado.ganchos == 1


def test_fallo_al_escribir_el_guion_revierte_y_permite_reintentar(cfg, monkeypatch):
    _preparar(cfg, [_toma("toma-a.mov")])
    antes = _huella_arbol(cfg.cursos_dir, cfg.estudio_dir)
    escribir_real = modulo_colocar.escribir_json_versionado

    def fallar_escritura(*_args, **_kwargs):
        raise OSError("fallo simulado al escribir")

    monkeypatch.setattr(modulo_colocar, "escribir_json_versionado", fallar_escritura)

    with pytest.raises(ColocacionNoValida) as captura:
        _colocar(cfg, [Asignacion(archivo="toma-a.mov", destino="E17")])

    assert captura.value.estado_http == 503
    assert captura.value.mensaje == "No se han podido colocar las tomas"
    assert _huella_arbol(cfg.cursos_dir, cfg.estudio_dir) == antes
    assert not list(cfg.cursos_dir.rglob("*.colocando.*"))
    assert not list(cfg.estudio_dir.rglob("*.colocando.*"))

    monkeypatch.setattr(modulo_colocar, "escribir_json_versionado", escribir_real)
    resultado = _colocar(cfg, [Asignacion(archivo="toma-a.mov", destino="E17")])

    assert resultado.colocadas[0].archivo == "toma-a.mov"


def test_fallo_al_instalar_restaura_la_copia_archivada(cfg, monkeypatch):
    guion, _ = _preparar(cfg, [_toma("toma-nueva.mov")])
    datos = json.loads(guion.read_text(encoding="utf-8"))
    datos["escenas"][0]["toma"] = {
        "original": "grabaciones/videos/toma-vieja.mov",
        "video": "grabaciones/react-04/E17.mov",
        "desde": 0,
        "hasta": 2,
        "cues": [0, 1],
        "momentos": [{"desde": 1}],
    }
    guion.write_text(json.dumps(datos, indent=2) + "\n", encoding="utf-8")
    video = cfg.estudio_dir / "public" / "grabaciones" / "react-04" / "E17.mov"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video-anterior")
    antes = _huella_arbol(cfg.cursos_dir, cfg.estudio_dir)
    instalar_real = modulo_colocar.instalar_archivando
    llamadas = 0

    def fallar_segunda(temporal, destino):
        nonlocal llamadas
        llamadas += 1
        if llamadas == 2:
            raise OSError("fallo simulado al instalar")
        return instalar_real(temporal, destino)

    monkeypatch.setattr(modulo_colocar, "instalar_archivando", fallar_segunda)

    with pytest.raises(ColocacionNoValida) as captura:
        _colocar(cfg, [Asignacion(archivo="toma-nueva.mov", destino="E17")])

    assert captura.value.estado_http == 503
    assert video.read_bytes() == b"video-anterior"
    assert not (video.parent / "anteriores").exists()
    assert _huella_arbol(cfg.cursos_dir, cfg.estudio_dir) == antes


def test_fallo_al_copiar_no_deja_temporales_ni_carpetas(cfg, monkeypatch):
    archivo = "Facetune0A1B2C3D-demo.MOV"
    _preparar(cfg, [_toma(archivo, "vertical")])
    antes = _huella_arbol(cfg.cursos_dir, cfg.estudio_dir)
    copia_real = modulo_colocar.shutil.copyfileobj
    llamadas = 0

    def disco_lleno(*args, **kwargs):
        nonlocal llamadas
        llamadas += 1
        if llamadas == 3:
            raise OSError(28, "No queda espacio en el disco")
        return copia_real(*args, **kwargs)

    monkeypatch.setattr(modulo_colocar.shutil, "copyfileobj", disco_lleno)

    with pytest.raises(ColocacionNoValida) as captura:
        _colocar(cfg, [Asignacion(archivo=archivo, destino="S2")])

    assert captura.value.estado_http == 503
    assert captura.value.mensaje == "No se han podido colocar las tomas"
    assert _huella_arbol(cfg.cursos_dir, cfg.estudio_dir) == antes

    monkeypatch.setattr(modulo_colocar.shutil, "copyfileobj", copia_real)
    assert _colocar(cfg, [Asignacion(archivo=archivo, destino="S2")]).ganchos == 1


def test_fallo_al_escribir_shorts_restaura_el_guion_ya_escrito(cfg, monkeypatch):
    vertical = "Facetune0A1B2C3D-demo.MOV"
    guion, _ = _preparar(cfg, [_toma("toma-a.mov"), _toma(vertical, "vertical")])
    shorts = cfg.estudio_dir / "shorts" / "l4" / "shorts.json"
    shorts.parent.mkdir(parents=True)
    shorts.write_text(
        json.dumps(
            {
                "leccion": "react-04",
                "numero": 4,
                "tomas": {},
                "ganchosEntregados": {},
                "frases": {},
                "shorts": [],
            }
        ),
        encoding="utf-8",
    )
    bytes_guion = guion.read_bytes()
    antes = _huella_arbol(cfg.cursos_dir, cfg.estudio_dir)
    escribir_real = modulo_colocar.escribir_json_versionado

    def fallar_shorts(ruta, datos, version):
        if ruta.name == "shorts.json":
            raise OSError("fallo simulado al escribir shorts.json")
        return escribir_real(ruta, datos, version)

    monkeypatch.setattr(modulo_colocar, "escribir_json_versionado", fallar_shorts)
    asignaciones = [
        Asignacion(archivo="toma-a.mov", destino="E17"),
        Asignacion(archivo=vertical, destino="S2"),
    ]

    with pytest.raises(ColocacionNoValida) as captura:
        _colocar(cfg, asignaciones)

    assert captura.value.estado_http == 503
    assert guion.read_bytes() == bytes_guion
    assert not guion.with_name("react-04.json.antes-de-editar").exists()
    assert _huella_arbol(cfg.cursos_dir, cfg.estudio_dir) == antes

    monkeypatch.setattr(modulo_colocar, "escribir_json_versionado", escribir_real)
    resultado = _colocar(cfg, asignaciones)

    assert resultado.ganchos == 1
    assert "toma" in json.loads(guion.read_text(encoding="utf-8"))["escenas"][0]


def test_lanzar_falla_mientras_se_coloca_y_funciona_al_terminar(cfg, monkeypatch):
    _preparar(cfg, [_toma("toma-a.mov")])
    copia_iniciada = threading.Event()
    continuar = threading.Event()
    copia_real = modulo_colocar.shutil.copyfileobj
    primera = True
    errores: list[Exception] = []

    def copiar_bloqueando(*args, **kwargs):
        nonlocal primera
        if primera:
            primera = False
            copia_iniciada.set()
            if not continuar.wait(5):
                raise TimeoutError("la prueba no liberó la copia")
        return copia_real(*args, **kwargs)

    def colocar_en_hilo():
        try:
            _colocar(cfg, [Asignacion(archivo="toma-a.mov", destino="E17")])
        except Exception as error:  # noqa: BLE001 - se comprueba en el assert
            errores.append(error)

    monkeypatch.setattr(modulo_colocar.shutil, "copyfileobj", copiar_bloqueando)
    hilo = threading.Thread(target=colocar_en_hilo)
    hilo.start()
    assert copia_iniciada.wait(5)
    plan = PlanTrabajo(
        accion="prueba",
        objetivo=None,
        comando=[sys.executable, "-c", "pass"],
        cwd=cfg.estudio_dir,
    )
    try:
        with pytest.raises(HTTPException) as captura:
            lanzar_plan(cfg, "react", 4, plan)
        assert captura.value.status_code == 409
        assert captura.value.detail == "Ya hay un trabajo en marcha"
    finally:
        continuar.set()
        hilo.join(5)

    assert not hilo.is_alive()
    assert errores == []
    trabajo = lanzar_plan(cfg, "react", 4, plan)
    esperar(trabajo.id, 5)


def test_id_vertical_de_nombre_generico_es_hexadecimal_estable():
    primero = id_toma_vertical("IMG_1234.MOV")

    assert primero == id_toma_vertical("IMG_1234.MOV")
    assert primero == hashlib.sha256(b"IMG_1234.MOV").hexdigest()[:8].upper()
    assert len(primero) == 8
    assert primero == primero.upper()
    assert all(caracter in "0123456789ABCDEF" for caracter in primero)


def test_enlace_en_videos_da_error_fijo_sin_mover_la_entrega(cfg, tmp_path):
    _preparar(cfg, [_toma("toma-a.mov")])
    videos = (
        cfg.cursos_dir / "REACT" / "04-importar-y-exportar" / "grabaciones" / "videos"
    )
    fuera = tmp_path / "videos-fuera"
    fuera.mkdir()
    videos.symlink_to(fuera, target_is_directory=True)

    with closing(abrir_bd(cfg.bd_ruta)) as bd:
        antes = _huella_arbol(cfg.cursos_dir, cfg.estudio_dir)
        with pytest.raises(ColocacionNoValida) as captura:
            colocar_tomas(
                cfg,
                bd,
                "react",
                4,
                [Asignacion(archivo="toma-a.mov", destino="E17")],
            )
        despues = _huella_arbol(cfg.cursos_dir, cfg.estudio_dir)

    assert captura.value.estado_http == 503
    assert captura.value.mensaje == "No se han podido colocar las tomas"
    assert despues == antes


def test_post_colocar_no_lo_captura_la_ruta_de_archivo(cfg):
    _preparar(cfg, [_toma("toma-a.mov")])
    config = cfg.model_copy(update={"token_escritura": TOKEN})
    with TestClient(crear_app(config), base_url="http://127.0.0.1:8000") as cliente:
        respuesta = cliente.post(
            "/api/cursos/react/lecciones/4/entregas/colocar",
            headers={"X-Estudio-Token": TOKEN},
            json={"asignaciones": [{"archivo": "toma-a.mov", "destino": "E17"}]},
        )

    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "colocadas": [{"archivo": "toma-a.mov", "destino": "E17"}],
        "ganchos": 0,
    }


def test_post_colocar_rechaza_campos_extra(cfg):
    _preparar(cfg, [_toma("toma-a.mov")])
    config = cfg.model_copy(update={"token_escritura": TOKEN})
    with TestClient(crear_app(config), base_url="http://127.0.0.1:8000") as cliente:
        respuesta = cliente.post(
            "/api/cursos/react/lecciones/4/entregas/colocar",
            headers={"X-Estudio-Token": TOKEN},
            json={
                "asignaciones": [
                    {"archivo": "toma-a.mov", "destino": "E17", "extra": True}
                ]
            },
        )

    assert respuesta.status_code == 422


def test_post_colocar_leccion_inexistente_devuelve_404(cfg):
    config = cfg.model_copy(update={"token_escritura": TOKEN})
    with TestClient(crear_app(config), base_url="http://127.0.0.1:8000") as cliente:
        respuesta = cliente.post(
            "/api/cursos/react/lecciones/99/entregas/colocar",
            headers={"X-Estudio-Token": TOKEN},
            json={"asignaciones": []},
        )

    assert respuesta.status_code == 404
    assert respuesta.json()["detail"] == "La lección no existe"


def _shorts_a_mano(cfg, datos: dict) -> Path:
    ruta = cfg.estudio_dir / "shorts" / "l4" / "shorts.json"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return ruta


def test_coloca_gancho_en_shorts_hecho_a_mano_sin_ganchos_entregados(cfg):
    archivo = "Facetune0A1B2C3D-demo.MOV"
    _preparar(cfg, [_toma(archivo, "vertical")])
    existente = {
        "leccion": "react-04",
        "numero": 4,
        "realceGancho": {"color": "#ffcc00", "desde": 0.5},
        "tomas": {"AAAA0001": "Toma ficticia hecha a mano."},
        "frases": {"AAAA0001": [{"t": "frase ficticia", "desde": 0.1}]},
        "shorts": [{"id": "short-ficticio", "tomas": ["AAAA0001"]}],
    }
    shorts = _shorts_a_mano(cfg, existente)

    resultado = _colocar(cfg, [Asignacion(archivo=archivo, destino="S2")])

    guardado = json.loads(shorts.read_text(encoding="utf-8"))
    assert resultado.ganchos == 1
    assert guardado["ganchosEntregados"] == {"S2": "0A1B2C3D"}
    assert guardado["tomas"] == {
        "AAAA0001": "Toma ficticia hecha a mano.",
        "0A1B2C3D": "Gancho ficticio.",
    }
    for clave in ("leccion", "numero", "realceGancho", "frases", "shorts"):
        assert guardado[clave] == existente[clave]
    assert set(guardado) == {*existente, "ganchosEntregados"}


def test_ganchos_entregados_que_no_es_objeto_da_503_sin_tocar_nada(cfg):
    archivo = "Facetune0A1B2C3D-demo.MOV"
    _preparar(cfg, [_toma(archivo, "vertical")])
    _shorts_a_mano(
        cfg,
        {"leccion": "react-04", "numero": 4, "tomas": {}, "ganchosEntregados": []},
    )
    antes = _huella_arbol(cfg.cursos_dir, cfg.estudio_dir)

    with pytest.raises(ColocacionNoValida) as captura:
        _colocar(cfg, [Asignacion(archivo=archivo, destino="S2")])

    assert captura.value.estado_http == 503
    assert _huella_arbol(cfg.cursos_dir, cfg.estudio_dir) == antes


def test_tiempos_redondeados_se_limitan_a_la_duracion_en_el_guion(cfg):
    toma = _toma("toma-a.mov")
    toma["candidatos"][0]["hasta"] = 5.005
    toma["candidatos"][0]["cues"] = [0.25, 5.004]
    guion, _ = _preparar(cfg, [toma])

    _colocar(cfg, [Asignacion(archivo="toma-a.mov", destino="E17")])

    escrita = json.loads(guion.read_text(encoding="utf-8"))["escenas"][0]["toma"]
    assert escrita["hasta"] == 5.0
    assert escrita["cues"] == [0.25, 5.0]


@pytest.mark.parametrize(
    "texto",
    ["linea1\nlinea2", "aviso\x07", "invertido\u202eoculto", "tab\tseparado"],
)
def test_texto_de_cierre_no_valido_da_422_sin_tocar_nada(cfg, texto):
    toma = _toma("cierre.mov", "vertical")
    toma["texto"] = texto
    _preparar(cfg, [toma])
    antes = _huella_arbol(cfg.cursos_dir, cfg.estudio_dir)

    with pytest.raises(ColocacionNoValida) as captura:
        _colocar(cfg, [Asignacion(archivo="cierre.mov", destino="cierre")])

    assert captura.value.estado_http == 422
    assert captura.value.mensaje == "El texto de la toma no es válido"
    assert _huella_arbol(cfg.cursos_dir, cfg.estudio_dir) == antes


def test_cierre_no_pisa_el_texto_corregido_a_mano(cfg):
    archivo = "cierre.mov"
    identificador = id_toma_vertical(archivo)
    toma = _toma(archivo, "vertical")
    toma["texto"] = "Transcripción automática ficticia."
    _preparar(cfg, [toma])
    shorts = _shorts_a_mano(
        cfg,
        {
            "leccion": "react-04",
            "numero": 4,
            "tomas": {identificador: "Texto ficticio corregido a mano."},
            "ganchosEntregados": {},
        },
    )

    _colocar(cfg, [Asignacion(archivo=archivo, destino="cierre")])

    guardado = json.loads(shorts.read_text(encoding="utf-8"))
    assert guardado["tomas"] == {identificador: "Texto ficticio corregido a mano."}


def test_gancho_no_pisa_el_texto_corregido_a_mano(cfg):
    archivo = "Facetune0A1B2C3D-demo.MOV"
    _preparar(cfg, [_toma(archivo, "vertical")])
    shorts = _shorts_a_mano(
        cfg,
        {
            "leccion": "react-04",
            "numero": 4,
            "tomas": {"0A1B2C3D": "texto corregido"},
            "ganchosEntregados": {"S2": "OTRA"},
        },
    )

    resultado = _colocar(cfg, [Asignacion(archivo=archivo, destino="S2")])

    guardado = json.loads(shorts.read_text(encoding="utf-8"))
    assert guardado["tomas"] == {"0A1B2C3D": "texto corregido"}
    assert guardado["ganchosEntregados"] == {"S2": "0A1B2C3D"}
    assert resultado.ganchos == 1


def test_fallo_de_ruta_al_limpiar_analisis_no_impide_responder(
    cfg, monkeypatch, caplog
):
    _preparar(cfg, [_toma("toma-a.mov")])

    def ruta_fuera(*_args, **_kwargs):
        raise ValueError("La ruta sale de la raíz")

    monkeypatch.setattr(modulo_colocar, "_limpiar_analisis", ruta_fuera)

    with caplog.at_level("WARNING", logger="estudio_api.colocar"):
        resultado = _colocar(cfg, [Asignacion(archivo="toma-a.mov", destino="E17")])

    assert resultado.colocadas[0].destino == "E17"
    assert "No se pudo limpiar el análisis de una toma" in caplog.text


def _espiar_pasos(cfg, monkeypatch) -> list[tuple[str, str]]:
    """Apunta, en orden, cada paso de la colocación que toca el disco."""
    pasos: list[tuple[str, str]] = []

    def relativa(ruta) -> str:
        ruta = Path(ruta)
        for raiz in (cfg.cursos_dir, cfg.estudio_dir):
            if ruta.is_relative_to(raiz):
                return ruta.relative_to(raiz).as_posix()
        return str(ruta)

    def espia(nombre, real, *, ruta_de):
        def envoltorio(*args, **kwargs):
            pasos.append((nombre, relativa(ruta_de(*args))))
            return real(*args, **kwargs)

        return envoltorio

    for nombre, atributo, ruta_de in (
        ("carpeta", "_crear_directorios_reales", lambda ruta, *_: ruta),
        ("copiar", "_preparar_copia", lambda salida, *_: salida.destino),
        ("instalar", "instalar_archivando", lambda _temporal, destino: destino),
        ("json", "escribir_json_versionado", lambda ruta, *_: ruta),
    ):
        real = getattr(modulo_colocar, atributo)
        monkeypatch.setattr(
            modulo_colocar, atributo, espia(nombre, real, ruta_de=ruta_de)
        )
    rename_real = modulo_colocar.os.rename
    monkeypatch.setattr(
        modulo_colocar.os,
        "rename",
        espia("mover", rename_real, ruta_de=lambda _origen, destino: destino),
    )
    return pasos


def test_coloca_en_orden_carpetas_copias_originales_instalaciones_y_json(
    cfg, monkeypatch
):
    vertical = "Facetune0A1B2C3D-demo.MOV"
    _preparar(cfg, [_toma("toma-a.mov"), _toma(vertical, "vertical")])
    pasos = _espiar_pasos(cfg, monkeypatch)

    _colocar(
        cfg,
        [
            Asignacion(archivo="toma-a.mov", destino="E17"),
            Asignacion(archivo=vertical, destino="S2"),
        ],
    )

    videos = "REACT/04-importar-y-exportar/grabaciones/videos"
    assert pasos == [
        ("carpeta", videos),
        ("carpeta", "public/grabaciones/react-04"),
        ("carpeta", "lecciones/tomas/react-04"),
        ("carpeta", "public/shorts/l4/tomas/original"),
        ("carpeta", "public/shorts/l4/tomas"),
        ("carpeta", "shorts/l4/tomas"),
        ("carpeta", "shorts/l4/tomas"),
        ("carpeta", "shorts/l4"),
        ("copiar", "public/grabaciones/react-04/E17.mov"),
        ("copiar", "lecciones/tomas/react-04/E17-camara.json"),
        ("copiar", "public/shorts/l4/tomas/original/0A1B2C3D.mov"),
        ("copiar", "public/shorts/l4/tomas/0A1B2C3D.mov"),
        ("copiar", "shorts/l4/tomas/0A1B2C3D.json"),
        ("copiar", "shorts/l4/tomas/0A1B2C3D.wav"),
        ("mover", f"{videos}/toma-a.mov"),
        ("mover", f"{videos}/{vertical}"),
        ("instalar", "public/grabaciones/react-04/E17.mov"),
        ("instalar", "lecciones/tomas/react-04/E17-camara.json"),
        ("instalar", "public/shorts/l4/tomas/original/0A1B2C3D.mov"),
        ("instalar", "public/shorts/l4/tomas/0A1B2C3D.mov"),
        ("instalar", "shorts/l4/tomas/0A1B2C3D.json"),
        ("instalar", "shorts/l4/tomas/0A1B2C3D.wav"),
        ("json", "lecciones/react-04.json"),
        ("json", "shorts/l4/shorts.json"),
    ]


def test_fallo_al_mover_el_segundo_original_devuelve_el_primero(cfg, monkeypatch):
    vertical = "Facetune0A1B2C3D-demo.MOV"
    _, entregas = _preparar(cfg, [_toma("toma-a.mov"), _toma(vertical, "vertical")])
    antes = _huella_arbol(cfg.cursos_dir, cfg.estudio_dir)
    rename_real = modulo_colocar.os.rename

    def fallar_segundo(origen, destino, *args, **kwargs):
        if Path(origen).name == vertical and Path(destino).parent.name == "videos":
            raise OSError("fallo simulado al mover")
        return rename_real(origen, destino, *args, **kwargs)

    monkeypatch.setattr(modulo_colocar.os, "rename", fallar_segundo)
    asignaciones = [
        Asignacion(archivo="toma-a.mov", destino="E17"),
        Asignacion(archivo=vertical, destino="S2"),
    ]

    with pytest.raises(ColocacionNoValida) as captura:
        _colocar(cfg, asignaciones)

    assert captura.value.estado_http == 503
    assert captura.value.mensaje == "No se han podido colocar las tomas"
    assert (entregas / "toma-a.mov").read_bytes() == b"video:toma-a.mov"
    assert not (entregas.parent / "videos").exists()
    assert not list(cfg.cursos_dir.rglob("*.colocando*"))
    assert not list(cfg.estudio_dir.rglob("*.colocando*"))
    assert _huella_arbol(cfg.cursos_dir, cfg.estudio_dir) == antes

    monkeypatch.setattr(modulo_colocar.os, "rename", rename_real)
    resultado = _colocar(cfg, asignaciones)

    assert [toma.archivo for toma in resultado.colocadas] == ["toma-a.mov", vertical]
