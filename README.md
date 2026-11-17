# API local del estudio de OnlyDevCoding

API FastAPI local para consultar y preparar la publicación de los cursos y el
material del estudio de OnlyDevCoding. Solo escucha en la interfaz local.

## Configuración

Copia el archivo de ejemplo, adapta las dos rutas a tus directorios locales y
genera un token de escritura con el comando indicado en el propio archivo:

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

Toda petición distinta de `GET`, `HEAD` u `OPTIONS` necesita que
`X-Estudio-Token` coincida con `ESTUDIO_TOKEN`. Sin token configurado, las
escrituras quedan desactivadas; el token debe tener al menos 32 caracteres.
Los WebSocket también exigen el token. Además, cada escritura debe declarar un
único `Content-Length` válido, no puede usar `Transfer-Encoding` ni superar
256 KB declarados o reales. CORS continúa permitiendo solo `GET`, para que el
token permanezca en el servidor de la web.

`BD_RUTA` define la base SQLite local y, por defecto, vale
`datos/estudio.sqlite3`. La API solo puede escribir los archivos de publicación
previstos dentro de cada lección; los reemplaza de forma atómica y conserva el
contenido original en `<archivo>.antes-de-editar` antes de la primera edición.

## Arranque

```sh
uv run uvicorn --factory estudio_api.app:crear_app_desde_entorno \
  --host 127.0.0.1 --port 8000
```
