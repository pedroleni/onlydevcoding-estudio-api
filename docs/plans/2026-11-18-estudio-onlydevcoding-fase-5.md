# Estudio OnlyDevCoding · Fase 5 (Editar el guion y lanzar las herramientas) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Desde la ficha de la lección se editan los textos del guion (frases, puntos y ganchos) y se lanzan con botones las herramientas del estudio: alinear la voz, preparar el montaje, renderizar una versión nueva, crear el vídeo final a −14 LUFS, y preparar y renderizar los shorts. La lección avisa cuando el montaje se ha quedado atrás («guion cambiado: hay que regenerar el montaje»).

**Architecture:**
- **Motor:** el de la fase 4 se generaliza. Cada acción es un `PlanTrabajo` (comando fijo, `cwd`, entorno, temporal y destino, forma de instalar el resultado, patrón de progreso, tiempo máximo y mensajes). Se añaden cancelar, listar y un `objetivo` por trabajo (esquema v4).
- **Catálogo cerrado:** `acciones.py` construye el plan de cada acción a partir de la lección y de unas opciones validadas contra lo que hay en disco. Ninguna opción llega al comando sin estar en una lista conocida.
- **Herramientas del estudio:** se adaptan en su propio repo (`tech-study-videos`, privado) para leer `CURSOS_DIR` del entorno e imprimir `PROGRESO n/total`. Sin la variable se comportan exactamente igual que hoy.
- **Estado del montaje:** se deduce del disco comparando fechas (guion, alineaciones y `montaje.json`), sin guardar nada en la BD. Así también cuenta lo que se cambie fuera de la app.
- **Web:** un único hook de seguimiento de trabajos y un `BotonAccion` reutilizable en las pestañas Guion, Grabaciones, Vídeo final y Shorts y reels, más una página `/trabajos` con los últimos trabajos y el botón Cancelar.

**Tech Stack:**
- **API:** Python 3.14, uv, FastAPI, Pydantic v2, `sqlite3`, `subprocess` sin shell, pytest y ruff.
- **Web:** Next.js 16 (App Router, `cacheComponents`, Server Actions), TypeScript, Tailwind, Vitest y Testing Library.
- **Estudio:** Node (ESM) en `tech-study-videos`.
- **Verificación:** Playwright sobre clones APFS.

**Spec:** `docs/specs/2026-11-16-estudio-onlydevcoding-design.md`, en estos apartados:
- «Objetivos 2»;
- «Decisiones del autor»: guion editable, marca «guion cambiado» y botones para las herramientas;
- «Decisiones mías»: lista cerrada de acciones como trabajos de uno en uno, edición = solo textos (frases, puntos y ganchos), copia `.antes-de-editar` y adaptar las herramientas (variables de entorno y `PROGRESO n/total`, por PR propio);
- «Pantallas 2»: pestañas Guion, Grabaciones (escuchar tomas) y Vídeo final (versiones y lanzar render);
- «Acciones»: alinear la voz, preparar el montaje, render de la lección (`previa-vN` nueva), copia a −14 LUFS, preparar y renderizar shorts;
- «Seguridad»: procesos solo de la lista cerrada, con lista de argumentos y sin shell, y rutas dentro de las dos raíces.

**Bocetos:** `leccion-layout-v2.html` (pestañas y panel de estado). No hay boceto de la edición ni de los botones: siguen el estilo del editor del teleprompter y de la pestaña Publicar.

**Base:** la fase 4, integrada en `main`. Rama `feat/fase-5` en la API y en la web; rama `feat/rutas-y-progreso` en `tech-study-videos`.

## Contexto de ejecución

Igual que en las fases 1 a 4:
- **Implementación:** Codex implementa, sin red y sin escribir en `.git`. Si no tiene cuota, implementa Claude. **Codex no abre nada en `datos/`.** La tarea 1 va en una sesión de Codex aparte, con `-C` en el repo del estudio (no se mezclan proyectos).
- **Commits:** los hace Claude, sin `Co-Authored-By` ni «Generated with», con el email `noreply` de GitHub en los repos públicos.
- **Verificación y revisión:** Claude verifica con Playwright sobre clones y encarga las revisiones.
- **El flujo actual no cambia:** las herramientas se siguen pudiendo lanzar a mano desde la terminal con los mismos comandos y resultados.

## Global Constraints

- **Siguen en vigor las de las fases 1 a 4:**
  - `127.0.0.1`, Host, Origin y `Sec-Fetch-Site`;
  - escrituras con `X-Estudio-Token`, `Content-Length` obligatorio y 256 KB (salvo la subida de tomas);
  - nada privado en los repos públicos (ni rutas del Mac ni textos de lecciones; los tests usan datos falsos);
  - castellano de España y tema oscuro;
  - trabajos de uno en uno en toda la API → 409 «Ya hay un trabajo en marcha»;
  - `registro` no se expone por la API; los mensajes de error son fijos, sin rutas.
- **Entorno de los procesos:** el mínimo de la fase 4 (`PATH`, `HOME`, `TMPDIR`, `LANG`, `USER`, `NODE_ENV`) más `CURSOS_DIR=<config.cursos_dir>` en las acciones que leen o escriben en la carpeta de la lección.
- **Binarios:** `node` y `npx` con `shutil.which`; si faltan → 503 «No se encuentra node en el PATH de la API» o «No se encuentra npx en el PATH de la API». El script de sonido se lanza con `/bin/zsh` y su ruta relativa fija.
- **Catálogo de acciones** (id → comando, con `cwd=ESTUDIO_DIR`; `<guion>` = `f"{curso}-{numero:02d}"`):

  | id | Etiqueta | Comando | Resultado | Tiempo máx. | Progreso |
  |---|---|---|---|---|---|
  | `alinear-voz` | Alinear la voz | `[node, "herramientas/alinear-voz.mjs", <guion>]` | escribe en su sitio | 1 h | `^PROGRESO (\d+)/(\d+)$` |
  | `preparar-montaje` | Preparar el montaje | `[node, "herramientas/preparar-leccion.mjs", <guion>]` | escribe en su sitio | 30 min | `^PROGRESO (\d+)/(\d+)$` |
  | `previa-grabacion` | Vista previa de grabación | el de la fase 4, sin cambios | `out/previas-grabacion/<guion>.mp4`, reemplazar | 2 h | `(\d+)/(\d+)` |
  | `render-leccion` | Renderizar una versión nueva | `[npx, "--no", "remotion", "render", "src/index.ts", "Leccion", <temporal>, '--props={"leccion":"<guion>"}']` | `<lección>/previa/previa-vN.mp4`, sin pisar | 4 h | `(\d+)/(\d+)` |
  | `video-final` | Crear el vídeo final (−14 LUFS) | `["/bin/zsh", "herramientas/publicar/sonido-redes.sh", <previa elegida>, <temporal>]` | `<lección>/publicar/1-youtube-leccion/curso-<curso>-<NN>-<slug>.mp4`, archivando el anterior | 30 min | ninguno |
  | `preparar-shorts` | Preparar los shorts | `[node, "herramientas/preparar-shorts.mjs", "l<numero>"]` | escribe en su sitio | 30 min | `^PROGRESO (\d+)/(\d+)$` |
  | `render-short` | Renderizar el short | `[npx, "--no", "remotion", "render", "src/index.ts", "Short", <temporal>, '--props={"short":"<id>"}']` | `<lección>/shorts/<id>.mp4`, archivando el anterior | 1 h | `(\d+)/(\d+)` |

  - `N` de `previa-vN` = el mayor `N` de `previa/previa-v*.mp4` + 1 (1 si no hay ninguna).
  - `<slug>` = el nombre de la carpeta de la lección sin el prefijo `NN-`.
  - Temporales ocultos en el mismo directorio que el destino: `.<nombre sin .mp4>.generando.mp4`.
  - **Archivar:** si el destino existe, primero se mueve a `anteriores/<nombre sin .mp4>-<YYYYMMDDTHHMMSSffffff>.mp4` dentro de su directorio (`-2`, `-3`… si ya existe) y después se hace `os.replace`. Si `os.replace` falla, el anterior vuelve a su sitio. Nunca se pierde un vídeo.
  - **Sin pisar:** se instala con `os.link(temporal, destino)` + borrar el temporal; si el destino ya existe → error «Ya existe una versión con ese número; vuelve a lanzarlo».
- **Requisitos de cada acción** (si no se cumplen → 409 con el mensaje literal):
  - `alinear-voz`: al menos una escena de voz grabada → «No hay voz grabada que alinear».
  - `preparar-montaje`: el guion existe (404 si no).
  - `render-leccion`: estado del montaje `al_dia` → «Esta lección aún no tiene montaje», «Hay voz sin alinear: alinea la voz y prepara el montaje» o «Guion cambiado: hay que regenerar el montaje».
  - `video-final`: opción `previa` presente en la lista de previas de la lección → si no, 422 «Esa versión no existe».
  - `preparar-shorts`: existe `ESTUDIO_DIR/shorts/l<numero>/shorts.json` y su `leccion` es `<guion>` → «Esta lección no tiene shorts».
  - `render-short`: la opción `short` cumple `^[a-z0-9-]{1,60}$`, está en `shorts.json` y existe `public/shorts/<id>/montaje.json` → si no está en la lista, 422 «Ese short no existe»; si falta su montaje, 409 «Prepara los shorts antes de renderizar».
- **Estado del montaje** (`EstadoMontaje`), comparando `st_mtime_ns`:
  - `estado: "sin_montaje"` si no existe `public/lecciones/<guion>/montaje.json`;
  - `sin_alinear: list[str]` = escenas de voz con toma (`ruta_toma_voz`) cuya alineación `lecciones/tomas/<guion>/<E>-voz.json` falta o es más antigua que la toma;
  - `estado: "voz_sin_alinear"` si `sin_alinear` no está vacía;
  - `estado: "guion_cambiado"` si `lecciones/<guion>.json` o alguna alineación es más reciente que el montaje;
  - si no, `"al_dia"`. El orden de prioridad es el de esta lista.
- **Mensajes de los trabajos:**
  - código de salida ≠ 0: «Remotion terminó con el código N» en las acciones de Remotion y «La herramienta terminó con el código N» en las demás;
  - arranque: «No se pudo arrancar la herramienta»;
  - instalación: «No se pudo guardar el resultado» (la previa de grabación conserva «No se pudo guardar la vista previa»);
  - tiempo: «El trabajo ha tardado demasiado y se ha cancelado» (la previa conserva el suyo);
  - API cerrada: «El trabajo se ha interrumpido al cerrar la API»;
  - cancelado: «Cancelado».
- **Estados:** `en_marcha | hecho | error | interrumpido | cancelado`.
- **Esquema de la BD:** `PRAGMA user_version = 4`: la tabla `trabajo` gana `objetivo TEXT` (nulo). Desde 0 se crea todo; desde 1, 2 y 3 se migra en una sola transacción; antes de migrar desde 3 se guarda `<bd>.v3` con el mecanismo de `.v2`. Cualquier otra versión → `RuntimeError`.
- **Edición de textos:** las reglas de la fase 4 (mismo número, 1–1000 caracteres, sin controles ni bidi, versión SHA-256, `.antes-de-editar`, formato `indent=2` + `\n`), ampliadas a:
  - las frases (`cues[].texto`) de las escenas de **cámara** además de sus `puntos`;
  - los ganchos: `ganchos[].texto`, por `id`, con el mismo número de ganchos; `id` y `titulo` no cambian.
  - `TELEPROMPTER.txt` y `GUION.md` no se editan: son derivados (los generan `dia-de-grabacion.mjs` y `preparar-leccion.mjs`).

## Review Focus

1. **Se apaga la API, o se cancela, a mitad de un render de la lección:** no queda ningún `.generando.mp4`, no aparece una `previa-vN` a medias y el trabajo queda `interrumpido` o `cancelado`. Test en la tarea 2.
2. **Crear el vídeo final cuando ya existe uno:** el anterior acaba en `anteriores/` byte a byte igual, y si la instalación falla vuelve a su sitio. Test en la tarea 2.
3. **Una opción manipulada** (`previa="../../x.mp4"`, `short="s1;rm"`, un short de otra lección o un campo de más) no llega nunca al comando: 422 sin lanzar nada. Test en la tarea 3.
4. **Se edita el guion fuera de la app mientras está abierta la pestaña Guion:** 409, el archivo no se toca y la web conserva lo escrito con «Recargar». Tests en las tareas 4 y 6.
5. **Las herramientas adaptadas, sin variables de entorno, producen exactamente lo mismo que antes:** `montaje.json`, `GUION.md` y las alineaciones de una lección real son byte a byte iguales antes y después del cambio. Comprobación en la tarea 1.

---

### Tarea 1: Herramientas del estudio con `CURSOS_DIR` y progreso (repo `tech-study-videos`)

**Files** (en `ESTUDIO_DIR`, rama `feat/rutas-y-progreso`):
- Modify: `herramientas/alinear-voz.mjs`, `herramientas/preparar-leccion.mjs` y `herramientas/preparar-shorts.mjs`

**Interfaces:**
- **Produces:**
  - `alinear-voz.mjs` y `preparar-leccion.mjs` usan `process.env.CURSOS_DIR ?? <la ruta fija de hoy>` como raíz de los cursos. Ningún otro cambio de rutas.
  - Las tres herramientas imprimen en stdout una línea `PROGRESO i/total` (con `i` de 1 a `total`) al terminar cada unidad de trabajo: cada escena en `alinear-voz` y `preparar-leccion`, cada short en `preparar-shorts`. El resto de la salida no cambia.

- [ ] **Step 1: Línea base, sin tocar los datos reales.** El código actual escribe en la ruta fija de los cursos reales, así que **nunca se ejecuta sin cambiar antes esa constante**. En un clon APFS del estudio y otro de `Cursos youtube` (scratchpad), cambiar solo en el clon del estudio la constante `CURSOS` de las dos herramientas para que apunte al clon de los cursos. Después, ejecutar ahí `node herramientas/alinear-voz.mjs react-04` (con la caché `.origen` no debe volver a transcribir), `node herramientas/preparar-leccion.mjs react-04` y `node herramientas/preparar-shorts.mjs l3`. Guardar los hashes de `public/lecciones/react-04/montaje.json`, `lecciones/tomas/react-04/*-voz.json`, el `GUION.md` del clon y `public/shorts/*/montaje.json`.
- [ ] **Step 2: Implementar** los dos cambios en la rama, con la constante original.
- [ ] **Step 3: Comprobar (Review Focus 5):**
  - el valor por defecto de `CURSOS` es exactamente la ruta fija de antes (diff de la línea);
  - en el clon, con el código nuevo y `CURSOS_DIR=<clon de los cursos>`, los hashes coinciden con la línea base;
  - la carpeta real de la lección no cambia su `mtime`;
  - aparecen las líneas `PROGRESO 1/N … N/N`.
- [ ] **Step 4: Commit** `Herramientas: CURSOS_DIR desde el entorno y líneas PROGRESO` en `feat/rutas-y-progreso`. El PR de este repo privado se abre con permiso del autor; la tarea 8 lo usa desde la rama.

### Tarea 2: Motor de trabajos general, cancelar y listar (API)

**Files:**
- Modify: `estudio_api/trabajos.py`, `estudio_api/decisiones.py` (v4) y `estudio_api/rutas_teleprompter.py` (la previa pasa a un `PlanTrabajo`)
- Test: `tests/test_trabajos.py` y los casos de migración de `tests/test_decisiones.py`

**Interfaces:**
- **Produces, en `trabajos.py`:**
  - `Mensajes` (dataclass congelada): `codigo: str` (con `{codigo}`), `arranque`, `guardado`, `tiempo`. Constantes `MENSAJES_REMOTION`, `MENSAJES_HERRAMIENTA` y `MENSAJES_PREVIA`, con los textos de Global Constraints.
  - `PlanTrabajo` (dataclass congelada): `accion: str`, `objetivo: str | None`, `comando: list[str]`, `cwd: Path`, `temporal: Path | None = None`, `destino: Path | None = None`, `instalar: Literal["reemplazar", "sin_pisar", "archivar"] = "reemplazar"`, `entorno: Mapping[str, str] = {}`, `patron_progreso: re.Pattern[str] = PROGRESO_REMOTION`, `tiempo_maximo: float = TIEMPO_MAXIMO_RENDER`, `mensajes: Mensajes = MENSAJES_REMOTION`.
  - `PROGRESO_REMOTION = re.compile(r"(\d+)/(\d+)")` y `PROGRESO_HERRAMIENTA = re.compile(r"^PROGRESO (\d+)/(\d+)$")`. Se aplica a cada línea del registro; manda la última coincidencia.
  - `lanzar(bd_ruta: Path, curso: str | None, numero: int | None, plan: PlanTrabajo) -> Trabajo` sustituye a la firma de la fase 4. El entorno es `_entorno_render() | plan.entorno`.
  - `Trabajo` gana `objetivo: str | None` y el estado `"cancelado"`.
  - `cancelar(bd_ruta: Path, id: int) -> Trabajo | None`: si el trabajo corre en este proceso, marca el motivo `"cancelado"`, mata el grupo como el tiempo máximo (SIGTERM, 10 s, SIGKILL), borra el temporal y deja `cancelado` con «Cancelado». Si no está en marcha aquí → `None`.
  - `listar_trabajos(bd, limite: int) -> list[Trabajo]` (más recientes primero) y `ultimo_trabajo(bd, accion, curso, numero, objetivo: str | None = None)`.
- **Produces, en `decisiones.py`:** esquema v4 de Global Constraints.

- [ ] **Step 1: Tests que fallan:**
  - **Migración:** v3 con trabajos → v4 conservándolos (`objetivo` nulo) y con `<bd>.v3`; v2 y v1 → v4; v0 → v4; v5 → `RuntimeError`; un fallo forzado deja la v3 intacta.
  - **Progreso de herramienta:** un comando que imprime `procesando 3/9 escenas`, `PROGRESO 1/4` y `PROGRESO 2/4` acaba con `progreso == 0.5` con `PROGRESO_HERRAMIENTA`, y el `3/9` no cuenta.
  - **Entorno:** el proceso ve `CURSOS_DIR` del plan y no ve una variable `SECRETO` puesta en el entorno de la API.
  - **Archivar (Review Focus 2):** con un destino existente, al terminar el anterior está en `anteriores/<nombre>-<marca>.mp4` byte a byte igual y el nuevo en su sitio; dos instalaciones en el mismo segundo (reloj con `monkeypatch`) no se pisan; con `os.replace` forzado a fallar, el anterior vuelve a su sitio, el temporal se borra y el trabajo queda `error` con «No se pudo guardar el resultado».
  - **Sin pisar:** si el destino aparece mientras corre → `error` con «Ya existe una versión con ese número; vuelve a lanzarlo» y el archivo que apareció no cambia.
  - **Cancelar (Review Focus 1):** con un comando lento que escribe el temporal, `cancelar` deja `cancelado`, el proceso y sus hijos muertos, sin temporal ni destino, y se puede lanzar otro enseguida; `cancelar` de un trabajo `hecho` → `None`.
  - **Mensajes:** código 3 con `MENSAJES_HERRAMIENTA` → «La herramienta terminó con el código 3»; los huérfanos al arrancar → «El trabajo se ha interrumpido al cerrar la API».
  - **Listar:** con 25 trabajos, `listar_trabajos(bd, 20)` devuelve los 20 últimos en orden descendente.
  - **Regresión:** los tests de la previa de la fase 4 siguen en verde con su comando y sus mensajes.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS, más `ruff check` y `ruff format --check`.
- [ ] **Step 5: Commit** `Motor de trabajos general: planes, archivar, cancelar y listar`.

### Tarea 3: Catálogo de acciones, estado del montaje y rutas (API)

**Files:**
- Create: `estudio_api/acciones.py` y `estudio_api/rutas_acciones.py`
- Modify: `estudio_api/modelos.py` (`EstadoMontaje` y `Leccion.montaje`), `estudio_api/lectura.py` (`leer_leccion` rellena `montaje`), `estudio_api/rutas_teleprompter.py` (la previa usa el catálogo) y `estudio_api/app.py` (router)
- Test: `tests/test_acciones.py`

**Interfaces:**
- **Consumes:** la tarea 2; `carpeta_de_trabajo`, `datos_curso`, `ruta_segura`, `ruta_toma_voz`, `ruta_montaje` y `_previas`.
- **Produces, modelos:**
  - `EstadoMontaje{estado: Literal["sin_montaje","voz_sin_alinear","guion_cambiado","al_dia"], sin_alinear: list[str]}`. `Leccion.montaje: EstadoMontaje | None` (`None` sin guion).
  - `IdAccion = Literal[...]` con los siete ids de Global Constraints.
  - `OpcionesAccion{previa: str | None = None, short: str | None = None}` con `extra="forbid"`.
  - `EstadoAccion{id: IdAccion, etiqueta: str, disponible: bool, motivo: str | None, opciones: list[str], ultimo: Trabajo | None, ultimos: dict[str, Trabajo]}`:
    - `opciones`: los nombres de las previas (`previa-vN.mp4`) en `video-final` y los ids de los shorts en `render-short`; vacía en las demás;
    - `ultimos`: el último trabajo por objetivo, solo en `render-short`.
- **Produces, funciones en `acciones.py`:**
  - `estado_montaje(config, guion: str, carpeta: Path) -> EstadoMontaje`.
  - `estados_acciones(config, bd, curso, numero) -> list[EstadoAccion] | None` (`None` si la lección no existe).
  - `plan_accion(config, curso, numero, accion: IdAccion, opciones: OpcionesAccion) -> PlanTrabajo`, que lanza `AccionNoDisponible(estado_http: int, mensaje: str)` con los mensajes y códigos de Global Constraints.
- **Produces, rutas:**
  - `GET /api/cursos/{curso}/lecciones/{numero}/acciones` → `list[EstadoAccion]` en el orden del catálogo, o 404.
  - `POST /api/cursos/{curso}/lecciones/{numero}/acciones/{accion}` (cuerpo `OpcionesAccion`) → 202 `Trabajo`. Errores: 404, 409, 422 y 503.
  - `GET /api/trabajos?limite=20` (1–100) → `list[Trabajo]`.
  - `POST /api/trabajos/{id}/cancelar` (cuerpo `{}`) → 200 `Trabajo`, o 409 «Ese trabajo no está en marcha».
  - `POST …/previa-grabacion` sigue igual hacia fuera y por dentro usa `plan_accion(..., "previa-grabacion", ...)`.

- [ ] **Step 1: Tests que fallan** (fixture con guion, tomas, montajes y `shorts.json` falsos, y `shutil.which` y los comandos sustituidos por scripts de Python como en la fase 4):
  - **Estado del montaje:** sin montaje → `sin_montaje`; una toma más nueva que su `-voz.json` → `voz_sin_alinear` con `["E03"]`; el guion tocado después del montaje → `guion_cambiado`; todo en orden → `al_dia`. `GET` de la lección lo incluye.
  - **Comandos exactos:** `plan_accion` devuelve para cada id la lista de Global Constraints (con rutas de la fixture), `cwd=ESTUDIO_DIR`, el temporal oculto junto al destino y `entorno == {"CURSOS_DIR": str(config.cursos_dir)}` en `alinear-voz` y `preparar-montaje`.
  - **`render-leccion`:** con `previa-v1.mp4` y `previa-v3.mp4` el destino es `previa-v4.mp4`; con `guion_cambiado` → 409 con su mensaje.
  - **Opciones (Review Focus 3):** `video-final` con `previa="../../x.mp4"`, con una previa que no existe o sin `previa` → 422; `render-short` con `short="s1;rm"`, con un id de otra lección o con `{"short":"s1","extra":1}` → 422. En todos los casos no se ha llamado a `lanzar`.
  - **Disponibilidad:** sin voz grabada, `alinear-voz` sale `disponible: false` con su motivo; sin `shorts.json`, `preparar-shorts` y `render-short` igual; `render-short` lista los ids de `shorts.json` en `opciones`.
  - **Rutas:** POST sin token → 401; acción desconocida → 422; con otro trabajo en marcha → 409; `GET /api/trabajos?limite=0` → 422; cancelar un trabajo terminado → 409; el trabajo de `render-short` guarda `objetivo` y aparece en `ultimos`.
  - **Regresión:** los tests de `previa-grabacion` de la fase 4 siguen en verde.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS.
- [ ] **Step 5: Commit** `Catálogo cerrado de acciones, estado del montaje y rutas de trabajos`.

### Tarea 4: Editar frases de cámara y ganchos (API)

**Files:**
- Modify: `estudio_api/guion_textos.py`, `estudio_api/teleprompter.py` (`ganchos` en la lectura) y `estudio_api/rutas_teleprompter.py`
- Test: `tests/test_guion_textos.py` y `tests/test_teleprompter_api.py`

**Interfaces:**
- **Produces:**
  - `GanchoGuion{id: str, titulo: str, texto: str}` y `Teleprompter.ganchos: list[GanchoGuion]` (vacía si el guion no tiene `ganchos` o no es una lista; se ignoran los elementos sin `id` y `texto` de tipo `str`).
  - `CambioEscena` admite `cues` también en escenas de cámara (antes solo `puntos`).
  - `CambiosTextos.escenas` pasa a 0–200 elementos y gana `ganchos: list[CambioGancho{id: str, texto: str}] | None = None` (1–20, `extra="forbid"`). Al menos uno de los dos con contenido; si no → 422 «No hay cambios que guardar».
  - `aplicar_textos` aplica los ganchos por `id`: exige que estén todos los del guion, una sola vez y ninguno de más, y solo cambia `texto`.

- [ ] **Step 1: Tests que fallan:**
  - cambiar la frase 1 de E01 (cámara) y un punto en la misma petición cambia solo esas dos cadenas del JSON;
  - cambiar el texto del gancho `g2` deja igual `id`, `titulo`, los demás ganchos y el resto del archivo, con `.antes-de-editar` creado la primera vez;
  - ganchos con uno de menos, uno repetido, un id desconocido o un texto con `\n` → 422 y el archivo sin tocar;
  - `{"version": …, "escenas": []}` sin ganchos → 422 «No hay cambios que guardar»;
  - el `GET` del teleprompter devuelve `ganchos` en su orden, y `[]` con un guion sin ganchos o con `ganchos` que no es una lista;
  - versión vieja con solo ganchos (Review Focus 4) → 409 con el mensaje de la fase 4 y el archivo como lo dejó el cambio externo.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS.
- [ ] **Step 5: Commit** `Editar frases de cámara y ganchos con control de versión`.

### Tarea 5: Acciones, trabajos y su seguimiento (web)

**Files:**
- Modify: `src/lib/tipos.ts`, `src/lib/api.ts`, `src/components/BarraNavegacion.tsx` y `src/components/teleprompter/useSeguimientoPrevia.ts` (pasa a envolver el hook general)
- Create: `src/lib/acciones-estudio.ts` (`"use server"`), `src/components/acciones/useSeguimientoTrabajo.ts`, `src/components/acciones/BotonAccion.tsx` y `src/app/trabajos/page.tsx`
- Test: `src/lib/acciones-estudio.test.ts`, `src/components/acciones/BotonAccion.test.tsx` y `src/app/trabajos/page.test.tsx`

**Interfaces:**
- **Consumes:** las rutas de la tarea 3.
- **Produces:**
  - En `tipos.ts`: `Trabajo` con `objetivo` y el estado `cancelado`; `IdAccion`, `EstadoAccion`, `EstadoMontaje` y `Leccion.montaje`; `Teleprompter.ganchos`.
  - En `api.ts`: `obtenerAcciones(curso, numero): Promise<EstadoAccion[] | null>` y `obtenerTrabajos(limite = 20): Promise<Trabajo[]>`.
  - En `acciones-estudio.ts`, con el patrón de `acciones-teleprompter.ts` (validar, `detalleDe`, `{ ok, … }`):
    - `lanzarAccion(curso, numero, accion: IdAccion, opciones: { previa?: string; short?: string }): Promise<{ ok: true; trabajo: Trabajo } | { ok: false; mensaje: string }>`;
    - `cancelarTrabajo(id: number): Promise<{ ok: true; trabajo: Trabajo } | { ok: false; mensaje: string }>`.
  - `useSeguimientoTrabajo({ trabajo, alTerminar })`: consulta `leerTrabajo` cada 2 s mientras esté `en_marcha` y, al pasar a otro estado, llama a `router.refresh()` una vez. Es la lógica de `useSeguimientoPrevia` (incluidos `MAXIMO_REFRESCOS` y la limpieza al desmontar), que pasa a ser un envoltorio fino sin cambiar su comportamiento.
  - `<BotonAccion curso numero accion={EstadoAccion} opciones? textoBoton? confirmar?>`:
    - desactivado con `motivo` como texto de ayuda si `!disponible`;
    - mientras corre: «En marcha… N %» (o «En marcha…» si el progreso es 0) y un botón «Cancelar»;
    - al acabar: «Hecho», «Falló: …» (con el `error` del trabajo), «Interrumpido» o «Cancelado», con la fecha;
    - con `confirmar`, pide confirmación antes de lanzar (`video-final` y `render-leccion`).
  - **`/trabajos`:** tabla de los últimos 20 con acción (etiqueta), lección (enlace), objetivo, estado, progreso, inicio y fin, y «Cancelar» en el que está en marcha. La barra de navegación gana «Trabajos».

- [ ] **Step 1: Tests que fallan:**
  - `lanzarAccion` con una acción fuera de la lista o `short="s1;rm"` → `ok: false` sin `escribir`; un 409 devuelve el mensaje de la API; una válida llama a `escribir(".../acciones/render-short", { short: "s1" }, "POST")`;
  - `BotonAccion` no disponible → botón desactivado y el motivo visible; lanzar → «En marcha… 40 %» y, cuando `leerTrabajo` devuelve `hecho`, llama a `router.refresh`; «Cancelar» llama a `cancelarTrabajo`; con `confirmar` y la confirmación rechazada no lanza nada;
  - `/trabajos` pinta un trabajo `cancelado` y uno `en_marcha` con su botón;
  - los tests de `PanelPrevia` y `Teleprompter` de la fase 4 siguen en verde.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** lint, tests y build (en un clon, no en el repo que sirve `next start`).
- [ ] **Step 5: Commit** `Acciones del estudio: lanzar, seguir y cancelar trabajos`.

### Tarea 6: Pestaña Guion editable (web)

**Files:**
- Create: `src/components/guion/GuionEditable.tsx` (cliente), `src/components/guion/EditorEscenaGuion.tsx`, `src/components/guion/EditorGanchos.tsx`, `src/components/guion/AvisoMontaje.tsx` y `src/lib/textos-guion.ts` (las funciones `sinSaltos`, `limpio` y `valido` que hoy viven en `EditorTextos.tsx`, que pasa a importarlas)
- Modify: `src/app/cursos/[curso]/[numero]/page.tsx` (la pestaña Guion pide también `obtenerTeleprompter` y `obtenerAcciones`), `src/components/TarjetaEscena.tsx` (hueco para el botón «Editar») y `src/lib/acciones-teleprompter.ts` (`guardarTextos(curso, numero, version, escenas, ganchos?: { id: string; texto: string }[])`, con las mismas validaciones para los ganchos; la llamada del teleprompter no cambia)
- Test: `GuionEditable.test.tsx`, `EditorGanchos.test.tsx` y `AvisoMontaje.test.tsx`

**Interfaces:**
- **Consumes:** `guardarTextos` (fase 4, con `ganchos`), `Teleprompter.version`, `EstadoMontaje` y `BotonAccion`.
- **Produces:**
  - Cada escena de voz o cámara tiene «Editar». El editor muestra una `textarea` por frase y, en cámara, otra por punto, con «Guardar» y «Cancelar». Solo una escena en edición a la vez.
  - Debajo de las escenas, «Ganchos de los shorts»: título y texto de cada gancho, con «Editar ganchos».
  - Guardar llama a `guardarTextos(curso, numero, version, escenas, ganchos?)` con todas las frases (y puntos) de la escena; tras guardar, `router.refresh()`.
  - Conflicto: el mensaje de la API y «Recargar», conservando lo escrito (mismo comportamiento que el teleprompter).
  - `AvisoMontaje` encima de las escenas:
    - `guion_cambiado` → «Guion cambiado: hay que regenerar el montaje.» con `BotonAccion` de `preparar-montaje`;
    - `voz_sin_alinear` → «Voz sin alinear: E03, E05.» con `BotonAccion` de `alinear-voz`;
    - `sin_montaje` → «Esta lección aún no tiene montaje.» con `BotonAccion` de `preparar-montaje`;
    - `al_dia` → nada.
  - `useAvisoAlSalir` activo mientras haya texto sin guardar.

- [ ] **Step 1: Tests que fallan:**
  - editar la frase 2 de E03 y guardar llama a `guardarTextos("react", 4, <version>, [{ id: "E03", cues: [...] }])`;
  - en una escena de cámara se envían `cues` y `puntos`;
  - editar un gancho envía `ganchos` con todos los ganchos;
  - un texto vacío desactiva «Guardar»;
  - con conflicto, lo escrito sigue y aparece «Recargar»;
  - cada estado del montaje muestra su texto y su botón, y `al_dia` no muestra nada;
  - una escena de animación no tiene «Editar»;
  - los textos de la API se pintan como texto (`<script>` literal).
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** lint, tests y build en el clon.
- [ ] **Step 5: Commit** `Pestaña Guion: editar frases, puntos y ganchos, y aviso del montaje`.

### Tarea 7: Grabaciones, Vídeo final y Shorts con sus acciones (web)

**Files:**
- Modify: `src/app/cursos/[curso]/[numero]/page.tsx` (`obtenerAcciones` en estas pestañas), `src/components/ListaPiezas.tsx` (`VistaVideoFinal`) y `src/components/PanelEstado.tsx` (línea del montaje)
- Create: `src/components/acciones/PanelVideoFinal.tsx`, `src/components/acciones/PanelShorts.tsx` y `src/components/GrabacionesVoz.tsx`
- Test: `PanelVideoFinal.test.tsx`, `PanelShorts.test.tsx`, `GrabacionesVoz.test.tsx` y `PanelEstado.test.tsx`

**Interfaces:**
- **Consumes:** `BotonAccion`, `EstadoAccion`, `Teleprompter.escenas[].toma`/`version_toma` y `urlMedio`.
- **Produces:**
  - **Grabaciones:** cada escena de voz grabada con su `<audio controls preload="none">` (`urlMedio(toma)` y `&v=<version_toma>`) y «Sin grabar» en las demás; arriba, `BotonAccion` de `alinear-voz` y la lista `sin_alinear`. Las de cámara siguen como hoy (la entrega es de la fase 6).
  - **Vídeo final:** encima de las versiones, `BotonAccion` «Renderizar una versión nueva (previa-vN)» con `confirmar`, y «Crear el vídeo final (−14 LUFS)» con un `<select>` de `opciones` (por defecto la última) y `confirmar` («Si ya hay un vídeo final, se guardará en anteriores/.»).
  - **Shorts y reels:** `BotonAccion` de `preparar-shorts` y una fila por id de `render-short.opciones` con su «Renderizar» y el estado de `ultimos[id]`. Sin `shorts.json`, el motivo de la API. Las piezas de `publicar/2-shorts-y-reels/` se siguen mostrando debajo.
  - **Panel de estado:** una línea «Montaje» con ✅ (`al_dia`), ⚠️ (`guion_cambiado` o `voz_sin_alinear`) o ⬜ (`sin_montaje`).

- [ ] **Step 1: Tests que fallan:**
  - Grabaciones: E03 grabada tiene `<audio>` con `?…&v=` y E04 «Sin grabar»;
  - Vídeo final: el `<select>` lista las previas y por defecto la última; lanzar envía `{ previa: "previa-v11.mp4" }` tras confirmar; sin montaje al día, «Renderizar» está desactivado con el motivo;
  - Shorts: una fila por short con el estado de su último trabajo; «Renderizar» de `s2` envía `{ short: "s2" }`;
  - Panel de estado: los tres iconos del montaje.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** lint, tests y build en el clon.
- [ ] **Step 5: Commit** `Lección: acciones de voz, vídeo final y shorts`.

### Tarea 8: Verificación real y cierre

- [ ] **Step 1: Arranque.** Clones APFS de `Cursos youtube/REACT` y de `ESTUDIO_DIR` (con `node_modules` y la rama `feat/rutas-y-progreso`) y una copia de la BD real (v3) en el scratchpad. API apuntando a ellos (`CURSOS_DIR`, `ESTUDIO_DIR`, `BD_RUTA`) y web de un clon con `npm run estudio`.
- [ ] **Step 2: Recorrido con Playwright** sobre la lección 4 (o la que tenga shorts para esa parte):
  - **BD:** la copia migra a la v4 y deja `.v3`.
  - **Guion:** editar una frase de voz, una de cámara y un gancho; el JSON del clon cambia solo en esas cadenas; aparece «Guion cambiado: hay que regenerar el montaje.»; un cambio a mano en el JSON y guardar → conflicto.
  - **Alinear:** grabar o tocar una toma en el clon → «Voz sin alinear: E…»; «Alinear la voz» avanza con `PROGRESO` y acaba `hecho` (comprueba que `Transcribir.app` funciona lanzada desde la API).
  - **Montaje:** «Preparar el montaje» acaba `hecho`, el aviso desaparece y `GUION.md` cambia solo en el clon (la carpeta real sin tocar: mismo `mtime`).
  - **Render:** «Renderizar una versión nueva» crea `previa-vN` con N = siguiente; cancelar un segundo render deja `cancelado` y ningún `.generando.mp4`.
  - **Vídeo final:** crearlo desde la última previa; repetirlo deja el anterior en `anteriores/`.
  - **Shorts:** preparar y renderizar un short de una lección con `shorts.json` (l1–l3) en el clon.
  - **Trabajos:** `/trabajos` muestra todo lo anterior.
  - **Calidad:** 0 errores de consola y sin scroll horizontal a 390 px.
- [ ] **Step 3:** `/security-review` en los dos repos, con atención a la construcción de comandos, las opciones y el entorno. Guardar los informes y arreglar lo que salga.
- [ ] **Step 4:** Revisión final de las dos ramas con un revisor nuevo, y arreglos.
- [ ] **Step 5:** Push y PR de los tres repos (el de `tech-study-videos` primero) con la CI en verde, con permiso del autor. Merge solo con su visto bueno.

## Fuera de esta fase

- **Fase 6:** entregar las tomas a cámara y los ganchos verticales, mejorar con IA (`superres.sh`) y `piel-natural`.
- **Reels de salida** (`Anuncio`, `AnuncioL3`, `AnuncioL4`…): son composiciones hechas a mano para cada lección, sin un formato común que una acción pueda lanzar. Se siguen haciendo a mano.
- **Normalizar los shorts a −14 LUFS y copiarlos a `publicar/2-shorts-y-reels/short-N-<slug>.mp4`:** hoy el nombre final se decide a mano; se valorará cuando haya un formato fijo.
- **Regenerar `TELEPROMPTER.txt`:** `dia-de-grabacion.mjs` escribe archivos de varias lecciones a la vez en `CURSOS_DIR/REACT/`; lanzarlo para una sola los pisaría.
- **Ver el registro de un trabajo en la web:** sigue sin exponerse (decisión de seguridad de la fase 4); el detalle va al log de la API.
- **Minors aplazados de la fase 4:** siguen en su registro.
