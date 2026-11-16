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
    # Sin CORP: Chromium bloquea same-site entre 127.0.0.1:3000 y 127.0.0.1:8000.
    # La protección contra otras webs es el rechazo de Sec-Fetch-Site: cross-site.
    assert "cross-origin-resource-policy" not in respuesta.headers


def test_medio_rechaza_sec_fetch_site_cross_site(cliente):
    respuesta = cliente.get(
        "/api/medios",
        params={"ruta": RUTA_PREVIA},
        headers={"Sec-Fetch-Site": "cross-site"},
    )

    assert respuesta.status_code == 403


def test_medio_acepta_sec_fetch_site_same_site(cliente):
    respuesta = cliente.get(
        "/api/medios",
        params={"ruta": RUTA_PREVIA},
        headers={"Sec-Fetch-Site": "same-site"},
    )

    assert respuesta.status_code == 200


def test_extension_permitida_insensible_a_mayusculas(cliente):
    respuesta = cliente.get(
        "/api/medios",
        params={"ruta": "cursos/REACT/04-importar-y-exportar/previa/fotograma.JPEG"},
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


def test_range_con_inicio_mayor_que_fin_devuelve_416(cliente):
    respuesta = cliente.get(
        "/api/medios",
        params={"ruta": RUTA_PREVIA},
        headers={"Range": "bytes=10-9"},
    )

    assert respuesta.status_code == 416
    assert respuesta.content == b""
    assert respuesta.headers["content-range"] == "bytes */16"


def test_range_con_numero_excesivamente_largo_es_invalido(cliente):
    respuesta = cliente.get(
        "/api/medios",
        params={"ruta": RUTA_PREVIA},
        headers={"Range": f"bytes={'1' * 4301}-"},
    )

    assert respuesta.status_code == 416
    assert respuesta.content == b""
    assert respuesta.headers["content-range"] == "bytes */16"


@pytest.mark.parametrize(
    "cabecera",
    [
        "items=0-9",
        "bytes=0-1,2-3",
        "",
        " bytes=0-9",
        "bytes =0-9",
        "bytes=0 -9",
    ],
)
def test_range_desconocido_o_malformado_se_ignora(cliente, cabecera):
    respuesta = cliente.get(
        "/api/medios",
        params={"ruta": RUTA_PREVIA},
        headers={"Range": cabecera},
    )

    assert respuesta.status_code == 200
    assert respuesta.content == b"0123456789abcdef"
    assert respuesta.headers["content-length"] == "16"


def test_unidad_bytes_no_distingue_mayusculas(cliente):
    respuesta = cliente.get(
        "/api/medios",
        params={"ruta": RUTA_PREVIA},
        headers={"Range": "BYTES=0-3"},
    )

    assert respuesta.status_code == 206
    assert respuesta.content == b"0123"
    assert respuesta.headers["content-range"] == "bytes 0-3/16"


def test_directorio_enlazado_a_mitad_de_ruta_que_sale_de_raiz_devuelve_404(
    cliente,
    cfg,
    tmp_path,
):
    directorio_fuera = tmp_path / "fuera"
    directorio_fuera.mkdir()
    (directorio_fuera / "secreto.mp4").write_bytes(b"secreto")
    (cfg.cursos_dir / "REACT" / "enlace-directorio").symlink_to(
        directorio_fuera,
        target_is_directory=True,
    )

    respuesta = cliente.get(
        "/api/medios",
        params={"ruta": "cursos/REACT/enlace-directorio/secreto.mp4"},
    )

    assert respuesta.status_code == 404


def test_traversal_codificado_en_query_cruda_devuelve_404(cliente):
    respuesta = cliente.get("/api/medios?ruta=cursos/%2e%2e/secreto.mp4")

    assert respuesta.status_code == 404


@pytest.mark.parametrize(
    "ruta",
    [
        r"cursos\..\..",
        "cursos/REACT/x.mp4\x00.json",
        "estudio/lecciones/react-04.JSON",
    ],
)
def test_rutas_malformadas_o_extension_prohibida_devuelven_404(cliente, ruta):
    respuesta = cliente.get("/api/medios", params={"ruta": ruta})

    assert respuesta.status_code == 404


def test_enlace_mp4_a_extension_prohibida_dentro_de_raiz_devuelve_404(cliente, cfg):
    archivo_privado = cfg.cursos_dir / "REACT" / "datos.json"
    archivo_privado.write_text("{}", encoding="utf-8")
    (cfg.cursos_dir / "REACT" / "camuflado.mp4").symlink_to(archivo_privado)

    respuesta = cliente.get(
        "/api/medios",
        params={"ruta": "cursos/REACT/camuflado.mp4"},
    )

    assert respuesta.status_code == 404
