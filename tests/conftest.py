import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from estudio_api.app import crear_app
from estudio_api.config import Config
from tests.ayudas import DATOS_REALES, TOKEN, conexion_vigilada


def _huella_datos() -> dict[str, tuple[int, int]]:
    if not DATOS_REALES.is_dir():
        return {}
    return {
        ruta.name: (ruta.stat().st_size, ruta.stat().st_mtime_ns)
        for ruta in DATOS_REALES.iterdir()
        if ruta.is_file()
    }


@pytest.fixture(autouse=True, scope="session")
def _datos_reales_intactos():
    """Falla la batería si algún test crea, cambia o borra algo en ``datos/``.

    Ahí vive la base de datos real del autor: los tests usan siempre bases
    temporales.
    """
    antes = _huella_datos()
    yield
    assert _huella_datos() == antes, (
        "Un test ha tocado datos/ (la base de datos real del autor)"
    )


@pytest.fixture(autouse=True)
def _sin_abrir_datos_reales(monkeypatch):
    """Falla al instante si un test intenta abrir una base de ``datos/``.

    La guarda de sesión solo detecta el daño al final; esta lo evita: el
    error salta antes de ``sqlite3.connect``, así que la base real ni se abre
    ni se migra.
    """
    monkeypatch.setattr(sqlite3, "connect", conexion_vigilada(sqlite3.connect))


@pytest.fixture
def cfg(tmp_path):
    cursos_dir = tmp_path / "cursos"
    estudio_dir = tmp_path / "estudio"
    cursos_dir.mkdir()
    (estudio_dir / "lecciones").mkdir(parents=True)

    leccion = cursos_dir / "REACT" / "04-importar-y-exportar"
    (leccion / "previa").mkdir(parents=True)
    youtube = leccion / "publicar" / "1-youtube-leccion"
    verticales = leccion / "publicar" / "2-shorts-y-reels"
    opciones = verticales / "portadas-opciones"
    youtube.mkdir(parents=True)
    opciones.mkdir(parents=True)
    (verticales / "anteriores").mkdir()
    (verticales / "descartadas").mkdir()

    (leccion / "previa" / "previa-v1.mp4").write_bytes(b"0123456789abcdef")
    (leccion / "previa" / "previa-v10.mp4").write_bytes(b"previa 10")
    (leccion / "previa" / "previa-v2.mp4").write_bytes(b"previa 2")
    (leccion / "previa" / "fotograma.JPEG").write_bytes(b"imagen")
    (cursos_dir / "REACT" / ".env").write_text(
        "SECRETO=falso",
        encoding="utf-8",
    )
    (youtube / "curso-react-04-ejemplo.mp4").write_bytes(b"leccion")
    (youtube / "miniatura-A-ejemplo.jpg").write_bytes(b"miniatura")
    (verticales / "reel-salida.mp4").write_bytes(b"reel")
    (verticales / "short-2-ejemplo.mp4").write_bytes(b"short")
    (verticales / "portada-short-2-principal.jpg").write_bytes(b"portada")
    (opciones / "portada-short-2-alternativa.jpg").write_bytes(b"opcion")
    (verticales / "reel-salida-anterior.mp4").write_bytes(b"anterior")
    (verticales / "anteriores" / "reel-antiguo.mp4").write_bytes(b"antiguo")
    (verticales / "descartadas" / "short-1-descartado.mp4").write_bytes(b"descartado")

    (cursos_dir / "REACT" / "05-otra").mkdir()
    (cursos_dir / "Asset").mkdir()
    (cursos_dir / "Fondos de pantalla").mkdir()
    (cursos_dir / "Intros (propuestas)").mkdir()
    (cursos_dir / "README.md").write_text("Datos ficticios", encoding="utf-8")
    (cursos_dir / "indice.html").write_text("<p>Falso</p>", encoding="utf-8")

    archivo_fuera = tmp_path.parent / f"{tmp_path.name}-fuera.mp4"
    archivo_fuera.write_bytes(b"contenido fuera de la raiz")
    (cursos_dir / "enlace-fuera.mp4").symlink_to(archivo_fuera)

    guion = {
        "ficha": "React",
        "numero": 4,
        "titulo": "Importar componentes",
        "subtitulo": "Organiza un proyecto de ejemplo",
        "carpeta": "REACT/04-importar-y-exportar",
        "escenas": [
            {
                "id": "E01",
                "modo": "camara",
                "tipo": "camara",
                "titulo": "Presentación",
                "cues": [{"texto": "Texto ficticio de apertura."}],
            },
            {
                "id": "E03",
                "modo": "voz",
                "tipo": "titulo",
                "titulo": "Un concepto inventado",
                "cues": [{"texto": "Explicación ficticia.", "paso": "inicio"}],
            },
            {
                "id": "E04",
                "modo": "animacion",
                "tipo": "codigo",
                "titulo": "Ejemplo visual",
            },
        ],
        "ganchos": [{"texto": "Gancho ficticio."}],
    }
    (estudio_dir / "lecciones" / "react-04.json").write_text(
        json.dumps(guion),
        encoding="utf-8",
    )

    montaje_dir = estudio_dir / "public" / "lecciones" / "react-04"
    montaje_dir.mkdir(parents=True)
    montaje = {
        "fps": 30,
        "duracion": 180,
        "escenas": [
            {"id": "E01", "duracion": 60},
            {"id": "E03", "duracion": 90},
            {"id": "E04", "duracion": 30},
        ],
    }
    (montaje_dir / "montaje.json").write_text(
        json.dumps(montaje),
        encoding="utf-8",
    )

    yield Config(
        cursos_dir=cursos_dir,
        estudio_dir=estudio_dir,
        bd_ruta=tmp_path / "datos" / "estudio.sqlite3",
    )

    archivo_fuera.unlink(missing_ok=True)


@pytest.fixture
def cliente(cfg):
    with TestClient(
        crear_app(cfg),
        base_url="http://127.0.0.1:8000",
    ) as test_client:
        yield test_client


@pytest.fixture
def cliente_con_token(cfg):
    config = cfg.model_copy(update={"token_escritura": TOKEN})
    with TestClient(
        crear_app(config),
        base_url="http://127.0.0.1:8000",
    ) as test_client:
        yield test_client
