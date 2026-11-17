from pathlib import Path

from estudio_api.estado import calcular_estado, publicado_por_red
from estudio_api.modelos import Avance, EstadoRed
from estudio_api.publicacion import Publicacion


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


def test_ids_de_escena_maliciosos_no_escapan_ni_cuentan(cfg, monkeypatch):
    carpeta = _carpeta_leccion(cfg)
    ids = ["../x", "/etc/passwd", "a/../../b", "E0\x001"]
    guion = {
        "escenas": [
            *({"id": identificador, "modo": "voz"} for identificador in ids),
            *({"id": identificador, "modo": "camara"} for identificador in ids),
        ]
    }

    # Señuelos en destinos a los que llegarían los recorridos relativos.
    (carpeta / "x.wav").write_bytes(b"fuera de grabaciones")
    (carpeta / "b.wav").write_bytes(b"fuera de grabaciones")
    grabaciones_estudio = cfg.estudio_dir / "public" / "grabaciones"
    grabaciones_estudio.mkdir(parents=True)
    (grabaciones_estudio / "x.mov").write_bytes(b"fuera de la toma")
    (grabaciones_estudio / "b.mov").write_bytes(b"fuera de la toma")

    is_file_original = Path.is_file
    raices = (cfg.cursos_dir.resolve(), cfg.estudio_dir.resolve())

    def is_file_confinado(ruta):
        resuelta = ruta.resolve()
        assert any(resuelta.is_relative_to(raiz) for raiz in raices)
        return is_file_original(ruta)

    monkeypatch.setattr(Path, "is_file", is_file_confinado)

    estado = calcular_estado(cfg, "react", 4, carpeta, guion)

    assert estado.voz == Avance(hechas=0, total=4)
    assert estado.camara == Avance(hechas=0, total=4)


def test_grabacion_de_voz_en_enlace_fuera_no_cuenta(cfg, tmp_path):
    carpeta = _carpeta_leccion(cfg)
    grabaciones = carpeta / "grabaciones"
    grabaciones.mkdir()
    archivo_fuera = tmp_path.parent / f"{tmp_path.name}-fuera.wav"
    archivo_fuera.write_bytes(b"voz fuera de la raiz")
    (grabaciones / "E03.wav").symlink_to(archivo_fuera)
    guion = {"escenas": [{"id": "E03", "modo": "voz"}]}

    estado = calcular_estado(cfg, "react", 4, carpeta, guion)

    assert estado.voz == Avance(hechas=0, total=1)


def test_toma_de_camara_no_escapa_con_curso_manipulado(cfg):
    carpeta = _carpeta_leccion(cfg)
    destino_si_escapara = cfg.estudio_dir / "public" / "x-04"
    destino_si_escapara.mkdir(parents=True)
    (destino_si_escapara / "E01.mov").write_bytes(b"toma fuera")
    guion = {"escenas": [{"id": "E01", "modo": "camara"}]}

    estado = calcular_estado(cfg, "../x", 4, carpeta, guion)

    assert estado.camara == Avance(hechas=0, total=1)


def test_toma_de_camara_no_cuenta_con_numero_manipulado(cfg):
    carpeta = _carpeta_leccion(cfg)
    grabaciones = cfg.estudio_dir / "public" / "grabaciones" / "react-00"
    grabaciones.mkdir(parents=True)
    (grabaciones / "E01.mov").write_bytes(b"toma fuera del rango")
    guion = {"escenas": [{"id": "E01", "modo": "camara"}]}

    estado = calcular_estado(cfg, "react", 0, carpeta, guion)

    assert estado.camara == Avance(hechas=0, total=1)


def test_sin_carpeta(cfg):
    guion = {"escenas": [{"id": "E01", "modo": "camara"}]}

    estado = calcular_estado(cfg, "react", 4, None, guion)

    assert estado.guion is True
    assert estado.video_final is False
    assert estado.previa is None


def test_video_final_sin_mp4_es_falso(cfg):
    carpeta = _carpeta_leccion(cfg)
    video = carpeta / "publicar" / "1-youtube-leccion" / "curso-react-04-ejemplo.mp4"
    video.unlink()

    estado = calcular_estado(cfg, "react", 4, carpeta, None)

    assert estado.video_final is False


def test_directorio_con_extension_mp4_no_es_video_final(cfg):
    carpeta = _carpeta_leccion(cfg)
    youtube = carpeta / "publicar" / "1-youtube-leccion"
    (youtube / "curso-react-04-ejemplo.mp4").unlink()
    (youtube / "x.mp4").mkdir()

    estado = calcular_estado(cfg, "react", 4, carpeta, None)

    assert estado.video_final is False


def test_previa_elige_la_version_numericamente_mas_alta(cfg):
    carpeta = _carpeta_leccion(cfg)

    estado = calcular_estado(cfg, "react", 4, carpeta, None)

    assert estado.previa is not None
    assert estado.previa.endswith("/previa/previa-v10.mp4")


def test_redes(cfg):
    estado = calcular_estado(cfg, "react", 4, _carpeta_leccion(cfg), None)

    assert list(estado.publicado) == [
        "youtube",
        "instagram",
        "tiktok",
        "linkedin",
    ]
    assert all(publicado is False for publicado in estado.publicado.values())


def test_publicado_por_red_sin_json_preve_solo_leccion_en_youtube():
    resultado = publicado_por_red(
        None,
        {("leccion", "youtube"): EstadoRed(estado="publicado")},
    )

    assert resultado == {
        "youtube": True,
        "instagram": False,
        "tiktok": False,
        "linkedin": False,
    }


def test_publicado_por_red_exige_todas_las_piezas_previstas():
    publicacion = Publicacion.model_validate(
        {
            "version": 1,
            "piezas": {
                "leccion": {
                    "redes": {
                        "youtube": {"descripcion": "Texto ficticio"},
                        "instagram": {"texto": "Texto ficticio"},
                    }
                },
                "reel-salida": {
                    "redes": {"instagram": {"texto": "Otro texto ficticio"}}
                },
            },
        }
    )
    resultado = publicado_por_red(
        publicacion,
        {
            ("leccion", "youtube"): EstadoRed(estado="publicado"),
            ("leccion", "instagram"): EstadoRed(estado="publicado"),
        },
    )

    assert resultado == {
        "youtube": True,
        "instagram": False,
        "tiktok": False,
        "linkedin": False,
    }


def test_publicado_por_red_no_cuenta_redes_vacias():
    publicacion = Publicacion.model_validate(
        {
            "version": 1,
            "piezas": {"leccion": {"redes": {"tiktok": {}}}},
        }
    )

    resultado = publicado_por_red(
        publicacion,
        {("leccion", "tiktok"): EstadoRed(estado="publicado")},
    )

    assert resultado["tiktok"] is False
