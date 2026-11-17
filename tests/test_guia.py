from estudio_api.guia import generar_guia
from estudio_api.publicacion import Publicacion


def test_generar_guia_conserva_textos_y_adapta_la_valla():
    publicacion = Publicacion.model_validate(
        {
            "version": 1,
            "piezas": {
                "leccion": {
                    "titulo": "Lección ficticia",
                    "video": "1-youtube-leccion/video-ficticio.mp4",
                    "fecha_propuesta": "2026-11-18T20:00",
                    "redes": {
                        "youtube": {
                            "titulos": ["Título recomendado", "Alternativa"],
                            "descripcion": (
                                'Primera línea con ``` y "comillas".\n\n'
                                "Segunda línea con emoji 🚀"
                            ),
                            "etiquetas": ["curso ficticio", "ejemplo"],
                            "comentario_fijado": "Comentario de prueba",
                            "ajustes": ["Visibilidad: privado"],
                            "notas": "Nota de prueba.",
                        }
                    },
                }
            },
            "despues_de_publicar": ["Comprobar el resultado ficticio"],
        }
    )

    guia = generar_guia(
        publicacion,
        "Curso ficticio",
        4,
        {"leccion": "1-youtube-leccion/miniatura-ficticia.jpg"},
    )

    assert guia.startswith("# Publicar la lección 4 de Curso ficticio\n")
    assert "`1-youtube-leccion/video-ficticio.mp4`" in guia
    assert "`1-youtube-leccion/miniatura-ficticia.jpg`" in guia
    assert "2026-11-18T20:00" in guia
    assert "Título recomendado (recomendado)" in guia
    assert '````\nPrimera línea con ``` y "comillas".\n\n' in guia
    assert "Segunda línea con emoji 🚀\n````" in guia
    assert "- Visibilidad: privado" in guia
    assert "Nota de prueba." in guia
    assert "## Después de publicar" in guia


def test_generar_guia_ordena_las_redes():
    publicacion = Publicacion.model_validate(
        {
            "version": 1,
            "piezas": {
                "leccion": {
                    "redes": {
                        "linkedin": {"texto": "LinkedIn"},
                        "tiktok": {"texto": "TikTok"},
                        "instagram": {"texto": "Instagram"},
                        "youtube": {"descripcion": "YouTube"},
                    }
                }
            },
        }
    )

    guia = generar_guia(publicacion, "Curso ficticio", 4, {})

    posiciones = [
        guia.index("### YouTube"),
        guia.index("### Instagram"),
        guia.index("### TikTok"),
        guia.index("### LinkedIn"),
    ]
    assert posiciones == sorted(posiciones)


def test_generar_guia_no_incluye_rutas_absolutas_ni_recorridos():
    publicacion = Publicacion.model_validate(
        {
            "version": 1,
            "piezas": {
                "leccion": {
                    "video": "/ruta/ficticia/video.mp4",
                    "redes": {
                        "linkedin": {"video": "../fuera/video.mp4"},
                    },
                }
            },
        }
    )

    guia = generar_guia(
        publicacion,
        "Curso ficticio",
        4,
        {"leccion": "/ruta/ficticia/portada.jpg"},
    )

    assert "/ruta/ficticia" not in guia
    assert "../fuera" not in guia


def test_generar_guia_encierra_las_notas_y_no_rompe_secciones_posteriores():
    publicacion = Publicacion.model_validate(
        {
            "version": 1,
            "piezas": {
                "leccion": {
                    "redes": {
                        "youtube": {
                            "notas": "Inicio de una valla sin cerrar:\n```\ncontenido",
                        }
                    }
                }
            },
            "despues_de_publicar": ["Comprobar el resultado"],
        }
    )

    guia = generar_guia(publicacion, "Curso ficticio", 4, {})

    assert (
        "#### Notas\n\n````\nInicio de una valla sin cerrar:\n```\ncontenido\n````"
        in guia
    )
    assert guia.index("#### Notas") < guia.index("## Después de publicar")
    assert "- Comprobar el resultado" in guia


def test_generar_guia_escapa_inicios_que_abren_markdown():
    publicacion = Publicacion.model_validate(
        {
            "version": 1,
            "piezas": {
                "leccion": {
                    "titulo": "# Pieza ficticia",
                    "fecha_propuesta": "> mañana",
                    "redes": {
                        "youtube": {
                            "titulos": ["```título ficticio"],
                            "ajustes": ["- ajuste ficticio", "1. otro ajuste"],
                        }
                    },
                }
            },
            "despues_de_publicar": ["| comprobar"],
        }
    )

    guia = generar_guia(publicacion, "# Curso ficticio", 4, {})

    assert guia.startswith("# Publicar la lección 4 de \\# Curso ficticio\n")
    assert "## \\# Pieza ficticia" in guia
    assert "- Fecha propuesta: \\> mañana" in guia
    assert "\\```título ficticio (recomendado)" in guia
    assert "- \\- ajuste ficticio" in guia
    assert "- 1\\. otro ajuste" in guia
    assert "- \\| comprobar" in guia
    assert "\n```título ficticio (recomendado)\n" not in guia
