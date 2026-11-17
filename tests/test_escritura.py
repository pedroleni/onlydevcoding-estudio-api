import os

import pytest

from estudio_api import escritura


def test_escribir_atomico_copia_una_vez(tmp_path):
    ruta = tmp_path / "publicacion.json"
    copia = tmp_path / "publicacion.json.antes-de-editar"
    ruta.write_text("original", encoding="utf-8")

    escritura.escribir_atomico(ruta, "primera edición")
    escritura.escribir_atomico(ruta, "segunda edición")

    assert ruta.read_text(encoding="utf-8") == "segunda edición"
    assert copia.read_text(encoding="utf-8") == "original"


def test_escribir_atomico_fallo_no_trunca(tmp_path, monkeypatch):
    ruta = tmp_path / "publicacion.json"
    copia = tmp_path / "publicacion.json.antes-de-editar"
    ruta.write_text("original", encoding="utf-8")

    def fallar_replace(origen, destino):
        raise OSError("fallo simulado")

    monkeypatch.setattr(escritura.os, "replace", fallar_replace)

    with pytest.raises(OSError, match="fallo simulado"):
        escritura.escribir_atomico(ruta, "contenido nuevo")

    assert ruta.read_text(encoding="utf-8") == "original"
    assert copia.read_text(encoding="utf-8") == "original"
    assert sorted(archivo.name for archivo in tmp_path.iterdir()) == [
        "publicacion.json",
        "publicacion.json.antes-de-editar",
    ]


def test_escribir_atomico_conserva_permisos(tmp_path):
    ruta = tmp_path / "publicacion.json"
    ruta.write_text("original", encoding="utf-8")
    ruta.chmod(0o644)

    escritura.escribir_atomico(ruta, "nuevo")

    assert ruta.stat().st_mode & 0o777 == 0o644


def test_fallo_de_lectura_no_borra_copia_ajena(tmp_path, monkeypatch):
    ruta = tmp_path / "publicacion.json"
    copia = tmp_path / "publicacion.json.antes-de-editar"
    ruta.write_text("original", encoding="utf-8")
    abrir_real = escritura.Path.open

    def fallar_lectura(path, *args, **kwargs):
        if path == ruta and args == ("rb",):
            copia.write_text("copia ajena", encoding="utf-8")
            raise OSError("fallo de lectura simulado")
        return abrir_real(path, *args, **kwargs)

    monkeypatch.setattr(escritura.Path, "open", fallar_lectura)

    with pytest.raises(OSError, match="fallo de lectura simulado"):
        escritura.escribir_atomico(ruta, "nuevo")

    assert os.stat(copia).st_size > 0
    assert copia.read_text(encoding="utf-8") == "copia ajena"
