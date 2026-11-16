from typing import Literal

from pydantic import BaseModel, Field


class Avance(BaseModel):
    hechas: int = 0
    total: int = 0


class EstadoLeccion(BaseModel):
    guion: bool = False
    voz: Avance = Field(default_factory=Avance)
    camara: Avance = Field(default_factory=Avance)
    video_final: bool = False
    miniatura: str | None = None
    previa: str | None = None
    publicado: dict[str, bool] = Field(default_factory=dict)


class Escena(BaseModel):
    id: str
    modo: Literal["voz", "camara", "animacion"]
    tipo: str
    titulo: str
    textos: list[str] = Field(default_factory=list)
    inicio_s: float | None = None
    duracion_s: float | None = None


class Pieza(BaseModel):
    id: str
    tipo: Literal["leccion", "reel", "short"]
    titulo: str
    video: str | None = None
    portadas: list[str] = Field(default_factory=list)


class LeccionResumen(BaseModel):
    curso: str
    numero: int
    slug: str
    titulo: str
    estado: EstadoLeccion = Field(default_factory=EstadoLeccion)


class Leccion(LeccionResumen):
    subtitulo: str = ""
    escenas: list[Escena] = Field(default_factory=list)
    piezas: list[Pieza] = Field(default_factory=list)
    previas: list[str] = Field(default_factory=list)
    duracion_s: float | None = None


class Curso(BaseModel):
    id: str
    nombre: str
    carpeta: str
    lecciones: int
