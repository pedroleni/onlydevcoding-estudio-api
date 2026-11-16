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
`http://127.0.0.1:3000`. La web y la API deben abrirse ambas mediante
`127.0.0.1` para pertenecer al mismo sitio, y la API rechaza las peticiones
que el navegador marque con `Sec-Fetch-Site: cross-site`: una web de otro sitio
no puede incrustar ni pedir los medios. Una página servida en `127.0.0.1` en otro
puerto sí es del mismo sitio; por eso no conviene tener otros servidores web
locales no confiables abiertos a la vez. No se usa `Cross-Origin-Resource-Policy:
same-site` porque Chromium bloquea con ella los medios entre
`127.0.0.1:3000` y `127.0.0.1:8000`.

## Arranque

```sh
uv run uvicorn --factory estudio_api.app:crear_app_desde_entorno \
  --host 127.0.0.1 --port 8000
```
