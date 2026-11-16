from estudio_api.estado import calcular_estado
from estudio_api.modelos import Avance


def _carpeta_leccion(cfg):
    return cfg.cursos_dir / "REACT" / "04-importar-y-exportar"


def test_voz_parcial(cfg):
    carpeta = _carpeta_leccion(cfg)
    grabaciones = carpeta / "grabaciones"
    grabaciones.mkdir()
    (grabaciones / "E03.wav").write_bytes(b"voz ficticia")
    guion = {
        "escenas": [
            {"id": "E03", "modo": "voz"},
            {"id": "E05", "modo": "voz"},
        ]
    }

    estado = calcular_estado(cfg, "react", 4, carpeta, guion)

    assert estado.voz == Avance(hechas=1, total=2)


def test_camara_desde_ia(cfg):
    carpeta = _carpeta_leccion(cfg)
    videos_ia = carpeta / "grabaciones" / "videos" / "ia"
    videos_ia.mkdir(parents=True)
    (videos_ia / "E01.mov").write_bytes(b"toma ficticia")
    guion = {"escenas": [{"id": "E01", "modo": "camara"}]}

    estado = calcular_estado(cfg, "react", 4, carpeta, guion)

    assert estado.camara == Avance(hechas=1, total=1)


def test_camara_desde_grabaciones_del_estudio(cfg):
    carpeta = _carpeta_leccion(cfg)
    grabaciones = cfg.estudio_dir / "public" / "grabaciones" / "react-04"
    grabaciones.mkdir(parents=True)
    (grabaciones / "E01.mov").write_bytes(b"toma ficticia")
    guion = {"escenas": [{"id": "E01", "modo": "camara"}]}

    estado = calcular_estado(cfg, "react", 4, carpeta, guion)

    assert estado.camara == Avance(hechas=1, total=1)


def test_sin_carpeta(cfg):
    guion = {"escenas": [{"id": "E01", "modo": "camara"}]}

    estado = calcular_estado(cfg, "react", 4, None, guion)

    assert estado.guion is True
    assert estado.video_final is False
    assert estado.previa is None


def test_redes(cfg):
    estado = calcular_estado(cfg, "react", 4, _carpeta_leccion(cfg), None)

    assert list(estado.publicado) == [
        "youtube",
        "instagram",
        "tiktok",
        "linkedin",
    ]
    assert all(publicado is False for publicado in estado.publicado.values())
