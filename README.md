# API local del estudio de OnlyDevCoding

API FastAPI local para consultar los cursos y el material del estudio de
OnlyDevCoding. En la fase 1 solo lee los directorios configurados y escucha en
la interfaz local.

## Configuración

Copia el archivo de ejemplo y adapta las dos rutas a tus directorios locales:

```sh
cp .env.example .env
```

La web permitida se puede cambiar mediante `ORIGEN_WEB`; por defecto es
`http://localhost:3000`.

## Arranque

```sh
uv run uvicorn estudio_api.app:app --host 127.0.0.1 --port 8000
```
