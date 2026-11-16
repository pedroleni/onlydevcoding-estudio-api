import pytest

RUTA_PREVIA = "cursos/REACT/04-importar-y-exportar/previa/previa-v1.mp4"


@pytest.mark.parametrize(
    "ruta",
    [
        "cursos/../../etc/passwd",
        "/etc/passwd",
        "cursos/REACT/.env",
        "estudio/lecciones/react-04.json",
        "cursos/enlace-fuera.mp4",
    ],
)
def test_medios_prohibidos_devuelven_404_sin_detalle(cliente, ruta):
    respuesta = cliente.get("/api/medios", params={"ruta": ruta})

    assert respuesta.status_code == 404
    assert respuesta.content == b""


def test_medio_completo(cliente):
    respuesta = cliente.get("/api/medios", params={"ruta": RUTA_PREVIA})

    assert respuesta.status_code == 200
    assert respuesta.content == b"0123456789abcdef"
    assert respuesta.headers["accept-ranges"] == "bytes"
    assert respuesta.headers["content-type"] == "video/mp4"
    assert respuesta.headers["content-length"] == "16"


def test_extension_permitida_insensible_a_mayusculas(cliente):
    respuesta = cliente.get(
        "/api/medios",
        params={
            "ruta": "cursos/REACT/04-importar-y-exportar/previa/fotograma.JPEG"
        },
    )

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"] == "image/jpeg"


@pytest.mark.parametrize("params", [{}, {"ruta": ""}])
def test_ruta_de_medio_ausente_o_vacia_devuelve_404_sin_detalle(cliente, params):
    respuesta = cliente.get("/api/medios", params=params)

    assert respuesta.status_code == 404
    assert respuesta.content == b""


@pytest.mark.parametrize(
    ("cabecera", "contenido", "content_range"),
    [
        ("bytes=0-9", b"0123456789", "bytes 0-9/16"),
        ("bytes=10-", b"abcdef", "bytes 10-15/16"),
        ("bytes=-4", b"cdef", "bytes 12-15/16"),
    ],
)
def test_medios_range(cliente, cabecera, contenido, content_range):
    respuesta = cliente.get(
        "/api/medios",
        params={"ruta": RUTA_PREVIA},
        headers={"Range": cabecera},
    )

    assert respuesta.status_code == 206
    assert respuesta.content == contenido
    assert respuesta.headers["content-range"] == content_range
    assert respuesta.headers["content-length"] == str(len(contenido))
    assert respuesta.headers["accept-ranges"] == "bytes"


def test_range_fuera_del_archivo(cliente):
    respuesta = cliente.get(
        "/api/medios",
        params={"ruta": RUTA_PREVIA},
        headers={"Range": "bytes=99-100"},
    )

    assert respuesta.status_code == 416
    assert respuesta.content == b""
    assert respuesta.headers["content-range"] == "bytes */16"
