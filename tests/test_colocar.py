import hashlib
import json
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from estudio_api.app import crear_app
from estudio_api.colocar import (
    Asignacion,
    ColocacionNoValida,
    colocar_tomas,
    id_toma_vertical,
)
from estudio_api.decisiones import abrir_bd
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
        (entregas / archivo).write_bytes(f"video:{archivo}".encode())
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
