import json
import os
import shutil
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from estudio_api.acciones import (
    PROGRESO_NINGUNO,
    AccionNoDisponible,
    OpcionesAccion,
    estado_montaje,
    plan_accion,
)
from estudio_api.app import crear_app
from estudio_api.decisiones import abrir_bd
from estudio_api.trabajos import (
    MENSAJES_HERRAMIENTA,
    MENSAJES_PREVIA,
    MENSAJES_REMOTION,
    PROGRESO_HERRAMIENTA,
    PROGRESO_REMOTION,
    TrabajoEnMarcha,
    esperar,
    leer_trabajo,
    listar_trabajos,
)
from tests.ayudas import TOKEN

CABECERAS = {"X-Estudio-Token": TOKEN}
RUTA_ACCIONES = "/api/cursos/react/lecciones/4/acciones"
RUTA_TEXTOS = "/api/cursos/react/lecciones/4/guion/textos"
RUTA_TOMA = "/api/cursos/react/lecciones/4/grabaciones/E03"
MENSAJE_LECCION_OCUPADA = (
    "No se puede cambiar mientras se prepara esta lección. "
    "Espera a que termine el trabajo."
)


def _marca(ruta: Path, marca: int) -> None:
    os.utime(ruta, ns=(marca, marca))


def _estado(catalogo):
    datos_guion = json.loads(catalogo["guion"].read_text(encoding="utf-8"))
    return estado_montaje(
        catalogo["config"],
        "react-04",
        catalogo["carpeta"],
        datos_guion,
    )


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
    montaje = catalogo["montaje"]
    toma = catalogo["toma"]
    alineacion = catalogo["alineacion"]
    guion = catalogo["guion"]
    contenido_montaje = montaje.read_bytes()

    montaje.unlink()
    assert _estado(catalogo).model_dump() == {
        "estado": "sin_montaje",
        "sin_alinear": [],
    }

    montaje.write_bytes(contenido_montaje)
    _marca(montaje, 300)
    _marca(toma, 400)
    assert _estado(catalogo).model_dump() == {
        "estado": "voz_sin_alinear",
        "sin_alinear": ["E03"],
    }

    _marca(alineacion, 500)
    _marca(guion, 600)
    assert _estado(catalogo).estado == "guion_cambiado"

    _marca(montaje, 700)
    assert _estado(catalogo).model_dump() == {
        "estado": "al_dia",
        "sin_alinear": [],
    }


@pytest.mark.parametrize("contenido", ["{roto", "[]"])
def test_estado_montaje_trata_json_no_objeto_como_sin_montaje(catalogo, contenido):
    catalogo["montaje"].write_text(contenido, encoding="utf-8")

    estado = _estado(catalogo)

    assert estado.model_dump() == {"estado": "sin_montaje", "sin_alinear": []}


def test_estado_montaje_usa_voz_archivo_y_descarta_rutas_invalidas(catalogo):
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

    estado = _estado(catalogo)

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
        "-f",
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
    especificacion = {
        "alinear-voz": (60 * 60, PROGRESO_HERRAMIENTA, MENSAJES_HERRAMIENTA),
        "preparar-montaje": (
            30 * 60,
            PROGRESO_HERRAMIENTA,
            MENSAJES_HERRAMIENTA,
        ),
        "previa-grabacion": (2 * 60 * 60, PROGRESO_REMOTION, MENSAJES_PREVIA),
        "render-leccion": (4 * 60 * 60, PROGRESO_REMOTION, MENSAJES_REMOTION),
        "video-final": (30 * 60, PROGRESO_NINGUNO, MENSAJES_HERRAMIENTA),
        "preparar-shorts": (
            30 * 60,
            PROGRESO_HERRAMIENTA,
            MENSAJES_HERRAMIENTA,
        ),
        "render-short": (60 * 60, PROGRESO_REMOTION, MENSAJES_REMOTION),
    }
    for accion, (tiempo, progreso, mensajes) in especificacion.items():
        assert planes[accion].tiempo_maximo == tiempo
        assert planes[accion].patron_progreso == progreso
        assert planes[accion].mensajes == mensajes
    assert all(
        planes[accion].entorno == {}
        for accion in (
            "previa-grabacion",
            "render-leccion",
            "video-final",
            "preparar-shorts",
            "render-short",
        )
    )


def _preparar_acciones_de_tomas(catalogo):
    carpeta = catalogo["carpeta"]
    guion = json.loads(catalogo["guion"].read_text(encoding="utf-8"))
    guion["escenas"].append(
        {
            "id": "E17",
            "modo": "camara",
            "titulo": "Escena ficticia de cámara",
            "cues": [{"texto": "Texto ficticio."}],
            "toma": {"original": "grabaciones/videos/original.mov"},
        }
    )
    catalogo["guion"].write_text(json.dumps(guion), encoding="utf-8")
    original = carpeta / "grabaciones" / "videos" / "original.mov"
    original.parent.mkdir()
    original.write_bytes(b"original-ficticio")
    entregas = carpeta / "grabaciones" / "entregas"
    entregas.mkdir()
    (entregas / "Facetune12345678.MOV").write_bytes(b"entrega-ficticia")
    shorts = json.loads(catalogo["shorts"].read_text(encoding="utf-8"))
    shorts["ganchosEntregados"] = {"g1": "12345678"}
    catalogo["shorts"].write_text(json.dumps(shorts), encoding="utf-8")
    return original


def test_plan_accion_construye_los_tres_comandos_de_tomas(catalogo, monkeypatch):
    config = catalogo["config"]
    carpeta = catalogo["carpeta"]
    original = _preparar_acciones_de_tomas(catalogo)
    monkeypatch.setattr(
        "estudio_api.acciones.shutil.which", lambda nombre: f"/bin-falso/{nombre}"
    )

    identificar = plan_accion(config, "react", 4, "identificar-tomas", OpcionesAccion())
    color = plan_accion(config, "react", 4, "color-ganchos", OpcionesAccion())
    mejorar = plan_accion(
        config, "react", 4, "mejorar-toma", OpcionesAccion(escena="E17")
    )

    destino = config.estudio_dir / "public" / "grabaciones" / "react-04" / "E17.mov"
    temporal = destino.with_name(".E17.generando.mov")
    assert identificar.comando == [
        "/bin-falso/node",
        "herramientas/identificar-tomas.mjs",
        "react-04",
    ]
    assert identificar.entorno == {"CURSOS_DIR": str(config.cursos_dir)}
    assert color.comando == [
        "/bin-falso/node",
        "herramientas/color/ganchos.mjs",
        "l4",
    ]
    assert mejorar.comando == [
        "/bin/zsh",
        "-f",
        "herramientas/superres/superres.sh",
        str(original),
        str(temporal),
    ]
    assert mejorar.objetivo == "E17"
    assert mejorar.temporal == temporal
    assert mejorar.destino == destino
    assert mejorar.copia == carpeta / "grabaciones" / "videos" / "ia" / "E17.mov"
    assert mejorar.instalar == "archivar"
    assert identificar.tiempo_maximo == color.tiempo_maximo == 60 * 60
    assert mejorar.tiempo_maximo == 3 * 60 * 60
    assert identificar.patron_progreso == color.patron_progreso == PROGRESO_HERRAMIENTA
    assert mejorar.patron_progreso == PROGRESO_NINGUNO
    assert all(
        plan.mensajes == MENSAJES_HERRAMIENTA for plan in (identificar, color, mejorar)
    )


def test_identificar_tomas_sin_entregas_da_409(catalogo):
    with pytest.raises(AccionNoDisponible) as captura:
        plan_accion(
            catalogo["config"],
            "react",
            4,
            "identificar-tomas",
            OpcionesAccion(),
        )

    assert captura.value.estado_http == 409
    assert captura.value.mensaje == "No hay tomas entregadas"


def test_color_ganchos_sin_ganchos_entregados_da_409(catalogo):
    with pytest.raises(AccionNoDisponible) as captura:
        plan_accion(catalogo["config"], "react", 4, "color-ganchos", OpcionesAccion())

    assert captura.value.estado_http == 409
    assert captura.value.mensaje == "No hay ganchos entregados"


def test_mejorar_toma_rechaza_escena_inexistente(catalogo):
    with pytest.raises(AccionNoDisponible) as captura:
        plan_accion(
            catalogo["config"],
            "react",
            4,
            "mejorar-toma",
            OpcionesAccion(escena="E99"),
        )

    assert captura.value.estado_http == 422
    assert captura.value.mensaje == "Esa escena no existe"


def test_mejorar_toma_lista_escenas_con_toma_y_ultimo_por_escena(catalogo):
    _preparar_acciones_de_tomas(catalogo)
    inicio = datetime.now().astimezone().isoformat()
    with closing(abrir_bd(catalogo["config"].bd_ruta)) as bd, bd:
        cursor = bd.execute(
            """
            INSERT INTO trabajo (accion, curso, numero, objetivo, estado, inicio)
            VALUES ('mejorar-toma', 'react', 4, 'E17', 'hecho', ?)
            """,
            (inicio,),
        )
        trabajo_id = cursor.lastrowid

    respuesta = catalogo["cliente"].get(RUTA_ACCIONES)

    assert respuesta.status_code == 200
    acciones = {accion["id"]: accion for accion in respuesta.json()}
    assert acciones["mejorar-toma"]["opciones"] == ["E17"]
    assert acciones["mejorar-toma"]["ultimo"]["id"] == trabajo_id
    assert acciones["mejorar-toma"]["ultimos"]["E17"]["id"] == trabajo_id


@pytest.mark.parametrize("original", [None, "../../fuera.mov"])
def test_mejorar_toma_rechaza_escena_sin_original_seguro(catalogo, original):
    guion = json.loads(catalogo["guion"].read_text(encoding="utf-8"))
    escena = {
        "id": "E17",
        "modo": "camara",
        "titulo": "Escena ficticia",
        "cues": [{"texto": "Texto ficticio."}],
    }
    if original is not None:
        escena["toma"] = {"original": original}
    guion["escenas"].append(escena)
    catalogo["guion"].write_text(json.dumps(guion), encoding="utf-8")

    with pytest.raises(AccionNoDisponible) as captura:
        plan_accion(
            catalogo["config"],
            "react",
            4,
            "mejorar-toma",
            OpcionesAccion(escena="E17"),
        )

    assert captura.value.estado_http == 409
    assert captura.value.mensaje == "Esa escena aún no tiene toma"


def test_mejorar_toma_rechaza_original_absoluto(catalogo, tmp_path):
    guion = json.loads(catalogo["guion"].read_text(encoding="utf-8"))
    guion["escenas"].append(
        {
            "id": "E17",
            "modo": "camara",
            "cues": [{"texto": "Texto ficticio."}],
            "toma": {"original": str(tmp_path / "fuera.mov")},
        }
    )
    catalogo["guion"].write_text(json.dumps(guion), encoding="utf-8")

    with pytest.raises(AccionNoDisponible) as captura:
        plan_accion(
            catalogo["config"],
            "react",
            4,
            "mejorar-toma",
            OpcionesAccion(escena="E17"),
        )

    assert captura.value.estado_http == 409
    assert captura.value.mensaje == "Esa escena aún no tiene toma"


def test_mejorar_toma_rechaza_enlace_a_original_de_otra_leccion(catalogo):
    otra = catalogo["config"].cursos_dir / "REACT" / "05-otra"
    original_ajeno = otra / "grabaciones" / "videos" / "ajeno.mov"
    original_ajeno.parent.mkdir(parents=True)
    original_ajeno.write_bytes(b"original-ajeno")
    enlace = catalogo["carpeta"] / "grabaciones" / "videos" / "enlace.mov"
    enlace.parent.mkdir(parents=True, exist_ok=True)
    enlace.symlink_to(original_ajeno)
    guion = json.loads(catalogo["guion"].read_text(encoding="utf-8"))
    guion["escenas"].append(
        {
            "id": "E17",
            "modo": "camara",
            "cues": [{"texto": "Texto ficticio."}],
            "toma": {"original": "grabaciones/videos/enlace.mov"},
        }
    )
    catalogo["guion"].write_text(json.dumps(guion), encoding="utf-8")

    with pytest.raises(AccionNoDisponible) as captura:
        plan_accion(
            catalogo["config"],
            "react",
            4,
            "mejorar-toma",
            OpcionesAccion(escena="E17"),
        )

    assert captura.value.estado_http == 409
    assert captura.value.mensaje == "Esa escena aún no tiene toma"


def test_preparar_mejorar_toma_limpia_temporal_de_copia_anterior(catalogo):
    _preparar_acciones_de_tomas(catalogo)
    plan = plan_accion(
        catalogo["config"],
        "react",
        4,
        "mejorar-toma",
        OpcionesAccion(escena="E17"),
    )
    assert plan.copia is not None
    temporal_copia = plan.copia.with_name(".E17.copiando.mov")
    temporal_copia.parent.mkdir(parents=True, exist_ok=True)
    temporal_copia.write_bytes(b"copia-interrumpida")

    assert plan.preparar is not None
    plan.preparar()

    assert not temporal_copia.exists()


def test_video_final_usa_slug_de_la_carpeta_en_disco(catalogo):
    guion = json.loads(catalogo["guion"].read_text(encoding="utf-8"))
    guion["carpeta"] = "REACT/04-slug-declarado-en-guion"
    catalogo["guion"].write_text(json.dumps(guion), encoding="utf-8")

    plan = plan_accion(
        catalogo["config"],
        "react",
        4,
        "video-final",
        OpcionesAccion(previa="previa-v3.mp4"),
    )

    assert plan.destino is not None
    assert plan.destino.name == "curso-react-04-importar-y-exportar.mp4"


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


def test_plan_rechaza_short_existente_de_otra_leccion(catalogo, monkeypatch):
    shorts_otra = catalogo["config"].estudio_dir / "shorts" / "l5" / "shorts.json"
    shorts_otra.parent.mkdir(parents=True)
    shorts_otra.write_text(
        json.dumps(
            {
                "leccion": "react-05",
                "shorts": [{"id": "short-de-otra-leccion"}],
            }
        ),
        encoding="utf-8",
    )

    def no_buscar(_nombre):
        raise AssertionError("No se debe buscar ningún binario")

    monkeypatch.setattr("estudio_api.acciones.shutil.which", no_buscar)

    with pytest.raises(AccionNoDisponible) as captura:
        plan_accion(
            catalogo["config"],
            "react",
            4,
            "render-short",
            OpcionesAccion(short="short-de-otra-leccion"),
        )

    assert captura.value.estado_http == 422
    assert captura.value.mensaje == "Ese short no existe"


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
        "identificar-tomas",
        "color-ganchos",
        "mejorar-toma",
    ]
    assert acciones["alinear-voz"]["disponible"] is False
    assert acciones["alinear-voz"]["motivo"] == "No hay voz grabada que alinear"
    assert acciones["preparar-shorts"]["disponible"] is False
    assert acciones["preparar-shorts"]["motivo"] == ("Esta lección no tiene shorts")
    assert acciones["render-short"]["disponible"] is False


def test_get_acciones_distingue_leccion_sin_guion(catalogo):
    catalogo["guion"].unlink()

    respuesta = catalogo["cliente"].get(RUTA_ACCIONES)

    assert respuesta.status_code == 200
    acciones = {accion["id"]: accion for accion in respuesta.json()}
    for accion in (
        "alinear-voz",
        "preparar-montaje",
        "previa-grabacion",
        "render-leccion",
        "mejorar-toma",
    ):
        assert acciones[accion]["disponible"] is False
        assert acciones[accion]["motivo"] == "Esta lección aún no tiene guion"


@pytest.mark.parametrize(
    "accion",
    [
        "alinear-voz",
        "preparar-montaje",
        "previa-grabacion",
        "render-leccion",
        "mejorar-toma",
    ],
)
def test_post_accion_en_leccion_sin_guion_da_409(catalogo, accion):
    catalogo["guion"].unlink()

    respuesta = catalogo["cliente"].post(
        f"{RUTA_ACCIONES}/{accion}",
        headers=CABECERAS,
        json={},
    )

    assert respuesta.status_code == 409
    assert respuesta.json()["detail"] == "Esta lección aún no tiene guion"


def test_post_previa_de_la_fase_4_sin_guion_mantiene_404(catalogo):
    catalogo["guion"].unlink()

    respuesta = catalogo["cliente"].post(
        "/api/cursos/react/lecciones/4/previa-grabacion",
        headers=CABECERAS,
        json={},
    )

    assert respuesta.status_code == 404
    assert respuesta.json()["detail"] == "La lección no existe"


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
    shutil.rmtree(catalogo["carpeta"] / "publicar" / "1-youtube-leccion")
    mkdir_real = Path.mkdir

    def mkdir_con_fallo(ruta, *args, **kwargs):
        if ruta.name == "1-youtube-leccion":
            raise OSError("fallo ficticio")
        return mkdir_real(ruta, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir_con_fallo)
    monkeypatch.setattr("estudio_api.acciones.shutil.which", lambda _: "/bin/falso")

    respuesta = catalogo["cliente"].post(
        f"{RUTA_ACCIONES}/video-final",
        headers=CABECERAS,
        json={"previa": "previa-v3.mp4"},
    )

    assert respuesta.status_code == 503
    assert respuesta.json()["detail"] == (
        "No se puede preparar la carpeta del resultado"
    )
    with closing(abrir_bd(catalogo["config"].bd_ruta)) as bd:
        assert listar_trabajos(bd, 10) == []


@pytest.mark.parametrize(
    ("directorio", "accion", "opciones"),
    [
        ("previa", "render-leccion", {}),
        ("publicar", "video-final", {"previa": "previa-v3.mp4"}),
        ("shorts", "render-short", {"short": "short-falso-1"}),
    ],
)
def test_enlace_de_resultado_fuera_da_503_y_no_lanza(
    catalogo,
    monkeypatch,
    directorio,
    accion,
    opciones,
):
    ruta = catalogo["carpeta"] / directorio
    if ruta.exists():
        shutil.rmtree(ruta)
    fuera = catalogo["config"].cursos_dir.parent / f"fuera-{directorio}"
    fuera.mkdir()
    ruta.symlink_to(fuera, target_is_directory=True)
    llamadas = []
    monkeypatch.setattr("estudio_api.acciones.shutil.which", lambda _: "/bin/falso")
    monkeypatch.setattr(
        "estudio_api.rutas_acciones.lanzar", lambda *args: llamadas.append(args)
    )

    respuesta = catalogo["cliente"].post(
        f"{RUTA_ACCIONES}/{accion}",
        headers=CABECERAS,
        json=opciones,
    )

    assert respuesta.status_code == 503
    assert respuesta.json()["detail"] == (
        "No se puede preparar la carpeta del resultado"
    )
    assert llamadas == []


def test_post_accion_con_trabajo_en_marcha_da_409(catalogo, monkeypatch):
    monkeypatch.setattr("estudio_api.acciones.shutil.which", lambda _: "/bin/falso")

    def rechazar(*_args):
        raise TrabajoEnMarcha

    monkeypatch.setattr("estudio_api.rutas_acciones.lanzar", rechazar)

    respuesta = catalogo["cliente"].post(
        f"{RUTA_ACCIONES}/alinear-voz",
        headers=CABECERAS,
        json={},
    )

    assert respuesta.status_code == 409
    assert respuesta.json()["detail"] == "Ya hay un trabajo en marcha"


def test_render_short_guarda_objetivo_y_aparece_en_ultimos(catalogo, monkeypatch):
    config = catalogo["config"]
    cliente = catalogo["cliente"]
    npx_falso = config.estudio_dir / "npx-falso"
    npx_falso.write_text('#!/bin/sh\nprintf video-ficticio > "$6"\n', encoding="utf-8")
    npx_falso.chmod(0o700)
    monkeypatch.setattr("estudio_api.acciones.shutil.which", lambda _: str(npx_falso))

    respuesta = cliente.post(
        f"{RUTA_ACCIONES}/render-short",
        headers=CABECERAS,
        json={"short": "short-falso-1"},
    )
    assert respuesta.status_code == 202
    esperar(respuesta.json()["id"], 5)

    acciones = {accion["id"]: accion for accion in cliente.get(RUTA_ACCIONES).json()}
    assert acciones["render-short"]["ultimo"]["objetivo"] == "short-falso-1"
    assert acciones["render-short"]["ultimos"]["short-falso-1"]["objetivo"] == (
        "short-falso-1"
    )
    with closing(abrir_bd(config.bd_ruta)) as bd:
        trabajo = leer_trabajo(bd, respuesta.json()["id"])
    assert trabajo is not None
    assert trabajo.objetivo == "short-falso-1"


def test_render_short_ultimo_es_el_mas_reciente_de_cualquier_objetivo(catalogo):
    inicio = datetime.now().astimezone().isoformat()
    with closing(abrir_bd(catalogo["config"].bd_ruta)) as bd, bd:
        bd.execute(
            """
            INSERT INTO trabajo (accion, curso, numero, objetivo, estado, inicio)
            VALUES ('render-short', 'react', 4, 'short-falso-1', 'hecho', ?)
            """,
            (inicio,),
        )
        cursor = bd.execute(
            """
            INSERT INTO trabajo (accion, curso, numero, objetivo, estado, inicio)
            VALUES ('render-short', 'react', 4, 'otro-short', 'hecho', ?)
            """,
            (inicio,),
        )
        ultimo_id = cursor.lastrowid

    acciones = {
        accion["id"]: accion for accion in catalogo["cliente"].get(RUTA_ACCIONES).json()
    }

    assert acciones["render-short"]["ultimo"]["id"] == ultimo_id
    assert set(acciones["render-short"]["ultimos"]) == {
        "short-falso-1",
        "otro-short",
    }


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


# --- Ronda final de la fase 5 ---


@contextmanager
def _trabajo_lento(catalogo, monkeypatch, accion):
    """Lanza ``accion`` con una herramienta falsa que espera a una señal."""
    config = catalogo["config"]
    continuar = config.estudio_dir / "continuar"
    herramienta = config.estudio_dir / "herramienta-lenta"
    herramienta.write_text(
        f'#!/bin/sh\nwhile [ ! -e "{continuar}" ]; do sleep 0.02; done\n',
        encoding="utf-8",
    )
    herramienta.chmod(0o700)
    monkeypatch.setattr("estudio_api.acciones.shutil.which", lambda _: str(herramienta))
    respuesta = catalogo["cliente"].post(
        f"{RUTA_ACCIONES}/{accion}",
        headers=CABECERAS,
        json={},
    )
    assert respuesta.status_code == 202
    try:
        yield respuesta.json()
    finally:
        continuar.touch()
        esperar(respuesta.json()["id"], 5)


def _registrar_en_marcha(config, accion, numero=4):
    inicio = datetime.now().astimezone().isoformat()
    with closing(abrir_bd(config.bd_ruta)) as bd, bd:
        bd.execute(
            """
            INSERT INTO trabajo (accion, curso, numero, estado, inicio)
            VALUES (?, 'react', ?, 'en_marcha', ?)
            """,
            (accion, numero, inicio),
        )


def _guardar_textos(cliente, texto):
    version = cliente.get("/api/cursos/react/lecciones/4/teleprompter").json()[
        "version"
    ]
    return cliente.put(
        RUTA_TEXTOS,
        headers=CABECERAS,
        json={"version": version, "escenas": [{"id": "E03", "cues": [texto]}]},
    )


def test_put_textos_mientras_se_prepara_el_montaje_da_409(catalogo, monkeypatch):
    cliente = catalogo["cliente"]
    antes = catalogo["guion"].read_bytes()

    with _trabajo_lento(catalogo, monkeypatch, "preparar-montaje"):
        respuesta = _guardar_textos(cliente, "Texto cambiado.")
        assert catalogo["guion"].read_bytes() == antes

    assert respuesta.status_code == 409
    assert respuesta.json()["detail"] == MENSAJE_LECCION_OCUPADA
    despues = _guardar_textos(cliente, "Texto cambiado.")
    assert despues.status_code == 200
    assert catalogo["guion"].read_bytes() != antes


@pytest.mark.parametrize(
    "accion",
    ["alinear-voz", "preparar-montaje", "preparar-shorts", "identificar-tomas"],
)
def test_put_textos_y_toma_con_trabajo_de_la_leccion_dan_409(
    catalogo, monkeypatch, accion
):
    cliente = catalogo["cliente"]
    _registrar_en_marcha(catalogo["config"], accion)
    antes = catalogo["guion"].read_bytes()
    toma_antes = catalogo["toma"].read_bytes()

    async def no_leer_el_cuerpo(*_args, **_kwargs):
        raise AssertionError("No se debe leer el cuerpo de la toma")

    monkeypatch.setattr(
        "estudio_api.rutas_teleprompter.guardar_toma", no_leer_el_cuerpo
    )

    textos = _guardar_textos(cliente, "Texto cambiado.")
    toma = cliente.put(
        RUTA_TOMA,
        headers={**CABECERAS, "Content-Type": "audio/wav"},
        content=b"RIFF-ficticio",
    )

    assert textos.status_code == 409
    assert textos.json()["detail"] == MENSAJE_LECCION_OCUPADA
    assert toma.status_code == 409
    assert toma.json()["detail"] == MENSAJE_LECCION_OCUPADA
    assert catalogo["guion"].read_bytes() == antes
    assert catalogo["toma"].read_bytes() == toma_antes


@pytest.mark.parametrize(
    ("accion", "numero"),
    [("render-leccion", 4), ("video-final", 4), ("preparar-montaje", 5)],
)
def test_otros_trabajos_no_bloquean_los_textos(catalogo, accion, numero):
    _registrar_en_marcha(catalogo["config"], accion, numero)

    respuesta = _guardar_textos(catalogo["cliente"], "Texto cambiado.")

    assert respuesta.status_code == 200


@pytest.mark.parametrize(
    ("enlace", "accion", "opciones"),
    [
        (("previa",), "render-leccion", {}),
        (("shorts",), "render-short", {"short": "short-falso-1"}),
        (("publicar",), "video-final", {"previa": "previa-v3.mp4"}),
        (
            ("publicar", "1-youtube-leccion"),
            "video-final",
            {"previa": "previa-v3.mp4"},
        ),
    ],
)
def test_carpeta_de_resultado_enlazada_dentro_de_la_raiz_da_503(
    catalogo, monkeypatch, enlace, accion, opciones
):
    carpeta = catalogo["carpeta"]
    otra = carpeta.parent / "05-otra" / "-".join(enlace)
    ruta = carpeta.joinpath(*enlace)
    if ruta.exists():
        shutil.copytree(ruta, otra)
        shutil.rmtree(ruta)
    else:
        otra.mkdir()
    ruta.symlink_to(otra, target_is_directory=True)
    contenido_otra = sorted(p.name for p in otra.rglob("*"))
    monkeypatch.setattr("estudio_api.acciones.shutil.which", lambda _: "/bin/falso")

    respuesta = catalogo["cliente"].post(
        f"{RUTA_ACCIONES}/{accion}",
        headers=CABECERAS,
        json=opciones,
    )

    assert respuesta.status_code == 503
    assert respuesta.json()["detail"] == (
        "No se puede preparar la carpeta del resultado"
    )
    assert sorted(p.name for p in otra.rglob("*")) == contenido_otra
    with closing(abrir_bd(catalogo["config"].bd_ruta)) as bd:
        assert listar_trabajos(bd, 10) == []


@pytest.mark.parametrize(
    ("accion", "opciones", "carpeta_resultado", "temporal", "destino"),
    [
        (
            "render-short",
            {"short": "short-falso-1"},
            "shorts",
            ".short-falso-1.generando.mp4",
            "short-falso-1.mp4",
        ),
        (
            "render-leccion",
            {},
            "previa",
            ".previa-v4.generando.mp4",
            "previa-v4.mp4",
        ),
    ],
)
def test_temporal_plantado_como_enlace_se_quita_antes_de_lanzar(
    catalogo, monkeypatch, accion, opciones, carpeta_resultado, temporal, destino
):
    config = catalogo["config"]
    fuera = config.cursos_dir.parent / "archivo-ajeno.txt"
    fuera.write_bytes(b"archivo ajeno")
    directorio = catalogo["carpeta"] / carpeta_resultado
    directorio.mkdir(exist_ok=True)
    (directorio / temporal).symlink_to(fuera)
    npx_falso = config.estudio_dir / "npx-falso"
    npx_falso.write_text('#!/bin/sh\nprintf video-nuevo > "$6"\n', encoding="utf-8")
    npx_falso.chmod(0o700)
    monkeypatch.setattr("estudio_api.acciones.shutil.which", lambda _: str(npx_falso))

    respuesta = catalogo["cliente"].post(
        f"{RUTA_ACCIONES}/{accion}",
        headers=CABECERAS,
        json=opciones,
    )
    assert respuesta.status_code == 202
    esperar(respuesta.json()["id"], 5)

    with closing(abrir_bd(config.bd_ruta)) as bd:
        assert leer_trabajo(bd, respuesta.json()["id"]).estado == "hecho"
    assert fuera.read_bytes() == b"archivo ajeno"
    assert not (directorio / destino).is_symlink()
    assert (directorio / destino).read_bytes() == b"video-nuevo"
    assert not os.path.lexists(directorio / temporal)


def test_temporal_de_la_previa_enlazado_no_borra_el_archivo_al_que_apunta(
    catalogo, monkeypatch
):
    config = catalogo["config"]
    directorio = config.estudio_dir / "out" / "previas-grabacion"
    directorio.mkdir(parents=True, exist_ok=True)
    otro = directorio / "otra-leccion.mp4"
    otro.write_bytes(b"previa de otra leccion")
    (directorio / "react-04.generando.mp4").symlink_to(otro)
    npx_falso = config.estudio_dir / "npx-falso"
    npx_falso.write_text('#!/bin/sh\nprintf previa-nueva > "$6"\n', encoding="utf-8")
    npx_falso.chmod(0o700)
    monkeypatch.setattr("estudio_api.acciones.shutil.which", lambda _: str(npx_falso))

    respuesta = catalogo["cliente"].post(
        f"{RUTA_ACCIONES}/previa-grabacion",
        headers=CABECERAS,
        json={},
    )
    assert respuesta.status_code == 202
    esperar(respuesta.json()["id"], 5)

    assert otro.read_bytes() == b"previa de otra leccion"
    assert not (directorio / "react-04.mp4").is_symlink()
    assert (directorio / "react-04.mp4").read_bytes() == b"previa-nueva"
    assert not os.path.lexists(directorio / "react-04.generando.mp4")


def test_video_final_con_anteriores_enlazado_fuera_no_mueve_nada(catalogo, monkeypatch):
    config = catalogo["config"]
    youtube = catalogo["carpeta"] / "publicar" / "1-youtube-leccion"
    final = youtube / "curso-react-04-importar-y-exportar.mp4"
    final.write_bytes(b"final anterior")
    fuera = config.cursos_dir.parent / "carpeta-ajena"
    fuera.mkdir()
    (youtube / "anteriores").symlink_to(fuera, target_is_directory=True)
    script = config.estudio_dir / "herramientas" / "publicar" / "sonido-redes.sh"
    script.parent.mkdir(parents=True)
    script.write_text('printf final-nuevo > "$2"\n', encoding="utf-8")

    respuesta = catalogo["cliente"].post(
        f"{RUTA_ACCIONES}/video-final",
        headers=CABECERAS,
        json={"previa": "previa-v3.mp4"},
    )
    assert respuesta.status_code == 202
    esperar(respuesta.json()["id"], 5)

    with closing(abrir_bd(config.bd_ruta)) as bd:
        trabajo = leer_trabajo(bd, respuesta.json()["id"])
    assert trabajo.estado == "error"
    assert trabajo.error == "No se pudo guardar el resultado"
    assert final.read_bytes() == b"final anterior"
    assert list(fuera.iterdir()) == []
    assert not os.path.lexists(
        youtube / ".curso-react-04-importar-y-exportar.generando.mp4"
    )


def test_video_final_instala_y_archiva_con_zsh_sin_configuracion(catalogo, monkeypatch):
    config = catalogo["config"]
    youtube = catalogo["carpeta"] / "publicar" / "1-youtube-leccion"
    final = youtube / "curso-react-04-importar-y-exportar.mp4"
    final.write_bytes(b"final anterior")
    script = config.estudio_dir / "herramientas" / "publicar" / "sonido-redes.sh"
    script.parent.mkdir(parents=True)
    script.write_text('printf final-nuevo > "$2"\n', encoding="utf-8")

    respuesta = catalogo["cliente"].post(
        f"{RUTA_ACCIONES}/video-final",
        headers=CABECERAS,
        json={"previa": "previa-v3.mp4"},
    )
    assert respuesta.status_code == 202
    esperar(respuesta.json()["id"], 5)

    with closing(abrir_bd(config.bd_ruta)) as bd:
        assert leer_trabajo(bd, respuesta.json()["id"]).estado == "hecho"
    assert final.read_bytes() == b"final-nuevo"
    archivados = list((youtube / "anteriores").iterdir())
    assert [ruta.read_bytes() for ruta in archivados] == [b"final anterior"]


def test_nombres_ocultos_no_cuentan_como_video_final_previa_ni_short(catalogo):
    cliente = catalogo["cliente"]
    carpeta = catalogo["carpeta"]
    youtube = carpeta / "publicar" / "1-youtube-leccion"
    for ruta in youtube.glob("*.mp4"):
        ruta.unlink()
    (youtube / ".curso-react-04-importar-y-exportar.generando.mp4").write_bytes(
        b"a medias"
    )
    (carpeta / "previa" / ".previa-v4.generando.mp4").write_bytes(b"a medias")
    verticales = carpeta / "publicar" / "2-shorts-y-reels"
    (verticales / ".short-9-oculto.mp4").write_bytes(b"a medias")
    (verticales / ".reel-oculto.mp4").write_bytes(b"a medias")

    ficha = cliente.get("/api/cursos/react/lecciones/4").json()
    piezas = {pieza["id"]: pieza for pieza in ficha["piezas"]}
    acciones = {accion["id"]: accion for accion in cliente.get(RUTA_ACCIONES).json()}

    assert ficha["estado"]["video_final"] is False
    assert piezas["leccion"]["video"] is None
    assert all("/." not in (pieza["video"] or "") for pieza in ficha["piezas"])
    assert [ruta.rsplit("/", 1)[1] for ruta in ficha["previas"]] == [
        "previa-v1.mp4",
        "previa-v3.mp4",
    ]
    assert ficha["estado"]["previa"].endswith("/previa-v3.mp4")
    assert acciones["video-final"]["opciones"] == ["previa-v1.mp4", "previa-v3.mp4"]

    (youtube / "curso-react-04-importar-y-exportar.mp4").write_bytes(b"final")
    ficha = cliente.get("/api/cursos/react/lecciones/4").json()
    piezas = {pieza["id"]: pieza for pieza in ficha["piezas"]}

    assert ficha["estado"]["video_final"] is True
    assert piezas["leccion"]["video"].endswith(
        "/1-youtube-leccion/curso-react-04-importar-y-exportar.mp4"
    )


def test_sin_montaje_tambien_lista_la_voz_sin_alinear(catalogo):
    catalogo["montaje"].unlink()
    _marca(catalogo["toma"], 400)

    assert _estado(catalogo).model_dump() == {
        "estado": "sin_montaje",
        "sin_alinear": ["E03"],
    }
    ficha = catalogo["cliente"].get("/api/cursos/react/lecciones/4").json()
    assert ficha["montaje"] == {"estado": "sin_montaje", "sin_alinear": ["E03"]}


def test_preparar_shorts_exige_el_montaje_de_la_leccion(catalogo, monkeypatch):
    catalogo["montaje"].unlink()
    monkeypatch.setattr("estudio_api.acciones.shutil.which", lambda _: "/bin/falso")

    acciones = {
        accion["id"]: accion for accion in catalogo["cliente"].get(RUTA_ACCIONES).json()
    }
    respuesta = catalogo["cliente"].post(
        f"{RUTA_ACCIONES}/preparar-shorts",
        headers=CABECERAS,
        json={},
    )

    assert acciones["preparar-shorts"]["disponible"] is False
    assert acciones["preparar-shorts"]["motivo"] == (
        "Prepara antes el montaje de la lección"
    )
    assert respuesta.status_code == 409
    assert respuesta.json()["detail"] == "Prepara antes el montaje de la lección"


@pytest.mark.parametrize(
    "contenido",
    [
        "{}",
        '{"fps": 30, "duracion": 30, "escenas": [{"id": "E99", "duracion": 30}]}',
    ],
)
def test_un_montaje_danado_es_sin_montaje_en_estado_previa_y_render(
    catalogo, contenido
):
    catalogo["montaje"].write_text(contenido, encoding="utf-8")
    _marca(catalogo["montaje"], 300)

    ficha = catalogo["cliente"].get("/api/cursos/react/lecciones/4").json()
    acciones = {
        accion["id"]: accion for accion in catalogo["cliente"].get(RUTA_ACCIONES).json()
    }

    assert _estado(catalogo).estado == "sin_montaje"
    assert ficha["montaje"]["estado"] == "sin_montaje"
    for accion in ("previa-grabacion", "render-leccion"):
        assert acciones[accion]["disponible"] is False
        assert acciones[accion]["motivo"] == "Esta lección aún no tiene montaje"
    assert acciones["preparar-shorts"]["motivo"] == (
        "Prepara antes el montaje de la lección"
    )


def test_cancelar_un_trabajo_que_no_existe_da_404(catalogo):
    respuesta = catalogo["cliente"].post(
        "/api/trabajos/999/cancelar",
        headers=CABECERAS,
        json={},
    )

    assert respuesta.status_code == 404
    assert respuesta.json()["detail"] == "El trabajo no existe"


def test_con_otro_trabajo_en_marcha_no_se_crea_ni_se_borra_nada(catalogo, monkeypatch):
    carpeta = catalogo["carpeta"]
    youtube = carpeta / "publicar" / "1-youtube-leccion"
    temporal_ajeno = youtube / ".curso-react-04-importar-y-exportar.generando.mp4"
    temporal_ajeno.write_bytes(b"lo escribe otro trabajo")

    with _trabajo_lento(catalogo, monkeypatch, "alinear-voz"):
        short = catalogo["cliente"].post(
            f"{RUTA_ACCIONES}/render-short",
            headers=CABECERAS,
            json={"short": "short-falso-1"},
        )
        final = catalogo["cliente"].post(
            f"{RUTA_ACCIONES}/video-final",
            headers=CABECERAS,
            json={"previa": "previa-v3.mp4"},
        )

    assert short.status_code == 409
    assert short.json()["detail"] == "Ya hay un trabajo en marcha"
    assert final.status_code == 409
    assert not (carpeta / "shorts").exists()
    assert temporal_ajeno.read_bytes() == b"lo escribe otro trabajo"
