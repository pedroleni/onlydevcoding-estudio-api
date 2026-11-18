from datetime import datetime
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, model_validator

HOSTS_PUBLICACION = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "youtu.be",
        "instagram.com",
        "www.instagram.com",
        "tiktok.com",
        "www.tiktok.com",
        "linkedin.com",
        "www.linkedin.com",
    }
)


class EstadoRed(BaseModel):
    estado: Literal["pendiente", "programado", "publicado"]
    fecha: datetime | None = None
    url: str | None = None

    @model_validator(mode="after")
    def validar_estado(self) -> Self:
        if self.url is not None:
            if any(
                caracter.isspace() or ord(caracter) < 32 or ord(caracter) == 127
                for caracter in self.url
            ):
                raise ValueError("La URL de publicación no es válida")
            try:
                url = urlsplit(self.url)
                puerto = url.port
            except ValueError as error:
                raise ValueError("La URL de publicación no es válida") from error
            if (
                url.scheme != "https"
                or url.hostname not in HOSTS_PUBLICACION
                or url.username is not None
                or url.password is not None
                or puerto is not None
                or url.netloc.endswith(":")
            ):
                raise ValueError("La URL de publicación no está permitida")

        if self.estado == "pendiente":
            if self.fecha is not None or self.url is not None:
                raise ValueError("Un estado pendiente no lleva fecha ni URL")
            return self

        if self.estado == "programado" and self.fecha is None:
            raise ValueError("Un estado programado exige fecha")

        if self.estado == "publicado" and self.fecha is None:
            self.fecha = datetime.now().astimezone()

        if self.fecha is not None and self.fecha.tzinfo is None:
            self.fecha = self.fecha.astimezone()

        return self


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


class EstadoMontaje(BaseModel):
    estado: Literal[
        "sin_montaje",
        "voz_sin_alinear",
        "guion_cambiado",
        "al_dia",
    ]
    sin_alinear: list[str] = Field(default_factory=list)


class Leccion(LeccionResumen):
    subtitulo: str = ""
    escenas: list[Escena] = Field(default_factory=list)
    piezas: list[Pieza] = Field(default_factory=list)
    previas: list[str] = Field(default_factory=list)
    duracion_s: float | None = None
    montaje: EstadoMontaje | None = None


class Curso(BaseModel):
    id: str
    nombre: str
    carpeta: str | None
    lecciones: int
    en_disco: bool
