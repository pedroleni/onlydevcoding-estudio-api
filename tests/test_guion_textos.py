import copy
import hashlib
import json
import os

import pytest
from fastapi.testclient import TestClient

from estudio_api.app import crear_app
from estudio_api.guion_textos import CambiosTextos, aplicar_textos
from tests.ayudas import TOKEN

RUTA_TELEPROMPTER = "/api/cursos/react/lecciones/4/teleprompter"
RUTA_TEXTOS = "/api/cursos/react/lecciones/4/guion/textos"
CABECERAS = {"X-Estudio-Token": TOKEN}


@pytest.fixture
def textos_guion(cfg):
    guion = {
        "ficha": "React",
        "numero": 4,
        "titulo": "Lección ficticia ñ 🎬",
        "carpeta": "REACT/04-importar-y-exportar",
        "escenas": [
            {
                "id": "E01",
                "modo": "camara",
                "titulo": "Presentación",
                "cues": [{"texto": "Texto de cámara."}],
                "puntos": ["Primer punto", "Segundo punto"],
            },
            {
                "id": "E02",
                "modo": "animacion",
                "titulo": "Animación",
                "cues": [{"texto": "Texto que no se puede editar."}],
            },
            {
                "id": "E03",
                "modo": "voz",
                "titulo": "Explicación",
                "cues": [
                    {"texto": "Primera frase.", "paso": "inicio"},
                    {"texto": "Segunda frase.", "pausa": 1.25},
                ],
            },
        ],
        "ganchos": [
            {"id": "g1", "titulo": "Primer gancho", "texto": "Texto uno."},
            {"id": "g2", "titulo": "Segundo gancho", "texto": "Texto dos."},
        ],
        "otro": {"se_conserva": True},
    }
    ruta = cfg.estudio_dir / "lecciones" / "react-04.json"
    contenido = json.dumps(guion, ensure_ascii=False, indent=2) + "\n"
    ruta.write_text(contenido, encoding="utf-8")
    config = cfg.model_copy(update={"token_escritura": TOKEN})
    with TestClient(
        crear_app(config),
        base_url="http://127.0.0.1:8000",
    ) as cliente:
        yield cliente, ruta, guion, contenido.encode("utf-8")


def _version(cliente: TestClient) -> str:
    respuesta = cliente.get(RUTA_TELEPROMPTER)
    assert respuesta.status_code == 200
    return respuesta.json()["version"]


def _guardar(
    cliente: TestClient,
    version: str,
    escenas: list[dict] | None = None,
    ganchos: list[dict] | None = None,
):
    cuerpo = {"version": version}
    if escenas is not None:
        cuerpo["escenas"] = escenas
    if ganchos is not None:
        cuerpo["ganchos"] = ganchos
    return cliente.put(
        RUTA_TEXTOS,
        headers=CABECERAS,
        json=cuerpo,
    )


def test_cambia_frase_y_punto_de_camara_en_la_misma_peticion(textos_guion):
    cliente, ruta, original, _ = textos_guion

    respuesta = _guardar(
        cliente,
        _version(cliente),
        [
            {
                "id": "E01",
                "cues": ["Nueva frase de cámara."],
                "puntos": ["Primer punto", "Nuevo segundo punto"],
            }
        ],
    )

    assert respuesta.status_code == 200
    guardado = json.loads(ruta.read_text(encoding="utf-8"))
    esperado = copy.deepcopy(original)
    esperado["escenas"][0]["cues"][0]["texto"] = "Nueva frase de cámara."
    esperado["escenas"][0]["puntos"][1] = "Nuevo segundo punto"
    assert guardado == esperado


def test_cambia_un_gancho_sin_tocar_sus_metadatos_ni_el_resto(textos_guion):
    cliente, ruta, original, bytes_originales = textos_guion

    respuesta = _guardar(
        cliente,
        _version(cliente),
        ganchos=[
            {"id": "g1", "texto": "Texto uno."},
            {"id": "g2", "texto": "  Gancho actualizado.  "},
        ],
    )

    assert respuesta.status_code == 200
    guardado = json.loads(ruta.read_text(encoding="utf-8"))
    esperado = copy.deepcopy(original)
    esperado["ganchos"][1]["texto"] = "Gancho actualizado."
    assert guardado == esperado
    assert (
        ruta.with_name("react-04.json.antes-de-editar").read_bytes() == bytes_originales
    )


@pytest.mark.parametrize(
    "ganchos",
    [
        [{"id": "g1", "texto": "Texto uno."}],
        [
            {"id": "g1", "texto": "Texto uno."},
            {"id": "g1", "texto": "Texto repetido."},
        ],
        [
            {"id": "g1", "texto": "Texto uno."},
            {"id": "desconocido", "texto": "Texto desconocido."},
        ],
        [
            {"id": "g1", "texto": "Texto uno."},
            {"id": "g2", "texto": "Dos\nlíneas"},
        ],
    ],
)
def test_ganchos_invalidos_devuelven_422_y_no_cambian_el_archivo(textos_guion, ganchos):
    cliente, ruta, _, bytes_originales = textos_guion

    respuesta = _guardar(cliente, _version(cliente), ganchos=ganchos)

    assert respuesta.status_code == 422
    assert ruta.read_bytes() == bytes_originales
    assert not ruta.with_name("react-04.json.antes-de-editar").exists()


def test_guion_con_ids_de_gancho_repetidos_devuelve_mensaje_fijo(textos_guion):
    cliente, ruta, _, _ = textos_guion
    guion = json.loads(ruta.read_text(encoding="utf-8"))
    guion["ganchos"][1]["id"] = "g1"
    ruta.write_text(json.dumps(guion, ensure_ascii=False), encoding="utf-8")
    bytes_antes = ruta.read_bytes()

    respuesta = _guardar(
        cliente,
        _version(cliente),
        ganchos=[
            {"id": "g1", "texto": "Texto uno."},
            {"id": "g1", "texto": "Texto dos."},
        ],
    )

    assert respuesta.status_code == 422
    assert respuesta.json()["detail"] == "Los ganchos del guion tienen ids repetidos"
    assert ruta.read_bytes() == bytes_antes


def test_peticion_sin_escenas_ni_ganchos_devuelve_mensaje_fijo(textos_guion):
    cliente, ruta, _, bytes_originales = textos_guion

    respuesta = _guardar(cliente, _version(cliente), escenas=[])

    assert respuesta.status_code == 422
    assert respuesta.json()["detail"] == "No hay cambios que guardar"
    assert ruta.read_bytes() == bytes_originales


def test_version_antigua_con_solo_ganchos_conserva_el_cambio_externo(textos_guion):
    cliente, ruta, _, _ = textos_guion
    version = _version(cliente)
    externo = ruta.read_text(encoding="utf-8").replace(
        "Lección ficticia", "Lección cambiada fuera"
    )
    ruta.write_text(externo, encoding="utf-8")

    respuesta = _guardar(
        cliente,
        version,
        ganchos=[
            {"id": "g1", "texto": "Texto uno."},
            {"id": "g2", "texto": "Texto de la app."},
        ],
    )

    assert respuesta.status_code == 409
    assert respuesta.json()["detail"] == (
        "El guion ha cambiado fuera de la app. Recarga antes de guardar."
    )
    assert ruta.read_text(encoding="utf-8") == externo


def test_cambia_una_frase_sin_tocar_el_resto_y_conserva_la_copia_inicial(
    textos_guion,
):
    cliente, ruta, original, bytes_originales = textos_guion

    respuesta = _guardar(
        cliente,
        _version(cliente),
        [
            {
                "id": "E03",
                "cues": ["Primera frase.", "  Nueva frase con ñ y 🎬.  "],
            }
        ],
    )

    assert respuesta.status_code == 200
    guardado = json.loads(ruta.read_text(encoding="utf-8"))
    esperado = copy.deepcopy(original)
    esperado["escenas"][2]["cues"][1]["texto"] = "Nueva frase con ñ y 🎬."
    assert guardado == esperado
    assert guardado["escenas"][2]["cues"][0]["paso"] == "inicio"
    assert guardado["escenas"][2]["cues"][1]["pausa"] == 1.25
    contenido = ruta.read_bytes()
    assert contenido.endswith(b"\n")
    assert b'\n  "ficha"' in contenido
    assert "ñ".encode() in contenido
    assert "🎬".encode() in contenido
    copia = ruta.with_name("react-04.json.antes-de-editar")
    assert copia.read_bytes() == bytes_originales
    assert respuesta.json()["version"] == hashlib.sha256(contenido).hexdigest()
    assert respuesta.json()["escenas"][1]["cues"][1]["texto"] == (
        "Nueva frase con ñ y 🎬."
    )

    bytes_copia = copia.read_bytes()
    segunda = _guardar(
        cliente,
        respuesta.json()["version"],
        [{"id": "E03", "cues": ["Otra primera.", "Nueva frase con ñ y 🎬."]}],
    )

    assert segunda.status_code == 200
    assert copia.read_bytes() == bytes_copia


def test_guardar_los_mismos_textos_conserva_los_bytes(textos_guion):
    cliente, ruta, _, bytes_originales = textos_guion

    respuesta = _guardar(
        cliente,
        _version(cliente),
        [{"id": "E03", "cues": ["Primera frase.", "Segunda frase."]}],
    )

    assert respuesta.status_code == 200
    assert ruta.read_bytes() == bytes_originales


@pytest.mark.parametrize(
    "cues",
    [
        ["Primera frase.", "Segunda frase."],
        ["  Primera frase.", "Segunda frase.  "],
    ],
)
def test_guardar_sin_cambios_no_escribe_ni_copia(textos_guion, cues):
    cliente, ruta, _, bytes_originales = textos_guion
    os.utime(ruta, ns=(1_000_000_000, 1_000_000_000))

    respuesta = _guardar(cliente, _version(cliente), [{"id": "E03", "cues": cues}])

    assert respuesta.status_code == 200
    assert respuesta.json()["version"] == hashlib.sha256(bytes_originales).hexdigest()
    assert ruta.read_bytes() == bytes_originales
    assert ruta.stat().st_mtime_ns == 1_000_000_000
    assert not ruta.with_name(f"{ruta.name}.antes-de-editar").exists()


def test_aplicar_textos_es_una_funcion_pura(textos_guion):
    _, _, original, _ = textos_guion
    antes = copy.deepcopy(original)
    cambios = CambiosTextos(
        version="0" * 64,
        escenas=[
            {
                "id": "E03",
                "cues": ["Primera frase.", "Texto cambiado."],
            }
        ],
    )

    resultado = aplicar_textos(original, cambios)

    assert original == antes
    assert resultado is not original
    assert resultado["escenas"][2]["cues"][1]["texto"] == "Texto cambiado."


@pytest.mark.parametrize(
    ("escenas", "mensaje"),
    [
        (
            [{"id": "E03", "cues": ["Solo una."]}],
            "La escena E03 tiene 2 frases y se han enviado 1",
        ),
        (
            [{"id": "E01", "puntos": ["Uno", "Dos", "Tres"]}],
            "La escena E01 tiene 2 puntos y se han enviado 3",
        ),
        (
            [{"id": "E03", "cues": ["Primera frase.", "   "]}],
            "El texto no puede estar vacío",
        ),
        (
            [{"id": "E03", "cues": ["Primera frase.", "Dos\nlíneas"]}],
            "El texto no puede contener saltos de línea ni caracteres de control",
        ),
        (
            [{"id": "E99", "cues": ["Texto."]}],
            "La escena E99 no existe",
        ),
    ],
)
def test_rechazos_de_reglas_devuelven_422_y_no_cambian_el_archivo(
    textos_guion, escenas, mensaje
):
    cliente, ruta, _, bytes_originales = textos_guion

    respuesta = _guardar(cliente, _version(cliente), escenas)

    assert respuesta.status_code == 422
    assert respuesta.json()["detail"] == mensaje
    assert ruta.read_bytes() == bytes_originales
    assert not ruta.with_name("react-04.json.antes-de-editar").exists()


def test_una_escena_de_animacion_no_se_puede_editar(textos_guion):
    cliente, ruta, _, bytes_originales = textos_guion

    respuesta = _guardar(
        cliente,
        _version(cliente),
        [{"id": "E02", "cues": ["Texto nuevo."]}],
    )

    assert respuesta.status_code == 422
    assert respuesta.json()["detail"] == "La escena E02 no se puede editar"
    assert ruta.read_bytes() == bytes_originales


def test_version_antigua_devuelve_409_y_conserva_el_cambio_externo(textos_guion):
    cliente, ruta, _, _ = textos_guion
    version = _version(cliente)
    externo = ruta.read_text(encoding="utf-8").replace(
        "Lección ficticia", "Lección cambiada fuera"
    )
    ruta.write_text(externo, encoding="utf-8")

    respuesta = _guardar(
        cliente,
        version,
        [{"id": "E03", "cues": ["Primera frase.", "Texto de la app."]}],
    )

    assert respuesta.status_code == 409
    assert respuesta.json()["detail"] == (
        "El guion ha cambiado fuera de la app. Recarga antes de guardar."
    )
    assert ruta.read_text(encoding="utf-8") == externo


def test_fallo_de_escritura_devuelve_503_y_no_un_conflicto(textos_guion, monkeypatch):
    cliente, _, _, _ = textos_guion

    def fallar_escritura(*_args, **_kwargs):
        raise OSError("fallo simulado")

    monkeypatch.setattr(
        "estudio_api.rutas_teleprompter.escribir_json_versionado",
        fallar_escritura,
    )

    respuesta = _guardar(
        cliente,
        _version(cliente),
        [{"id": "E03", "cues": ["Primera frase.", "Texto nuevo."]}],
    )

    assert respuesta.status_code == 503
    assert respuesta.json()["detail"] == "No se han podido guardar los textos"


def test_relee_el_archivo_justo_antes_de_escribir(textos_guion, monkeypatch):
    cliente, ruta, _, _ = textos_guion
    version = _version(cliente)
    externo = ruta.read_text(encoding="utf-8").replace(
        "Lección ficticia", "Cambio durante el guardado"
    )
    from estudio_api.guion_textos import aplicar_textos as aplicar_real

    def aplicar_con_cambio(guion, cambios):
        resultado = aplicar_real(guion, cambios)
        ruta.write_text(externo, encoding="utf-8")
        return resultado

    monkeypatch.setattr(
        "estudio_api.rutas_teleprompter.aplicar_textos", aplicar_con_cambio
    )

    respuesta = _guardar(
        cliente,
        version,
        [{"id": "E03", "cues": ["Primera frase.", "Texto de la app."]}],
    )

    assert respuesta.status_code == 409
    assert respuesta.json()["detail"] == (
        "El guion ha cambiado fuera de la app. Recarga antes de guardar."
    )
    assert ruta.read_text(encoding="utf-8") == externo


@pytest.mark.parametrize("texto", ["Texto \ud800 roto", "Texto \u202e invertido"])
def test_surrogates_sueltos_y_bidi_devuelven_422_sin_tocar_el_archivo(
    textos_guion, texto
):
    cliente, ruta, _, bytes_originales = textos_guion
    cuerpo = json.dumps(
        {
            "version": _version(cliente),
            "escenas": [{"id": "E03", "cues": ["Primera frase.", texto]}],
        }
    )

    respuesta = cliente.put(
        RUTA_TEXTOS,
        headers={**CABECERAS, "Content-Type": "application/json"},
        content=cuerpo.encode("ascii"),
    )

    assert respuesta.status_code == 422
    assert respuesta.json()["detail"] == (
        "El texto no puede contener saltos de línea ni caracteres de control"
    )
    assert ruta.read_bytes() == bytes_originales
    assert not ruta.with_name("react-04.json.antes-de-editar").exists()


@pytest.mark.parametrize("caracter", [chr(codigo) for codigo in range(0x202A, 0x202F)])
def test_rechaza_todos_los_controles_bidi_de_incrustacion(caracter):
    guion = {"escenas": [{"id": "E03", "modo": "voz", "cues": [{"texto": "a"}]}]}
    cambios = CambiosTextos(
        version="0" * 64,
        escenas=[{"id": "E03", "cues": [f"a{caracter}b"]}],
    )

    with pytest.raises(ValueError):
        aplicar_textos(guion, cambios)


@pytest.mark.parametrize("caracter", [chr(codigo) for codigo in range(0x2066, 0x206A)])
def test_rechaza_todos_los_aislamientos_bidi(caracter):
    guion = {"escenas": [{"id": "E03", "modo": "voz", "cues": [{"texto": "a"}]}]}
    cambios = CambiosTextos(
        version="0" * 64,
        escenas=[{"id": "E03", "cues": [f"a{caracter}b"]}],
    )

    with pytest.raises(ValueError):
        aplicar_textos(guion, cambios)


def test_emoji_con_zwj_se_guarda(textos_guion):
    cliente, ruta, _, _ = textos_guion

    respuesta = _guardar(
        cliente,
        _version(cliente),
        [
            {
                "id": "E03",
                "cues": ["Primera frase.", "Programo \U0001f469\u200d\U0001f4bb hoy."],
            }
        ],
    )

    assert respuesta.status_code == 200
    guardado = json.loads(ruta.read_text(encoding="utf-8"))
    assert (
        guardado["escenas"][2]["cues"][1]["texto"]
        == "Programo \U0001f469\u200d\U0001f4bb hoy."
    )


def test_escena_de_camara_sin_puntos_acepta_lista_vacia_sin_cambios(textos_guion):
    cliente, ruta, _, _ = textos_guion
    guion = json.loads(ruta.read_text(encoding="utf-8"))
    del guion["escenas"][0]["puntos"]
    ruta.write_text(
        json.dumps(guion, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    respuesta = _guardar(
        cliente,
        _version(cliente),
        [{"id": "E01", "cues": ["Texto de cámara."], "puntos": []}],
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["escenas"][0]["puntos"] == []
    assert "puntos" not in json.loads(ruta.read_text(encoding="utf-8"))["escenas"][0]


def test_escena_de_camara_sin_puntos_rechaza_puntos_nuevos(textos_guion):
    cliente, ruta, _, _ = textos_guion
    guion = json.loads(ruta.read_text(encoding="utf-8"))
    del guion["escenas"][0]["puntos"]
    ruta.write_text(
        json.dumps(guion, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    respuesta = _guardar(
        cliente,
        _version(cliente),
        [{"id": "E01", "puntos": ["Nuevo"]}],
    )

    assert respuesta.status_code == 422
    assert respuesta.json()["detail"] == "La escena E01 no tiene puntos editables"
