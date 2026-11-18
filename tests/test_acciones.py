import json
import os
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from estudio_api.acciones import (
    AccionNoDisponible,
    OpcionesAccion,
    estado_montaje,
    plan_accion,
)
from estudio_api.app import crear_app
from estudio_api.decisiones import abrir_bd
from estudio_api.trabajos import esperar, leer_trabajo
from tests.ayudas import TOKEN

CABECERAS = {"X-Estudio-Token": TOKEN}
RUTA_ACCIONES = "/api/cursos/react/lecciones/4/acciones"


def _marca(ruta: Path, marca: int) -> None:
    os.utime(ruta, ns=(marca, marca))


@pytest.fixture
def catalogo(cfg):
    carpeta = cfg.cursos_dir / "REACT" / "04-importar-y-exportar"
    guion_ruta = cfg.estudio_dir / "lecciones" / "react-04.json"
    guion = json.loads(guion_ruta.read_text(encoding="utf-8"))
    guion["escenas"] = [
        {
            "id": "E03",
            "modo": "voz",
            "titulo": "Escena ficticia",
            "cues": [{"texto": "Texto ficticio."}],
        }
    ]
    guion_ruta.write_text(json.dumps(guion), encoding="utf-8")

    grabaciones = carpeta / "grabaciones"
    grabaciones.mkdir()
    toma = grabaciones / "E03.wav"
    toma.write_bytes(b"toma-ficticia")

    alineaciones = cfg.estudio_dir / "lecciones" / "tomas" / "react-04"
    alineaciones.mkdir(parents=True)
    alineacion = alineaciones / "E03-voz.json"
    alineacion.write_text("{}", encoding="utf-8")

    montaje = cfg.estudio_dir / "public" / "lecciones" / "react-04" / "montaje.json"
    montaje.write_text(
        json.dumps(
            {
                "fps": 30,
                "duracion": 30,
                "escenas": [{"id": "E03", "duracion": 30}],
            }
        ),
        encoding="utf-8",
    )

    previa = carpeta / "previa"
    for ruta in previa.iterdir():
        ruta.unlink()
    (previa / "previa-v1.mp4").write_bytes(b"v1")
    (previa / "previa-v3.mp4").write_bytes(b"v3")

    shorts_json = cfg.estudio_dir / "shorts" / "l4" / "shorts.json"
    shorts_json.parent.mkdir(parents=True)
    shorts_json.write_text(
        json.dumps(
            {
                "leccion": "react-04",
                "shorts": [
                    {"id": "short-falso-1"},
                    {"id": "otro-short"},
                    {"id": "ID INVALIDO"},
                ],
            }
        ),
        encoding="utf-8",
    )
    montaje_short = (
        cfg.estudio_dir / "public" / "shorts" / "short-falso-1" / "montaje.json"
    )
    montaje_short.parent.mkdir(parents=True)
    montaje_short.write_text("{}", encoding="utf-8")

    _marca(toma, 100)
    _marca(alineacion, 200)
    _marca(guion_ruta, 200)
    _marca(montaje, 300)

    config = cfg.model_copy(update={"token_escritura": TOKEN})
    with TestClient(
        crear_app(config),
        base_url="http://127.0.0.1:8000",
    ) as cliente:
        yield {
            "config": config,
            "cliente": cliente,
            "carpeta": carpeta,
            "guion": guion_ruta,
            "toma": toma,
            "alineacion": alineacion,
            "montaje": montaje,
            "shorts": shorts_json,
        }


def test_estado_montaje_respeta_prioridad_y_fechas(catalogo):
    config = catalogo["config"]
    carpeta = catalogo["carpeta"]
    montaje = catalogo["montaje"]
    toma = catalogo["toma"]
    alineacion = catalogo["alineacion"]
    guion = catalogo["guion"]

    montaje.unlink()
    assert estado_montaje(config, "react-04", carpeta).model_dump() == {
        "estado": "sin_montaje",
        "sin_alinear": [],
    }

    montaje.write_text("{}", encoding="utf-8")
    _marca(montaje, 300)
    _marca(toma, 400)
    assert estado_montaje(config, "react-04", carpeta).model_dump() == {
        "estado": "voz_sin_alinear",
        "sin_alinear": ["E03"],
    }

    _marca(alineacion, 500)
    _marca(guion, 600)
    assert estado_montaje(config, "react-04", carpeta).estado == "guion_cambiado"

    _marca(montaje, 700)
    assert estado_montaje(config, "react-04", carpeta).model_dump() == {
        "estado": "al_dia",
        "sin_alinear": [],
    }


def test_estado_montaje_usa_voz_archivo_y_descarta_rutas_invalidas(catalogo):
    config = catalogo["config"]
    carpeta = catalogo["carpeta"]
    guion = json.loads(catalogo["guion"].read_text(encoding="utf-8"))
    guion["escenas"].extend(
        [
            {
                "id": "E05",
                "modo": "voz",
                "voz": {"archivo": "tomas/voz-especial.wav"},
            },
            {
                "id": "E07",
                "modo": "voz",
                "voz": {"archivo": "../../fuera.wav"},
            },
        ]
    )
    catalogo["guion"].write_text(json.dumps(guion), encoding="utf-8")
    toma_especial = carpeta / "tomas" / "voz-especial.wav"
    toma_especial.parent.mkdir()
    toma_especial.write_bytes(b"voz")
    _marca(toma_especial, 800)
    _marca(catalogo["montaje"], 700)
    _marca(catalogo["alineacion"], 900)

    estado = estado_montaje(config, "react-04", carpeta)

    assert estado.estado == "voz_sin_alinear"
    assert estado.sin_alinear == ["E05"]


def test_get_leccion_incluye_estado_montaje(catalogo):
    respuesta = catalogo["cliente"].get("/api/cursos/react/lecciones/4")

    assert respuesta.status_code == 200
    assert respuesta.json()["montaje"] == {"estado": "al_dia", "sin_alinear": []}


def test_get_leccion_sin_guion_deja_montaje_en_null(catalogo):
    catalogo["guion"].unlink()

    respuesta = catalogo["cliente"].get("/api/cursos/react/lecciones/4")

    assert respuesta.status_code == 200
    assert respuesta.json()["montaje"] is None


def test_plan_accion_construye_los_siete_comandos_exactos(catalogo, monkeypatch):
    config = catalogo["config"]
    carpeta = catalogo["carpeta"]
    monkeypatch.setattr(
        "estudio_api.acciones.shutil.which", lambda nombre: f"/bin-falso/{nombre}"
    )

    planes = {
        accion: plan_accion(config, "react", 4, accion, opciones)
        for accion, opciones in {
            "alinear-voz": OpcionesAccion(),
            "preparar-montaje": OpcionesAccion(),
            "previa-grabacion": OpcionesAccion(),
            "render-leccion": OpcionesAccion(),
            "video-final": OpcionesAccion(previa="previa-v3.mp4"),
            "preparar-shorts": OpcionesAccion(),
            "render-short": OpcionesAccion(short="short-falso-1"),
        }.items()
    }

    assert planes["alinear-voz"].comando == [
        "/bin-falso/node",
        "herramientas/alinear-voz.mjs",
        "react-04",
    ]
    assert planes["preparar-montaje"].comando == [
        "/bin-falso/node",
        "herramientas/preparar-leccion.mjs",
        "react-04",
    ]
    assert planes["previa-grabacion"].comando == [
        "/bin-falso/npx",
        "--no",
        "remotion",
        "render",
        "src/index.ts",
        "Leccion",
        str(
            config.estudio_dir / "out" / "previas-grabacion" / "react-04.generando.mp4"
        ),
        '--props={"leccion":"react-04"}',
        "--scale=0.5",
        "--muted",
        "--crf=30",
    ]
    previa_v4 = carpeta / "previa" / "previa-v4.mp4"
    temporal_v4 = carpeta / "previa" / ".previa-v4.generando.mp4"
    assert planes["render-leccion"].comando == [
        "/bin-falso/npx",
        "--no",
        "remotion",
        "render",
        "src/index.ts",
        "Leccion",
        str(temporal_v4),
        '--props={"leccion":"react-04"}',
    ]
    destino_final = (
        carpeta
        / "publicar"
        / "1-youtube-leccion"
        / "curso-react-04-importar-y-exportar.mp4"
    )
    assert planes["video-final"].comando == [
        "/bin/zsh",
        "herramientas/publicar/sonido-redes.sh",
        str(carpeta / "previa" / "previa-v3.mp4"),
        str(destino_final.with_name(f".{destino_final.stem}.generando.mp4")),
    ]
    assert planes["preparar-shorts"].comando == [
        "/bin-falso/node",
        "herramientas/preparar-shorts.mjs",
        "l4",
    ]
    destino_short = carpeta / "shorts" / "short-falso-1.mp4"
    assert planes["render-short"].comando == [
        "/bin-falso/npx",
        "--no",
        "remotion",
        "render",
        "src/index.ts",
        "Short",
        str(destino_short.with_name(".short-falso-1.generando.mp4")),
        '--props={"short":"short-falso-1"}',
    ]

    assert all(plan.cwd == config.estudio_dir for plan in planes.values())
    assert planes["render-leccion"].destino == previa_v4
    assert planes["render-leccion"].temporal == temporal_v4
    assert planes["render-leccion"].instalar == "sin_pisar"
    assert planes["video-final"].destino == destino_final
    assert planes["video-final"].instalar == "archivar"
    assert planes["render-short"].destino == destino_short
    assert planes["render-short"].objetivo == "short-falso-1"
    assert planes["alinear-voz"].entorno == {"CURSOS_DIR": str(config.cursos_dir)}
    assert planes["preparar-montaje"].entorno == {"CURSOS_DIR": str(config.cursos_dir)}


@pytest.mark.parametrize(
    ("accion", "opciones", "estado", "mensaje"),
    [
        (
            "video-final",
            OpcionesAccion(previa="../../x.mp4"),
            422,
            "Esa versión no existe",
        ),
        (
            "video-final",
            OpcionesAccion(previa="previa-v99.mp4"),
            422,
            "Esa versión no existe",
        ),
        ("video-final", OpcionesAccion(), 422, "Esa versión no existe"),
        (
            "render-short",
            OpcionesAccion(short="s1;rm"),
            422,
            "Ese short no existe",
        ),
        (
            "render-short",
            OpcionesAccion(short="short-de-otra-leccion"),
            422,
            "Ese short no existe",
        ),
    ],
)
def test_plan_rechaza_opciones_manipuladas_antes_de_buscar_binario(
    catalogo, monkeypatch, accion, opciones, estado, mensaje
):
    def no_buscar(_nombre):
        raise AssertionError("No se debe buscar ningún binario")

    monkeypatch.setattr("estudio_api.acciones.shutil.which", no_buscar)

    with pytest.raises(AccionNoDisponible) as captura:
        plan_accion(catalogo["config"], "react", 4, accion, opciones)

    assert captura.value.estado_http == estado
    assert captura.value.mensaje == mensaje


def test_plan_render_leccion_exige_montaje_al_dia(catalogo):
    _marca(catalogo["guion"], 500)

    with pytest.raises(AccionNoDisponible) as captura:
        plan_accion(
            catalogo["config"],
            "react",
            4,
            "render-leccion",
            OpcionesAccion(),
        )

    assert captura.value.estado_http == 409
    assert captura.value.mensaje == "Guion cambiado: hay que regenerar el montaje"


def test_get_acciones_calcula_disponibilidad_y_opciones(catalogo):
    catalogo["toma"].unlink()
    catalogo["shorts"].unlink()

    respuesta = catalogo["cliente"].get(RUTA_ACCIONES)

    assert respuesta.status_code == 200
    acciones = {accion["id"]: accion for accion in respuesta.json()}
    assert [accion["id"] for accion in respuesta.json()] == [
        "alinear-voz",
        "preparar-montaje",
        "previa-grabacion",
        "render-leccion",
        "video-final",
        "preparar-shorts",
        "render-short",
    ]
    assert acciones["alinear-voz"]["disponible"] is False
    assert acciones["alinear-voz"]["motivo"] == "No hay voz grabada que alinear"
    assert acciones["preparar-shorts"]["disponible"] is False
    assert acciones["preparar-shorts"]["motivo"] == ("Esta lección no tiene shorts")
    assert acciones["render-short"]["disponible"] is False


def test_get_acciones_lista_shorts_validos_y_previas(catalogo):
    respuesta = catalogo["cliente"].get(RUTA_ACCIONES)

    acciones = {accion["id"]: accion for accion in respuesta.json()}
    assert acciones["video-final"]["opciones"] == [
        "previa-v1.mp4",
        "previa-v3.mp4",
    ]
    assert acciones["render-short"]["opciones"] == [
        "short-falso-1",
        "otro-short",
    ]


def test_video_final_sin_previas_tiene_el_motivo_literal(catalogo):
    for previa in (catalogo["carpeta"] / "previa").iterdir():
        previa.unlink()

    acciones = {
        accion["id"]: accion for accion in catalogo["cliente"].get(RUTA_ACCIONES).json()
    }

    assert acciones["video-final"]["disponible"] is False
    assert acciones["video-final"]["motivo"] == (
        "Aún no hay ninguna versión renderizada"
    )


def test_render_short_sin_montaje_da_409(catalogo, monkeypatch):
    montaje = (
        catalogo["config"].estudio_dir
        / "public"
        / "shorts"
        / "short-falso-1"
        / "montaje.json"
    )
    montaje.unlink()

    def no_buscar(_nombre):
        raise AssertionError("No se debe buscar npx si falta el montaje")

    monkeypatch.setattr("estudio_api.acciones.shutil.which", no_buscar)

    with pytest.raises(AccionNoDisponible) as captura:
        plan_accion(
            catalogo["config"],
            "react",
            4,
            "render-short",
            OpcionesAccion(short="short-falso-1"),
        )

    assert captura.value.estado_http == 409
    assert captura.value.mensaje == "Prepara los shorts antes de renderizar"


@pytest.mark.parametrize("contenido", ["{roto", "{}", '{"shorts": 3}'])
def test_shorts_json_roto_o_sin_lista_no_provoca_500(catalogo, contenido):
    catalogo["shorts"].write_text(contenido, encoding="utf-8")

    respuesta = catalogo["cliente"].get(RUTA_ACCIONES)

    assert respuesta.status_code == 200
    acciones = {accion["id"]: accion for accion in respuesta.json()}
    assert acciones["render-short"]["opciones"] == []
    assert acciones["render-short"]["disponible"] is False


def test_rutas_validan_token_accion_cuerpo_y_limite(catalogo, monkeypatch):
    cliente = catalogo["cliente"]
    monkeypatch.setattr("estudio_api.acciones.shutil.which", lambda _: "/bin/falso")

    assert cliente.post(f"{RUTA_ACCIONES}/alinear-voz", json={}).status_code == 401
    assert (
        cliente.post(
            f"{RUTA_ACCIONES}/accion-inventada", headers=CABECERAS, json={}
        ).status_code
        == 422
    )
    assert (
        cliente.post(
            f"{RUTA_ACCIONES}/render-short",
            headers=CABECERAS,
            json={"short": "short-falso-1", "extra": 1},
        ).status_code
        == 422
    )
    assert cliente.get("/api/trabajos?limite=0").status_code == 422


def test_post_opcion_invalida_no_lanza(catalogo, monkeypatch):
    llamadas = []
    monkeypatch.setattr(
        "estudio_api.rutas_acciones.lanzar", lambda *args: llamadas.append(args)
    )

    respuesta = catalogo["cliente"].post(
        f"{RUTA_ACCIONES}/video-final",
        headers=CABECERAS,
        json={"previa": "../../x.mp4"},
    )

    assert respuesta.status_code == 422
    assert respuesta.json()["detail"] == "Esa versión no existe"
    assert llamadas == []


def test_fallo_al_preparar_destino_da_503_y_no_lanza(catalogo, monkeypatch):
    llamadas = []
    mkdir_real = Path.mkdir

    def mkdir_con_fallo(ruta, *args, **kwargs):
        if ruta.name == "1-youtube-leccion":
            raise OSError("fallo ficticio")
        return mkdir_real(ruta, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir_con_fallo)
    monkeypatch.setattr(
        "estudio_api.rutas_acciones.lanzar", lambda *args: llamadas.append(args)
    )

    respuesta = catalogo["cliente"].post(
        f"{RUTA_ACCIONES}/video-final",
        headers=CABECERAS,
        json={"previa": "previa-v3.mp4"},
    )

    assert respuesta.status_code == 503
    assert respuesta.json()["detail"] == (
        "No se puede preparar la carpeta del resultado"
    )
    assert llamadas == []


def test_render_short_guarda_objetivo_y_aparece_en_ultimos(catalogo, monkeypatch):
    config = catalogo["config"]
    cliente = catalogo["cliente"]
    monkeypatch.setattr("estudio_api.acciones.shutil.which", lambda _: "/npx")

    temporal = catalogo["carpeta"] / "shorts" / ".short-falso-1.generando.mp4"

    def comando_falso(*_args, **_kwargs):
        from estudio_api.trabajos import PlanTrabajo

        return PlanTrabajo(
            accion="render-short",
            objetivo="short-falso-1",
            comando=[
                sys.executable,
                "-c",
                "import pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(b'video')",
                str(temporal),
            ],
            cwd=config.estudio_dir,
            temporal=temporal,
            destino=catalogo["carpeta"] / "shorts" / "short-falso-1.mp4",
            instalar="archivar",
        )

    monkeypatch.setattr("estudio_api.rutas_acciones.plan_accion", comando_falso)
    respuesta = cliente.post(
        f"{RUTA_ACCIONES}/render-short",
        headers=CABECERAS,
        json={"short": "short-falso-1"},
    )
    assert respuesta.status_code == 202
    esperar(respuesta.json()["id"], 5)

    acciones = {accion["id"]: accion for accion in cliente.get(RUTA_ACCIONES).json()}
    assert acciones["render-short"]["ultimos"]["short-falso-1"]["objetivo"] == (
        "short-falso-1"
    )
    with closing(abrir_bd(config.bd_ruta)) as bd:
        trabajo = leer_trabajo(bd, respuesta.json()["id"])
    assert trabajo is not None
    assert trabajo.objetivo == "short-falso-1"


def test_cancelar_terminado_da_409_y_listar_devuelve_trabajos(catalogo):
    config = catalogo["config"]
    inicio = datetime.now().astimezone().isoformat()
    with closing(abrir_bd(config.bd_ruta)) as bd, bd:
        cursor = bd.execute(
            "INSERT INTO trabajo (accion, estado, inicio) VALUES (?, ?, ?)",
            ("prueba", "hecho", inicio),
        )
        trabajo_id = cursor.lastrowid
    assert trabajo_id is not None

    cancelacion = catalogo["cliente"].post(
        f"/api/trabajos/{trabajo_id}/cancelar",
        headers=CABECERAS,
        json={},
    )
    listado = catalogo["cliente"].get("/api/trabajos?limite=20")

    assert cancelacion.status_code == 409
    assert cancelacion.json()["detail"] == "Ese trabajo no está en marcha"
    assert listado.status_code == 200
    assert listado.json()[0]["id"] == trabajo_id


def test_cancelar_devuelve_cualquier_trabajo_que_devuelva_el_motor(
    catalogo, monkeypatch
):
    config = catalogo["config"]
    inicio = datetime.now().astimezone().isoformat()
    with closing(abrir_bd(config.bd_ruta)) as bd, bd:
        cursor = bd.execute(
            "INSERT INTO trabajo (accion, estado, inicio) VALUES (?, ?, ?)",
            ("carrera", "hecho", inicio),
        )
        trabajo_id = cursor.lastrowid
    with closing(abrir_bd(config.bd_ruta)) as bd:
        terminado = leer_trabajo(bd, trabajo_id)
    assert terminado is not None
    monkeypatch.setattr("estudio_api.rutas_acciones.cancelar", lambda *_: terminado)

    respuesta = catalogo["cliente"].post(
        f"/api/trabajos/{trabajo_id}/cancelar",
        headers=CABECERAS,
        json={},
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "hecho"
