# Estudio OnlyDevCoding · Fase 2 (Publicar) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** La pestaña Publicar de cada lección: elegir la portada de cada pieza, ver y copiar sus textos por red, editarlos, programar y marcar qué está publicado y dónde. Las guías `PUBLICAR-leccion-N.md|html` del móvil se regeneran solas.

**Architecture:**
- **Textos:** los guarda `publicar/publicacion.json` en la carpeta de cada lección. Lo escribe Claude y la app lo lee y lo edita.
- **Decisiones del autor:** la portada elegida y el estado por pieza y red se guardan en una base SQLite local de la API.
- **Escrituras:** es la primera fase que escribe. Las escrituras van del navegador a una Server Action de Next, y de ahí a la API, con un token secreto en `X-Estudio-Token`. El navegador nunca llama a la API para escribir, y el token nunca sale del servidor.

**Tech Stack:**
- **API:** Python 3.14, uv, FastAPI, Pydantic v2, `sqlite3` de la biblioteca estándar, pytest, ruff.
- **Web:** Next.js 16 (App Router, `cacheComponents`, Server Actions), TypeScript, Tailwind, Vitest y Testing Library.
- **Verificación visual:** Playwright, la hace Claude.

**Spec:** `docs/specs/2026-11-16-estudio-onlydevcoding-design.md` (secciones «Decisiones del autor → Publicar», «Datos», «Seguridad»).

**Base:** la fase 1, integrada en `main`. Hay que leer el registro `.superpowers/sdd/2026-11-16-estudio-onlydevcoding-fase-1/progress.md` (Rulings y minors diferidos). Rama `feat/fase-2` en cada repo.

## Contexto de ejecución

Igual que en la fase 1:
- **Codex** implementa (sin red y sin escribir en `.git`). Si no tiene cuota, implementa Claude.
- **Claude** instala dependencias, hace los commits (sin `Co-Authored-By` ni «Generated with»), arranca los servidores, verifica con Playwright y encarga las revisiones.

## Global Constraints

- Las de la fase 1 siguen en vigor: local, `127.0.0.1`, Host/Origin/`Sec-Fetch-Site`, rutas dentro de las raíces, nada privado en los repos, castellano de España, tema oscuro y redes en el orden YouTube, Instagram, TikTok, LinkedIn.
- **Toda escritura** (método distinto de `GET`/`HEAD`/`OPTIONS`) exige la cabecera `X-Estudio-Token` igual a `ESTUDIO_TOKEN`, comparada con `hmac.compare_digest`.
  - Sin la cabecera, o con un valor distinto: 401.
  - Si la API no tiene `ESTUDIO_TOKEN` configurado: 503 «Escrituras desactivadas: falta ESTUDIO_TOKEN».
  - Cuerpo de más de 256 KB: 413.
  - CORS sigue permitiendo solo `GET`.
- `ESTUDIO_TOKEN` vive solo en los `.env` de la API y de la web, que no se versionan. `.env.example` lleva un marcador y la orden para generarlo: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.
- **Qué puede escribir la API en disco.** Solo `publicar/publicacion.json`, `publicar/PUBLICAR-leccion-N.md` y `publicar/PUBLICAR-leccion-N.html` de la carpeta de cada lección. Nada más en `CURSOS_DIR` y nada en `ESTUDIO_DIR`.
  - **Cómo escribe:** siempre de forma atómica (temporal en la misma carpeta y después `os.replace`).
  - **Copia previa:** antes de la primera edición de cada archivo, guarda una copia `<archivo>.antes-de-editar`. Si la copia ya existe, no se toca. Es la misma convención que la página de grabación.
- **Base de datos:** `BD_RUTA` en `.env`, con `datos/estudio.sqlite3` por defecto (relativo al directorio de arranque). `datos/` va en `.gitignore`.
- **Ids de pieza:** `^(leccion|reel-salida(-[1-9]\d*)?|short-[1-9]\d*)$`. **Redes:** `youtube`, `instagram`, `tiktok`, `linkedin`. **Estados:** `pendiente`, `programado`, `publicado`.
- **URL de lo publicado:** opcional, y solo `https` con host `youtube.com`, `www.youtube.com`, `youtu.be`, `instagram.com`, `www.instagram.com`, `tiktok.com`, `www.tiktok.com`, `linkedin.com` o `www.linkedin.com`.
- **Límites de texto** (los de cada plataforma), que la API valida (422) y la web muestra con contadores:
  - Título de YouTube: 100.
  - Descripción de YouTube: 5000.
  - Etiquetas de YouTube unidas con `, `: 500.
  - Texto de Instagram y de TikTok: 2200.
  - Texto de LinkedIn: 3000.
  - Comentario fijado: 10000.
  - Ajustes y «después de publicar»: hasta 30 líneas de 300 cada una.

## Formato de `publicar/publicacion.json`

Las rutas son relativas a `publicar/`. Un campo que no aplica se omite o va a `null`.

```json
{
  "version": 1,
  "piezas": {
    "leccion": {
      "titulo": "Lección completa",
      "video": "1-youtube-leccion/curso-demo-04-ejemplo.mp4",
      "duracion": "7:30",
      "portadas": ["1-youtube-leccion/miniatura-A.jpg", "1-youtube-leccion/miniatura-B.jpg"],
      "fecha_propuesta": "2026-11-16T20:00",
      "redes": {
        "youtube": {
          "titulos": ["Recomendado primero", "Alternativa"],
          "descripcion": "…",
          "etiquetas": ["react", "curso de react"],
          "texto": null,
          "comentario_fijado": "…",
          "ajustes": ["Lista: Curso de demostración", "Idioma: Español"],
          "video": null,
          "notas": "Vídeo relacionado: la lección anterior"
        },
        "linkedin": { "texto": "…", "video": "4-linkedin/linkedin-ejemplo.mp4" }
      }
    },
    "reel-salida": { "titulo": "Resumen en cinco pasos", "video": "2-shorts-y-reels/reel-….mp4", "portadas": ["2-shorts-y-reels/portada-reel-….jpg"], "redes": { "youtube": {}, "instagram": {}, "tiktok": {} } }
  },
  "despues_de_publicar": ["Lección anterior: actualiza su pantalla final"],
  "notas": null
}
```

## Review Focus

1. **`publicacion.json` escrito a mano con un error de sintaxis o un campo raro.** La pestaña muestra «No se ha podido leer publicacion.json» y el resto de la lección funciona. Test en la tarea 3.
2. **Escritura sin token, con un token incorrecto o lanzada desde el navegador directamente** (`fetch` con `PUT` desde otra página). Responde 401, o el navegador la bloquea por CORS, y no se escribe nada. Tests en la tarea 1.
3. **Una descripción que contiene `` ``` ``, emojis, comillas o líneas en blanco.** Se guarda exacta en el JSON, y la guía regenerada la envuelve en una valla más larga (````` ```` `````), así que el `.md` sigue siendo válido. Test en la tarea 5.
4. **La portada elegida se borra o se renombra en disco.** La vista no la ofrece ni la da por elegida (`portada_elegida: null`). Test en la tarea 4.
5. **Un guardado que falla a mitad.** `publicacion.json` nunca queda truncado y existe la copia `.antes-de-editar`. Test en la tarea 1 (`escribir_atomico`).

---

## Repo de la API (`onlydevcoding-estudio-api`)

### Tarea 1: Escrituras protegidas y escritura atómica

**Files:**
- Modify: `estudio_api/config.py` (`token_escritura: str | None`, desde `ESTUDIO_TOKEN`; `bd_ruta: Path`, desde `BD_RUTA`), `estudio_api/seguridad.py`, `.env.example`, `.gitignore` (`datos/`), `README.md`, `.claude/agents/security-local-api.md`, `security/security-review-instructions.md`
- Create: `estudio_api/escritura.py`
- Test: `tests/test_escritura.py`, `tests/test_app.py`

**Interfaces:**
- Produces:
  - `escribir_atomico(ruta: Path, contenido: str) -> None`: copia `.antes-de-editar` si el archivo existe y aún no hay copia, escribe en un temporal de la misma carpeta y hace `os.replace`.
  - Middleware: el token se exige a todos los métodos de escritura y en todas las rutas.

- [ ] **Step 1: Tests que fallan:**
```python
def test_put_sin_token_401(cliente_con_token): assert cliente_con_token.put("/api/salud").status_code == 401
def test_put_token_malo_401(cliente_con_token): assert cliente_con_token.put("/api/salud", headers={"X-Estudio-Token": "otro"}).status_code == 401
def test_put_sin_configurar_503(cliente): assert cliente.put("/api/salud", headers={"X-Estudio-Token": "x"}).status_code == 503
def test_put_token_bueno_pasa(cliente_con_token): assert cliente_con_token.put("/api/salud", headers={"X-Estudio-Token": TOKEN}).status_code == 405  # pasa el cortafuegos; la ruta solo admite GET
def test_cuerpo_grande_413(cliente_con_token): assert cliente_con_token.put("/api/salud", headers={"X-Estudio-Token": TOKEN}, content=b"x" * (256 * 1024 + 1)).status_code == 413
def test_cors_no_permite_put(cliente_con_token): r = cliente_con_token.options("/api/salud", headers={"Origin": "http://127.0.0.1:3000", "Access-Control-Request-Method": "PUT"}); assert "PUT" not in r.headers.get("access-control-allow-methods", "")
def test_escribir_atomico_copia_una_vez(tmp_path): ...  # dos escrituras → .antes-de-editar conserva el contenido ORIGINAL
def test_escribir_atomico_fallo_no_trunca(tmp_path, monkeypatch): ...  # os.replace lanza OSError → el archivo conserva su contenido y no quedan temporales
```
- [ ] **Step 2:** `uv run pytest -q` → FAIL. **Step 3:** Implementar y documentar en README y en los documentos de seguridad. **Step 4:** PASS, ruff y escáneres en verde.
- [ ] **Step 5: Commit** `Escrituras protegidas con token y escritura atómica`.

### Tarea 2: Base de datos de decisiones

**Files:**
- Create: `estudio_api/decisiones.py`
- Modify: `estudio_api/modelos.py`
- Test: `tests/test_decisiones.py`

**Interfaces:**
- Produces:
  - `class EstadoRed(BaseModel): estado: Literal["pendiente","programado","publicado"]; fecha: datetime | None = None; url: str | None = None`. Validador: `programado` exige `fecha`. `publicado` sin fecha toma la de ahora. `url` debe cumplir la regla de Global Constraints. `pendiente` no lleva fecha ni URL.
  - `abrir_bd(ruta: Path) -> sqlite3.Connection`: crea la carpeta, el esquema (`PRAGMA user_version = 1`) y las tablas `portada_elegida(curso, numero, pieza, ruta, PK(curso,numero,pieza))` y `estado_red(curso, numero, pieza, red, estado, fecha, url, PK(curso,numero,pieza,red))`.
  - `elegir_portada(bd, curso: str, numero: int, pieza: str, ruta: str) -> None` y `portadas_elegidas(bd, curso, numero) -> dict[str, str]`.
  - `fijar_estado(bd, curso, numero, pieza, red, estado: EstadoRed) -> None`. `pendiente` borra la fila.
  - `estados(bd, curso, numero) -> dict[tuple[str, str], EstadoRed]`.
  - Todas las consultas usan parámetros `?`, nunca formateo de cadenas.

- [ ] **Step 1: Tests que fallan:**
  - Volver a elegir portada sustituye la anterior.
  - Programado, después publicado y después pendiente: la fila desaparece.
  - Programado sin fecha da `ValidationError`.
  - `javascript:alert(1)`, `http://youtube.com/x` y `https://evil.example/x` dan `ValidationError`; `https://youtu.be/abc` es válida.
  - Abrir la base dos veces conserva los datos.
  - Un nombre de pieza con comillas se guarda tal cual, porque las consultas van parametrizadas.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS.
- [ ] **Step 5: Commit** `Base de datos local de portadas y estados de publicación`.

### Tarea 3: Lectura de `publicacion.json`

**Files:**
- Create: `estudio_api/publicacion.py`
- Test: `tests/test_publicacion.py`

**Interfaces:**
- Produces:
  - Modelos con `extra="forbid"`:
    - `TextosRed(titulos: list[str] = [], descripcion: str | None, etiquetas: list[str] = [], texto: str | None, comentario_fijado: str | None, ajustes: list[str] = [], video: str | None, notas: str | None)`. Los límites de Global Constraints se validan según la red, en `validar_textos(red, textos)`.
    - `PiezaPublicacion(titulo: str | None, video: str | None, duracion: str | None, portadas: list[str] = [], fecha_propuesta: str | None, redes: dict[Red, TextosRed] = {})`.
    - `Publicacion(version: Literal[1], piezas: dict[str, PiezaPublicacion], despues_de_publicar: list[str] = [], notas: str | None)`.
  - `class LecturaPublicacion(BaseModel): publicacion: Publicacion | None; error: str | None`.
  - `leer_publicacion(config, carpeta: Path | None) -> LecturaPublicacion`:
    - Sin carpeta o sin archivo: `(None, None)`.
    - JSON inválido, de más de 5 MB o que no valida: `(None, "No se ha podido leer publicacion.json")`.
    - Las rutas de `video` y `portadas` que no resuelven a un archivo dentro de `carpeta/publicar` con extensión de medio se descartan.
    - Un id de pieza que no cumple el patrón invalida el archivo.
  - `ruta_publica_publicar(config, carpeta, relativa: str) -> str | None`: convierte una ruta relativa a `publicar/` en el formato `cursos/…` de `/api/medios`.

- [ ] **Step 1: Tests que fallan.** Cada caso usa un `publicacion.json` falso creado en `tmp_path`:
  - Válido: lee piezas, redes y textos exactos, emojis incluidos.
  - JSON roto: error con el mensaje fijado.
  - Campo desconocido: error.
  - Id `reel-final`: error.
  - Portada `../../x.jpg`, portada inexistente y portada `.txt`: se descartan.
  - Sin archivo: `(None, None)`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar reutilizando `ruta_segura` y el lector JSON limitado de `lectura.py`; extráelo a una función común si hace falta. **Step 4:** PASS.
- [ ] **Step 5: Commit** `Lectura validada de publicacion.json`.

### Tarea 4: Vista de publicación, portada y estado

**Files:**
- Create: `estudio_api/rutas_publicar.py`, `estudio_api/vista_publicacion.py`
- Modify: `estudio_api/app.py` (incluir el router), `estudio_api/estado.py` y `estudio_api/lectura.py` (el `publicado` real y la `miniatura` elegida), `estudio_api/modelos.py`
- Test: `tests/test_publicar_api.py`, `tests/test_estado.py`

**Interfaces:**
- Consumes: tareas 2 y 3, y `leer_leccion` de la fase 1.
- Produces:
  - `RedVista(red, textos: TextosRed | None, estado: EstadoRed)`, siempre las 4 redes en orden.
  - `PiezaVista(id, tipo, titulo, video: str | None, duracion, fecha_propuesta, portadas: list[str], portada_elegida: str | None, redes: list[RedVista])`.
  - `VistaPublicacion(curso, numero, piezas: list[PiezaVista], despues_de_publicar: list[str], notas: str | None, error: str | None, guia: str | None)`.
  - Reglas de construcción:
    - Las piezas salen de la unión de las piezas del disco (fase 1) y las de `publicacion.json`, en el orden `leccion`, después `reel-salida*` y después `short-N` por número.
    - Las rutas de medios van en el formato `cursos/…`.
    - Las portadas son las del JSON más las del disco, sin duplicados.
    - `portada_elegida` sale de la base de datos solo si sigue entre las candidatas.
  - `GET /api/cursos/{curso}/lecciones/{numero}/publicacion` → `VistaPublicacion`, o 404 si la lección no existe.
  - `PUT …/piezas/{pieza}/portada` con cuerpo `{"ruta": str}`. La ruta tiene que estar entre las candidatas; si no, 422. Devuelve `VistaPublicacion`.
  - `PUT …/piezas/{pieza}/redes/{red}/estado` con cuerpo `EstadoRed` → `VistaPublicacion`. Una pieza que no existe da 404.
  - `publicado_por_red(publicacion: Publicacion | None, estados) -> dict[str, bool]`:
    - Las previstas son los pares (pieza, red) con textos en el JSON. Sin JSON, solo (`leccion`, `youtube`).
    - Una red está publicada si tiene alguna prevista y todas sus previstas están en `publicado`.
  - En `EstadoLeccion`: `publicado` sale de esa función, y `miniatura` es la portada elegida de `leccion`, si la hay.

- [ ] **Step 1: Tests que fallan:**
  - GET con JSON y sin JSON.
  - Elegir una portada, recargar y verla elegida. Borrar el archivo y que `portada_elegida` pase a `None`.
  - Una portada que no es candidata da 422.
  - Marcar como publicado `leccion`/`youtube`: el detalle de la lección da `publicado["youtube"] is True` y la lista de lecciones también.
  - Con un reel previsto en Instagram sin publicar, `instagram` queda en `False`.
  - Una red inválida en la ruta da 404 o 422.
  - El PUT sin token da 401. Este test ya existe con carácter general en la tarea 1; aquí se repite sobre la ruta real.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS.
- [ ] **Step 5: Commit** `Vista de publicación con portada elegida y estado por red`.

### Tarea 5: Edición de textos y guía regenerada

**Files:**
- Create: `estudio_api/guia.py`
- Modify: `estudio_api/rutas_publicar.py`
- Test: `tests/test_guia.py`, `tests/test_publicar_api.py`

**Interfaces:**
- Consumes: `escribir_atomico` (tarea 1), `Publicacion`/`validar_textos` (tarea 3), `VistaPublicacion` (tarea 4).
- Produces:
  - `PUT …/piezas/{pieza}/redes/{red}/textos` con cuerpo `TextosRed`.
    - Valida los límites (si no los cumple, 422).
    - Si existe `publicacion.json`, lo carga; si no, crea uno con `version: 1`.
    - Sustituye los textos de esa pieza y red, y lo escribe con `escribir_atomico` (JSON con `ensure_ascii=False`, sangría de 2 y salto de línea final).
    - Regenera la guía y devuelve `VistaPublicacion` más `aviso: str | None`.
    - Si `publicacion.json` está corrupto, responde 409 «Arregla publicacion.json antes de editar desde la app» y no escribe nada.
  - `generar_guia(publicacion: Publicacion, curso_nombre: str, numero: int, portada_elegida: dict[str, str]) -> str`. Genera Markdown con:
    - El título `# Publicar la lección N de <Curso>`.
    - Una sección por pieza, con su archivo, su portada y su fecha propuesta.
    - Dentro, una subsección por red con títulos (el recomendado marcado), descripción, etiquetas, texto y comentario fijado, cada uno en su bloque de código. Los ajustes van como lista y las notas, como párrafo.
    - Al final, «Después de publicar».
    - Si un texto contiene una valla de N acentos graves, se envuelve en una de N+1, con un mínimo de 3.
  - `regenerar_guia(config, carpeta, numero, curso_nombre, publicacion, portadas) -> str | None`:
    - Escribe `PUBLICAR-leccion-N.md` con `escribir_atomico`.
    - Después ejecuta `[sys.executable, <ESTUDIO_DIR>/herramientas/publicar/md-a-html.py, md, html, <portada elegida de leccion, si la hay>]` con `subprocess.run(..., shell=False, timeout=60, cwd=carpeta/"publicar")`.
    - Devuelve un aviso si falta el script o si falla. El `.md` queda escrito igualmente.
    - El HTML también se genera primero en un temporal y después se mueve con `os.replace`.

- [ ] **Step 1: Tests que fallan:**
  - `generar_guia`:
    - Una descripción con `` ``` `` dentro sale envuelta en `` ```` ``.
    - Los emojis y las comillas quedan intactos.
    - El orden de redes es YouTube, Instagram, TikTok, LinkedIn.
  - PUT de textos:
    - Escribe el JSON y crea `PUBLICAR-leccion-4.md` y su `.antes-de-editar` (cuando ya existía).
    - Para `md-a-html.py` se usa un script falso en `tmp_path`, que escribe el HTML.
    - Si el script falla, hay aviso y el `.md` queda escrito.
    - Con un JSON corrupto: 409, y el archivo queda intacto.
    - Un título de 101 caracteres: 422.
    - `subprocess.run` se llama con lista y sin shell (se comprueba con `monkeypatch`).
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS. **Step 5:** Escáneres en verde (el patrón de ejecución de procesos documentado en `security-review-instructions.md` como única excepción permitida).
- [ ] **Step 6: Commit** `Edición de textos de publicación y guía regenerada`.

---

## Repo web (`onlydevcoding-estudio-web`)

### Tarea 6: Escrituras desde el servidor

**Files:**
- Create: `src/lib/api-escritura.ts` (`import "server-only"`), `src/lib/acciones.ts` (`"use server"`)
- Modify: `src/lib/api.ts` (`obtenerPublicacion`), `src/lib/tipos.ts`, `.env.example` (`ESTUDIO_TOKEN=`), `README.md`, `AGENTS.md`, `security/security-review-instructions.md`, `package.json` (Claude instala `server-only`)
- Test: `src/lib/acciones.test.ts`, `src/lib/api.test.ts`

**Interfaces:**
- Consumes: los endpoints de las tareas 4 y 5.
- Produces:
  - `obtenerPublicacion(curso: string, numero: number): Promise<VistaPublicacion | null>`.
  - Tipos `VistaPublicacion`, `PiezaVista`, `RedVista`, `TextosRed` y `EstadoRed`, idénticos a la API.
  - `type ResultadoAccion = { ok: true; vista: VistaPublicacion; aviso?: string } | { ok: false; mensaje: string }`.
  - Server Actions:
    - `elegirPortada(curso, numero, pieza, ruta)`
    - `cambiarEstado(curso, numero, pieza, red, estado: EstadoRed)`
    - `guardarTextos(curso, numero, pieza, red, textos: TextosRed)`

    Las tres devuelven `Promise<ResultadoAccion>`, validan los argumentos (los patrones de curso, número, pieza y red) antes de llamar, y después refrescan la página (consulta en `node_modules/next/dist/docs/` la API de Next 16 para refrescar desde una Server Action).
  - `api-escritura.ts`: `escribir(ruta: string, cuerpo: unknown): Promise<Response>`, un `PUT` a `API_URL` con `X-Estudio-Token: process.env.ESTUDIO_TOKEN`.
    - Sin token: devuelve `{ok:false, mensaje:"Falta ESTUDIO_TOKEN en el .env de la web"}` sin llamar a `fetch`.
    - Los mensajes de error de la API (401, 409, 422 y 503) se traducen a castellano.

- [ ] **Step 1: Tests que fallan.** `fetch` simulado:
  - La cabecera `X-Estudio-Token` se envía.
  - Sin token no se llama a `fetch`.
  - Pieza `../x`: error sin llamar a `fetch`.
  - Un 409 se traduce a un mensaje en castellano.
  - El token no aparece en ningún archivo de `src/` que lleve `"use client"`. Es un test de texto sobre los archivos.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** lint, tests y build en verde.
- [ ] **Step 5: Commit** `Escrituras a la API desde Server Actions con token`.

### Tarea 7: Pestaña Publicar

**Files:**
- Create: `src/components/publicar/PublicarLeccion.tsx` (servidor), `SelectorPieza.tsx`, `ElegirPortada.tsx` (cliente), `TextosRed.tsx`, `BotonCopiar.tsx` (cliente), `EstadoPublicacion.tsx` (cliente)
- Modify: `src/app/cursos/[curso]/[numero]/page.tsx` (la pestaña `publicar` y los parámetros `pieza` y `red`)
- Test: `src/components/publicar/*.test.tsx`

**Interfaces:**
- Consumes: la tarea 6.
- Produces: la pestaña del boceto aprobado (`publicar.html`):
  - **Selector de piezas** con duración, que son enlaces `?pestana=publicar&pieza=<id>` (por defecto, la primera).
  - **«Portada — haz clic en la buena»**: miniaturas que son botones con `aria-pressed` y la marca «✓ Elegida».
  - **Pestañas por red** (`&red=`, por defecto la primera con textos). Cada una muestra:
    - Títulos, con el recomendado primero y marcado.
    - Descripción, etiquetas (unidas con `, `), texto y comentario fijado, cada campo con su botón «Copiar» (`navigator.clipboard.writeText`, que confirma con «Copiado» durante 2 s) y un contador `n/límite` que se pone en rojo si se pasa.
    - Ajustes de Studio en lista, notas, el vídeo propio de la red si lo tiene y la fecha propuesta.
  - **Estado:**
    - «📅 Programar» con `datetime-local`.
    - «✓ Marcar como publicado en <Red>», con un campo de URL opcional.
    - «Volver a pendiente».
    - Muestra el estado actual con su fecha.
    - Los errores de la acción se ven junto al botón.
  - **«Después de publicar»** como lista.
  - **Sin `publicacion.json`:** «Esta lección todavía no tiene textos de publicación», aunque siguen la portada y el estado.
  - **Con `error`:** sale el aviso.
  - Al marcar como publicado, el panel de estado y la rejilla del curso lo reflejan, porque vienen de la API.

- [ ] **Step 1: Tests que fallan:**
  - La pieza y la red se eligen por la URL.
  - Copiar llama a `clipboard.writeText` con el texto exacto, con saltos de línea.
  - El contador se pone en rojo al pasar de 100 en un título de YouTube.
  - La portada elegida tiene `aria-pressed="true"`.
  - Sin JSON, aparece el mensaje.
  - «Marcar como publicado» llama a la acción con `{estado:"publicado", url}`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** lint, tests y build.
- [ ] **Step 5: Commit** `Pestaña Publicar: portadas, textos por red y estado`.

### Tarea 8: Editar los textos

**Files:**
- Create: `src/components/publicar/EditorTextosRed.tsx` (cliente)
- Modify: `TextosRed.tsx` (botón «Editar»)
- Test: `src/components/publicar/EditorTextosRed.test.tsx`

**Interfaces:**
- Consumes: `guardarTextos` (tarea 6).
- Produces: el editor de los textos de una red.
  - **Campos:**
    - Títulos, uno por línea; el primero es el recomendado.
    - Descripción, texto y comentario, en `textarea`.
    - Etiquetas separadas por comas.
    - Ajustes, uno por línea.
    - Notas.
  - **Contadores en vivo:** «Guardar» se desactiva si algún campo se pasa de su límite.
  - **«Guardar»:** muestra «Guardado. Guía del móvil regenerada», o el `aviso` de la API si el HTML no se pudo regenerar.
  - **«Cancelar»:** descarta los cambios.
  - **Al guardar con error:** los textos editados se conservan.

- [ ] **Step 1: Tests que fallan:**
  - Los campos se convierten a `TextosRed` (las líneas vacías se quitan y las etiquetas se recortan).
  - Guardar está desactivado cuando un campo pasa del límite.
  - Si la acción devuelve error, el texto editado se conserva.
  - Si la acción devuelve un aviso, el aviso se muestra.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** lint, tests y build.
- [ ] **Step 5: Commit** `Edición de los textos de publicación desde la app`.

---

## Contenido y cierre (Claude)

### Tarea 9: Pasar las guías de las lecciones 1 a 4 a `publicacion.json`

Se hace en el repo privado `tech-study-videos-material` (`CURSOS_DIR`), nunca en los repos públicos.

- [ ] **Step 1:** Para cada `REACT/0N-*/publicar/PUBLICAR-leccion-N.md` (y `4-linkedin/LINKEDIN-leccion-N.md`), escribir `publicar/publicacion.json` con todo su contenido. Los títulos van con el recomendado primero. También van la descripción, las etiquetas, los ajustes de Studio, el comentario fijado, el vídeo relacionado (en las notas), los textos de cada short y reel y «Después de publicar». El calendario se pasa a `fecha_propuesta`.
- [ ] **Step 2:** Validar los cuatro con `GET …/publicacion`: deben salir sin `error` y con todas sus piezas.
- [ ] **Step 3:** Comparar, campo a campo, cada guía original con la vista. Nada se pierde. Lo que no encaja en un campo va a `notas`.
- [ ] **Step 4:** Commit en el repo privado. Las guías `.md|html` actuales no se tocan hasta que el autor guarde desde la app.

### Tarea 10: Verificación real y cierre

- [ ] **Step 1:** Generar `ESTUDIO_TOKEN` y ponerlo en los dos `.env`. Arrancar la API y la web (`npm run estudio`). Con Playwright, recorrer Publicar de la lección 4:
  - Elegir una portada y recargar.
  - Copiar el título.
  - Programar y marcar como publicado (y volver a pendiente).
  - Editar un texto y comprobar que se regeneran el JSON y la guía.
  - Ver el panel de estado y la rejilla del curso.
  - Sin token en la web, el aviso sale en castellano.
- [ ] **Step 2:** Pedir al autor qué piezas de las lecciones 1 a 4 ya están publicadas y marcarlas desde la app.
- [ ] **Step 3:** `/security-review` en los dos repos, guardar los informes y arreglar.
- [ ] **Step 4:** Revisión final de las dos ramas con un revisor nuevo, y arreglos.
- [ ] **Step 5:** Push y PR de cada repo, con la CI en verde. Merge solo con el visto bueno del autor.
