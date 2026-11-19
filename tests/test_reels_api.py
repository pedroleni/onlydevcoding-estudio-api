import json

from tests.ayudas import TOKEN

RUTA_REELS = "/api/cursos/react/reels"
RUTA_GRABADO = "/api/cursos/react/lecciones/4/ganchos/{gancho}/grabado"


def _ganchos(cfg, ganchos):
    ruta = cfg.estudio_dir / "lecciones" / "react-04.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["ganchos"] = ganchos
    ruta.write_text(json.dumps(datos), encoding="utf-8")


def _entregados(cfg, entregados):
    carpeta = cfg.estudio_dir / "shorts" / "l4"
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "shorts.json").write_text(
        json.dumps({"leccion": "react-04", "ganchosEntregados": entregados}),
        encoding="utf-8",
    )


GANCHOS = [
    {"id": "S1", "titulo": "Un div de más", "texto": "Un div de más, y se rompe."},
    {"id": "S2", "texto": "Sin título propio."},
    {"titulo": "Sin id", "texto": "No cuenta."},
    {"id": "S3", "titulo": "Sin texto"},
]


def test_reels_lista_los_ganchos_validos_con_su_estado(cfg, cliente):
    _ganchos(cfg, GANCHOS)
    _entregados(cfg, {"S2": "ABCDEF12"})

    cuerpo = cliente.get(RUTA_REELS).json()

    assert cuerpo == {
        "lecciones": [
            {
                "numero": 4,
                "titulo": "Importar componentes",
                "ganchos": [
                    {
                        "id": "S1",
                        "titulo": "Un div de más",
                        "texto": "Un div de más, y se rompe.",
                        "grabado": False,
                        "entregado": False,
                    },
                    {
                        "id": "S2",
                        "titulo": "S2",
                        "texto": "Sin título propio.",
                        "grabado": True,
                        "entregado": True,
                    },
                ],
            }
        ]
    }


def test_reels_omite_lecciones_sin_ganchos_y_404_si_no_hay_curso(cfg, cliente):
    _ganchos(cfg, [])

    assert cliente.get(RUTA_REELS).json() == {"lecciones": []}
    assert cliente.get("/api/cursos/python/reels").status_code == 404


def test_marcar_y_desmarcar_grabado(cfg, cliente_con_token):
    _ganchos(cfg, GANCHOS)
    cabeceras = {"X-Estudio-Token": TOKEN}

    marcado = cliente_con_token.put(
        RUTA_GRABADO.format(gancho="S1"), headers=cabeceras, json={"grabado": True}
    )
    assert marcado.status_code == 200
    s1 = marcado.json()["lecciones"][0]["ganchos"][0]
    assert (s1["id"], s1["grabado"], s1["entregado"]) == ("S1", True, False)
    assert (
        cliente_con_token.get(RUTA_REELS).json()["lecciones"][0]["ganchos"][0][
            "grabado"
        ]
        is True
    )

    desmarcado = cliente_con_token.put(
        RUTA_GRABADO.format(gancho="S1"), headers=cabeceras, json={"grabado": False}
    )
    assert desmarcado.json()["lecciones"][0]["ganchos"][0]["grabado"] is False


def test_marcar_grabado_valida_gancho_cuerpo_y_token(cfg, cliente_con_token):
    _ganchos(cfg, GANCHOS)
    cabeceras = {"X-Estudio-Token": TOKEN}

    assert (
        cliente_con_token.put(
            RUTA_GRABADO.format(gancho="S9"), headers=cabeceras, json={"grabado": True}
        ).status_code
        == 404
    )
    assert (
        cliente_con_token.put(
            "/api/cursos/react/lecciones/9/ganchos/S1/grabado",
            headers=cabeceras,
            json={"grabado": True},
        ).status_code
        == 404
    )
    assert (
        cliente_con_token.put(
            RUTA_GRABADO.format(gancho="S1"),
            headers=cabeceras,
            json={"grabado": True, "otro": 1},
        ).status_code
        == 422
    )
    assert (
        cliente_con_token.put(
            RUTA_GRABADO.format(gancho="S1"), json={"grabado": True}
        ).status_code
        == 401
    )


def _temario(cfg, contenido):
    (cfg.cursos_dir / "REACT" / "TEMARIO.json").write_text(contenido, encoding="utf-8")


def test_temario_lee_las_lecciones_previstas_en_orden(cfg, cliente):
    _temario(
        cfg,
        json.dumps(
            {
                "lecciones": [
                    {"numero": 2, "titulo": "Vite", "modulo": "Primeros pasos"},
                    {"numero": 1, "titulo": " ¿Qué es React? ", "modulo": " "},
                    {"numero": 1, "titulo": "Duplicada"},
                    {"numero": 0, "titulo": "Fuera de rango"},
                    {"numero": True, "titulo": "Booleano"},
                    {"numero": 3, "titulo": ""},
                    "basura",
                ]
            }
        ),
    )

    assert cliente.get("/api/cursos/react/temario").json() == {
        "lecciones": [
            {"numero": 1, "titulo": "¿Qué es React?", "modulo": None},
            {"numero": 2, "titulo": "Vite", "modulo": "Primeros pasos"},
        ]
    }


def test_temario_vacio_si_no_hay_archivo_o_esta_roto(cfg, cliente):
    assert cliente.get("/api/cursos/react/temario").json() == {"lecciones": []}
    _temario(cfg, "{no es json")
    assert cliente.get("/api/cursos/react/temario").json() == {"lecciones": []}
    assert cliente.get("/api/cursos/python/temario").status_code == 404
