# Estudio OnlyDevCoding · Fase 4 (Teleprompter y grabación) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** El teleprompter de la app hace todo lo que hace hoy la página de grabación (`npm run grabar`) y añade las escenas a cámara marcadas 🎥 con su texto. Incluye:
- ritmo, letra, micrófono y nivel;
- ensayar, grabar a WAV, parar y repetir;
- editar el texto;
- la vista previa sincronizada con la lectura y con la toma;
- los nombres hablados y los números en cifras.

**Architecture:**
- **Lectura:** la API junta en una sola respuesta todo lo que el teleprompter necesita de una lección: el guion, qué escenas están grabadas, los tiempos del montaje y el estado de la vista previa.
- **Grabación:** el navegador graba y convierte a WAV como hoy. Sube la toma a un Route Handler de Next, que guarda el token y reenvía el cuerpo en streaming a la API.
  - Es la única ruta de la API con un límite de cuerpo grande.
  - La toma anterior pasa a `grabaciones/tomas/`.
- **Vista previa:** se genera con un motor de trabajos mínimo, de uno en uno y registrado en SQLite (esquema v3), con una sola acción de la lista cerrada. La fase 5 añadirá las demás acciones a ese mismo motor.
- **Texto:** la edición escribe solo los textos, con control de versión, para no pisar cambios hechos fuera.

**Tech Stack:**
- **API:** Python 3.14, uv, FastAPI, Pydantic v2, `sqlite3`, `subprocess` sin shell, `threading`, pytest y ruff.
- **Web:** Next.js 16 (App Router, `cacheComponents`, Server Actions y Route Handlers), TypeScript, Tailwind, Vitest y Testing Library. En el navegador: MediaRecorder, Web Audio y `requestAnimationFrame`.
- **Verificación:** Playwright con micrófono simulado, sobre clones APFS.

**Spec:** `docs/specs/2026-11-16-estudio-onlydevcoding-design.md`, en estos apartados:
- «Objetivos 4»;
- «Decisiones del autor → Teleprompter»;
- «Decisiones mías»: edición = solo textos, copia `.antes-de-editar`, herramientas como trabajos de uno en uno y la página actual en paralelo;
- «Pantallas 4»;
- «Acciones»: generar la vista previa de grabación;
- «Seguridad»: subidas con límite de tamaño y tipo, y procesos de la lista cerrada sin shell.

**Referencia funcional (hay que portarla):** `ESTUDIO_DIR/herramientas/grabacion/index.html` y `servidor.mjs` del repo privado `tech-study-videos`. Se leen ahí y **no se copian textos de guiones a los repos públicos**. Las funciones que se portan son estas, y su comportamiento es el contrato:
- `calcularPlan`, `trocear`, `leerNumero` y `NUMEROS`;
- `sincronizarPrevia` y `previaConToma`;
- `aWav`;
- `aplicarTextos`, `generarPrevia` y `resumenMontaje`.

**Boceto aprobado:** `teleprompter.html` de `.superpowers/brainstorm/` del proyecto de bocetos. Muestra:
- **La barra de escenas,** con `E10 ✓`, `E11` y `🎥 E17`.
- **La escena de voz:** texto grande, vista previa a la derecha, «Ritmo 175 ppm · Letra · Micrófono · Nivel», Ensayar, ● Grabar, Editar texto y «▶ Toma guardada: E11.wav».
- **La escena a cámara:** «🎥 Se graba con la cámara · horizontal», los puntos numerados y el botón «⬆ Entregar los vídeos de la cámara». La entrega es de la **fase 6**: aquí el botón sale desactivado con el título «Llega en la fase 6».

**Base:** la fase 3, integrada en `main`. Rama `feat/fase-4` en cada repo.

## Contexto de ejecución

Igual que en las fases 1 a 3:
- **Implementación:** Codex implementa, sin red y sin escribir en `.git`. Si no tiene cuota, implementa Claude.
- **Commits:** los hace Claude, sin `Co-Authored-By` ni «Generated with», con el email `noreply` de GitHub.
- **Verificación y revisión:** Claude verifica con Playwright sobre clones y encarga las revisiones.
- **La página actual (`npm run grabar`) no se toca:** sigue funcionando en paralelo. La app escribe en las mismas rutas y con los mismos nombres de archivo.

## Global Constraints

- **Siguen en vigor las de las fases 1 a 3:**
  - todo en `127.0.0.1`, con comprobación de Host, Origin y `Sec-Fetch-Site`;
  - toda escritura con `X-Estudio-Token`, `Content-Length` obligatorio y sin `Transfer-Encoding`;
  - CORS solo para `GET`;
  - nada privado en los repos;
  - castellano de España y tema oscuro.
- **Identificadores:**
  - guion: `f"{curso}-{numero:02d}"`, por ejemplo `react-04`, en `ESTUDIO_DIR/lecciones/<guion>.json`;
  - escena: `^E\d{2}$`.
  - Las escenas `animacion` no salen en el teleprompter.
- **Cuerpo grande, solo en una ruta:**
  - es `PUT /api/cursos/{curso}/lecciones/{numero}/grabaciones/{escena}`;
  - admite hasta **200 MiB** (`209715200` bytes) y `Content-Length` de hasta 9 dígitos;
  - exige `Content-Type: audio/wav` y que el cuerpo empiece por `RIFF` con `WAVE` en los bytes 8–12;
  - el resto de rutas sigue con 256 KB.
- **Tomas de voz:**
  - destino `<carpeta lección>/grabaciones/<E>.wav`, solo para escenas `voz` del guion;
  - se escribe primero en un temporal oculto del mismo directorio;
  - después la toma anterior se mueve a `grabaciones/tomas/<E>-<YYYYMMDDTHHMMSSffffff>.wav` (si el nombre ya existe, se añade `-2`, `-3`…);
  - por último, `os.replace`.
  - Nunca se pierde una toma.
- **Vista previa de grabación:** la misma ruta que la página actual, `ESTUDIO_DIR/out/previas-grabacion/<guion>.mp4`, con un temporal `<guion>.generando.mp4`.
  - **Comando fijo, sin shell y con `cwd=ESTUDIO_DIR`:** `[<npx>, "remotion", "render", "src/index.ts", "Leccion", <temporal>, '--props={"leccion":"<guion>"}', "--scale=0.5", "--muted", "--crf=30"]`.
    - `<npx>` es `shutil.which("npx")`. Si no existe → 503 «No se encuentra npx en el PATH de la API».
  - **Requisito:** que exista `public/lecciones/<guion>/montaje.json`. Si no → 409 «Esta lección aún no tiene montaje».
  - **Desactualizada:** cuando el `mtime` de `montaje.json` es mayor que el de la previa.
- **Trabajos:**
  - van de uno en uno en toda la API: si hay uno en marcha → 409 «Ya hay un trabajo en marcha»;
  - estados `en_marcha | hecho | error | interrumpido`;
  - `progreso` va de 0 a 1 y es el último `(\d+)/(\d+)` que aparece en la salida;
  - `registro` guarda las últimas 40 líneas, de hasta 500 caracteres cada una;
  - el error queda como «Remotion terminó con el código N»;
  - al arrancar la API, los `en_marcha` pasan a `interrumpido` y se borran sus temporales.
- **Esquema de la BD:** `PRAGMA user_version = 3`.
  - Desde 0 se crea todo; desde 1 y desde 2 se migra en una sola transacción.
  - Antes de migrar desde 2 se guarda una copia `<bd>.v2`, con el mismo mecanismo que la copia `.v1`.
  - Cualquier otra versión da `RuntimeError`.
- **Edición de textos:**
  - solo se cambian `cues[].texto` y `puntos`, con **el mismo número** de frases y de puntos;
  - cada texto se recorta, ocupa de 1 a 1000 caracteres y no lleva saltos de línea ni caracteres de control.
  - **Control de versión:** `version` es el SHA-256 en hexadecimal de los bytes del archivo. Si no coincide → 409 «El guion ha cambiado fuera de la app. Recarga antes de guardar.».
  - **Escritura:** con `escribir_atomico`, que crea la copia `.antes-de-editar`. Se serializa con `json.dumps(…, ensure_ascii=False, indent=2) + "\n"`, que es el formato de la página actual.
- **Ajustes del teleprompter (iguales que hoy):**
  - ritmo 110–200 ppm, en pasos de 5, por defecto 150;
  - letra 32–80 px, en pasos de 2, por defecto 52;
  - vista previa Oculta/Pequeña/Mediana/Grande = 0/320/440/600 px, por defecto 440;
  - esperas `coma 0.22`, `punto 0.42` y `frase 0.5` s;
  - grabando, la toma sigue tras el texto hasta `max(15, total·0.5)` s;
  - se guardan en `localStorage["teleprompter-preferencias"]`, siempre dentro de `try/catch`.
- **Atajos (iguales que hoy):**
  - Espacio: ensayar, o parar si va en marcha;
  - Intro: grabar;
  - Esc: parar;
  - R: repetir;
  - ← y →: escena anterior y siguiente.
  - No actúan mientras se edita o con el foco en un campo.
- **Textos de la interfaz:** los de la página actual, literales. Por ejemplo:
  - en los modos, «Voz en off · leer» y «Cámara · con tus palabras»;
  - en las cuentas atrás, «Silencio» y «dos segundos sin hablar ni moverte (sirve para limpiar el ruido)»;
  - en el pie de la previa, «voz provisional, sin sonido» y «el montaje ha cambiado: regénerala».
- **URL:** `/teleprompter?curso=<id>&leccion=<n>`.
  - Si falta algún parámetro, se abre la última lección usada (la preferencia guardada) o, si no hay, la primera lección con guion.
  - Una lección sin guion muestra «Esta lección aún no tiene guion».

## Review Focus

1. **Una subida que falla a mitad** (cuerpo cortado, 413 o un WAV que no lo es) deja la toma anterior `E03.wav` intacta, sin temporales ni nada movido a `tomas/`. Test en la tarea 3.
2. **Repetir la misma escena dos veces en el mismo segundo** no pisa ninguna toma anterior en `tomas/`. Test en la tarea 3.
3. **El guion cambia fuera de la app** (en la página actual o lo cambia Claude) entre cargar y guardar el texto: responde 409 y el archivo no se toca. La web muestra el mensaje y conserva lo escrito. Tests en las tareas 4 y 8.
4. **La API se reinicia con un render en marcha:** el trabajo queda `interrumpido`, su temporal se borra y se puede volver a lanzar. Test en la tarea 1.
5. **Textos con números y nombres ambiguos** («uno» como pronombre, «uno, dos», «cada punto es», cifras ya escritas o una frase vacía tras recortar) se leen igual que en la página actual. Hay tests en la tarea 5. Además, en la tarea 9 se comprueba la paridad con todos los guiones reales, en local y sin comitear.

---

### Tarea 1: Esquema v3 y motor de trabajos (API)

**Files:**
- Modify: `estudio_api/decisiones.py` (`abrir_bd`, `_copia_antes_de_migrar` con la versión como parámetro)
- Create: `estudio_api/trabajos.py`
- Modify: `estudio_api/app.py` (al arrancar, `interrumpir_huerfanos`)
- Test: `tests/test_trabajos.py` y los casos de migración en `tests/test_decisiones.py`

**Interfaces:**
- **Produces, en `decisiones.py`:** la tabla `trabajo(id INTEGER PK AUTOINCREMENT, accion TEXT NOT NULL, curso TEXT, numero INTEGER, estado TEXT NOT NULL, progreso REAL NOT NULL DEFAULT 0, inicio TEXT NOT NULL, fin TEXT, error TEXT, registro TEXT NOT NULL DEFAULT '[]', temporal TEXT)`.
- **Produces, en `trabajos.py`:**
  - `Trabajo(BaseModel)`: `{id: int, accion: str, curso: str | None, numero: int | None, estado: Literal["en_marcha","hecho","error","interrumpido"], progreso: float, inicio: datetime, fin: datetime | None, error: str | None, registro: list[str]}`. `temporal` no se expone.
  - `class TrabajoEnMarcha(Exception)`.
  - `lanzar(bd_ruta: Path, accion: str, curso: str | None, numero: int | None, comando: list[str], cwd: Path, temporal: Path | None, destino: Path | None) -> Trabajo`:
    - inserta la fila y arranca un hilo con `subprocess.Popen(comando, cwd=cwd, stdout=PIPE, stderr=STDOUT, shell=False)`;
    - lee la salida en trozos (Remotion reescribe la línea con `\r`) y actualiza `progreso` y `registro` como mucho una vez por segundo, con su propia conexión;
    - al terminar con código 0, hace `os.replace(temporal, destino)` y pasa a `hecho`; con otro código, borra el temporal y pasa a `error`;
    - un `threading.Lock` de módulo, más la comprobación en la BD, garantiza que haya uno solo en marcha. Si hay otro → `TrabajoEnMarcha`.
  - `leer_trabajo(bd, id) -> Trabajo | None`.
  - `ultimo_trabajo(bd, accion, curso, numero) -> Trabajo | None`.
  - `interrumpir_huerfanos(bd) -> int`: los `en_marcha` pasan a `interrumpido`, se borra su `temporal` y devuelve cuántos.
  - `esperar(id, timeout: float) -> None`, solo para tests: hace `join` del hilo.

- [ ] **Step 1: Tests que fallan:**
  - **Migración:**
    - una base v2 con tareas y portadas pasa a la v3 conservando las filas y deja la copia `<bd>.v2`;
    - una v1 llega a la v3;
    - una v0 se crea directamente en la v3;
    - una v4 da `RuntimeError`;
    - si se fuerza un fallo al crear `trabajo`, sigue en la v2.
  - **Terminar bien:** `lanzar` con `[sys.executable, "-c", "import sys,time; [print(f'{i}/4', flush=True) or time.sleep(0.05) for i in range(1,5)]; open(sys.argv[1],'w').write('x')", <temporal>]` y `esperar` acaba en `hecho`, con `progreso == 1.0`, el destino creado y sin temporal.
  - **Terminar mal:** con un comando que sale con código 3 acaba en `error`, con «Remotion terminó con el código 3», y el temporal borrado.
  - **De uno en uno:** un segundo `lanzar` mientras corre uno lento → `TrabajoEnMarcha`.
  - **Registro:** con 100 líneas de salida, `registro` guarda las 40 últimas, y una línea de 2000 caracteres se corta a 500.
  - **Huérfanos:** una fila `en_marcha` con un temporal en disco pasa a `interrumpido` con `interrumpir_huerfanos`, el temporal se borra y después se puede lanzar otro.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS, más `ruff check` y `ruff format --check`.
- [ ] **Step 5: Commit** `Base de datos v3 y motor de trabajos de uno en uno`.

### Tarea 2: Lectura del teleprompter y vista previa (API)

**Files:**
- Create: `estudio_api/teleprompter.py` y `estudio_api/rutas_teleprompter.py`
- Modify: `estudio_api/estado.py` (hacer públicas `voz_grabada` y `camara_grabada`, sin cambiar su comportamiento), `estudio_api/app.py` (router) y `estudio_api/medios.py` (servir `.mp4` de `estudio/out/previas-grabacion/`, que ya lo cubre `TIPOS_MEDIO`; comprobarlo con un test)
- Test: `tests/test_teleprompter_api.py`

**Interfaces:**
- **Consumes:** la tarea 1; `carpeta_leccion`, `datos_curso` y `ruta_segura` de lectura y rutas.
- **Produces, modelos (con `extra="forbid"` en las entradas):**
  - `CueTeleprompter{texto: str, pausa: float}`: `pausa` vale 0 si falta y se limita a 0–30.
  - `EscenaTeleprompter{id, modo: Literal["voz","camara"], titulo, cues: list[CueTeleprompter], puntos: list[str], grabada: bool, toma: str | None, version_toma: int | None}`.
    - `toma` es la ruta pública `cursos/…/grabaciones/E03.wav`, solo si es de voz y existe.
    - `version_toma` es el `st_mtime_ns`, para romper la caché del `<audio>`.
  - `MontajeEscena{id, modo, inicio: int, duracion: int, cues: list[int]}`, en fotogramas, con `cues` = `desde ?? 0` de cada cue. `Montaje{fps: float, duracion: int, escenas: list[MontajeEscena]}`.
  - `EstadoPrevia{ruta: str | None, existe: bool, desactualizada: bool, version: int | None, trabajo: Trabajo | None}`.
    - `ruta` = `estudio/out/previas-grabacion/<guion>.mp4`.
    - `trabajo` = `ultimo_trabajo("previa-grabacion", curso, numero)`.
  - `Teleprompter{curso, numero, guion: str, titulo, version: str, escenas: list[EscenaTeleprompter], montaje: Montaje | None, previa: EstadoPrevia}`.
- **Produces, rutas:**
  - `GET /api/cursos/{curso}/lecciones/{numero}/teleprompter` → `Teleprompter`, o 404 si el curso o la lección no existen o no tienen guion.
    - Un `montaje.json` dañado o ilegible da `montaje: null`, no un 500.
  - `POST /api/cursos/{curso}/lecciones/{numero}/previa-grabacion` (cuerpo `{}`) → 202 `Trabajo`. Puede dar 404, 409 (sin montaje o con un trabajo en marcha) o 503 (sin npx).
  - `GET /api/trabajos/{id}` → `Trabajo` o 404. El id usa `Path(ge=1, le=2**63-1)`.

- [ ] **Step 1: Tests que fallan:**
  - **Fixture con E01 (cámara), E02 (animación), E03 (voz con `E03.wav`) y E04 (voz sin toma):**
    - el GET devuelve E01, E03 y E04, en ese orden;
    - E03 lleva `grabada: true`, `toma` y `version_toma`;
    - E01 lleva `puntos`;
    - `version` es el SHA-256 del JSON.
  - **Montaje:** con `montaje.json`, los inicios se acumulan (E01 0, E03 = duración de E01, …). Con un montaje roto da `montaje: null`.
  - **Previa:** con la previa más antigua que el montaje sale `desactualizada: true`.
  - **Ruta de la previa:** `GET /api/medios?ruta=estudio/out/previas-grabacion/react-04.mp4` con `Range` → 206.
  - **Lanzar:**
    - con `shutil.which` y el comando de la tarea 1 sustituidos por `monkeypatch` (el comando sale de una función `comando_previa(npx, temporal, guion) -> list[str]`, que tiene su propio test con la lista exacta de Global Constraints), el POST → 202 y el trabajo acaba `hecho`, con la previa en su sitio;
    - un segundo POST mientras corre → 409;
    - sin npx → 503;
    - sin montaje → 409.
  - **Seguridad:** el POST sin token → 401; `numero=0` → 422; `curso=../x` → 422 o 404, nunca 500.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS.
- [ ] **Step 5: Commit** `Lectura del teleprompter y vista previa como trabajo`.

### Tarea 3: Subida de tomas de voz (API)

**Files:**
- Modify: `estudio_api/seguridad.py` (límite por ruta) y `estudio_api/rutas_teleprompter.py`
- Create: `estudio_api/tomas.py`
- Test: `tests/test_tomas.py` y `tests/test_seguridad.py`, o el archivo de seguridad que ya exista

**Interfaces:**
- **Produces, en `seguridad.py`:** `LIMITES_POR_RUTA: list[tuple[str, re.Pattern[str], int]] = [("PUT", re.compile(r"^/api/cursos/[a-z0-9-]{1,40}/lecciones/[1-9][0-9]{0,2}/grabaciones/E[0-9]{2}$"), 209_715_200)]`.
  - Para esa ruta, el máximo de dígitos de `Content-Length` es 9 y el límite, ese. Para todas las demás no cambia nada.
- **Produces, en `tomas.py`:** `guardar_toma(config, curso, numero, escena, cuerpo: AsyncIterator[bytes], longitud: int) -> TomaGuardada{escena, ruta, version, bytes}`.
  - Valida que la escena sea `voz` en el guion y que exista la carpeta del curso. Crea `grabaciones/` si falta, dentro de `cursos_dir`.
  - Escribe a un temporal oculto, comprueba la cabecera RIFF/WAVE con los primeros 12 bytes y que lo escrito sea igual a `longitud`.
  - Después mueve la anterior a `tomas/` y hace `os.replace`, como dice Global Constraints. Si algo falla, borra el temporal y no toca nada más.
- **Produces, ruta:** `PUT /api/cursos/{curso}/lecciones/{numero}/grabaciones/{escena}` con `Content-Type: audio/wav` → 201 `TomaGuardada`.
  - Errores: 415 si el tipo es otro, 422 si no es un WAV o la escena no es de voz, 404 si la lección o la escena no existen y 413 si el cuerpo es demasiado grande.

- [ ] **Step 1: Tests que fallan:**
  - **Primera toma:** un WAV mínimo válido (44 bytes de cabecera y 1 s de silencio) en E04 → 201, el archivo existe y `tomas/` está vacía.
  - **Repetir:** dos subidas seguidas a E03 → `tomas/` tiene la toma original y la de la primera subida, con nombres distintos aunque se suban en el mismo segundo (`monkeypatch` del reloj).
  - **Fallos (Review Focus 1):** un cuerpo que no es un WAV → 422; `Content-Type: audio/mpeg` → 415; `Content-Length` mayor que el cuerpo (cortado) → 4xx. En los tres casos `E03.wav` queda byte a byte igual, `tomas/` sigue vacía y no hay archivos ocultos en `grabaciones/`.
  - **Escena:** subir a E01 (cámara) → 422; a E99 → 404.
  - **Límites:** 300 KB en esta ruta → 201; 300 KB en `PUT /api/publicar/…` → 413; un `Content-Length` de 209715201 → 413 sin leer el cuerpo; sin token → 401.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS.
- [ ] **Step 5: Commit** `Subida de tomas de voz sin perder las anteriores`.

### Tarea 4: Editar los textos del guion (API)

**Files:**
- Create: `estudio_api/guion_textos.py`
- Modify: `estudio_api/rutas_teleprompter.py`
- Test: `tests/test_guion_textos.py`

**Interfaces:**
- **Consumes:** `escribir_atomico` y el `version` de la tarea 2.
- **Produces:**
  - `CambiosTextos{version: str (64 hex), escenas: list[CambioEscena]}`, con `CambioEscena{id: str, cues: list[str] | None = None, puntos: list[str] | None = None}` y `extra="forbid"`. La lista de escenas tiene de 1 a 200 elementos.
  - `aplicar_textos(guion: dict, cambios: CambiosTextos) -> dict`, una función pura con las reglas de Global Constraints. Si algo no cumple → `ValueError` con un mensaje en castellano.
  - `PUT /api/cursos/{curso}/lecciones/{numero}/guion/textos` → 200 `Teleprompter` actualizado. Puede dar 409 (versión), 422 (reglas) o 404.
  - Este endpoint es el que reutilizará la pestaña Guion en la fase 5.

- [ ] **Step 1: Tests que fallan:**
  - **Cambiar una frase:** cambiar la frase 2 de E03 deja intactos el resto del JSON, otros campos como `paso` o `pausa` y las demás escenas.
    - El archivo acaba en `\n`, usa sangría de 2 espacios y conserva «ñ» y «🎬» tal cual.
    - Aparece `react-04.json.antes-de-editar`, y una segunda edición no lo cambia.
  - **Rechazos:** con una frase de menos, un punto de más, un texto vacío o con `\n`, o una escena desconocida → 422, y el archivo no cambia.
  - **Versión (Review Focus 3):** se modifica el archivo en disco tras el GET y el PUT con la versión vieja → 409 con el mensaje exacto, y el archivo queda como lo dejó el cambio externo.
  - **Animación:** un `CambioEscena` de una escena de animación → 422.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS.
- [ ] **Step 5: Commit** `Editar los textos del guion con control de versión`.

### Tarea 5: Lógica del teleprompter portada (web, funciones puras)

**Files:**
- Create: `src/lib/teleprompter/trocear.ts`, `src/lib/teleprompter/ritmo.ts`, `src/lib/teleprompter/wav.ts` y `src/lib/teleprompter/previa.ts`
- Test: los `*.test.ts` de cada uno

**Interfaces:**
- **Produces:**
  - `trocear(texto: string): { t: string; dichas: string[] }[]`, `leerNumero(ws: string[], i: number): { valor: number; fin: number } | null` y `NUMEROS`. Es una traducción fiel a TypeScript de la página actual; no se mejora ni se cambia la heurística.
  - `calcularPlan(cues: { texto: string; pausa: number }[], ppm: number): { pasos: Paso[]; total: number }`.
    - `Paso = { c: number; p?: number; pausa?: true; desde: number; hasta: number }`.
    - También exporta `ESPERA` y `mmss(s: number): string`.
  - `codificarWav(canales: Float32Array[], frecuencia: number): ArrayBuffer`: mono, 16 bits, mezcla de canales y recorte a [-1, 1], como `aWav`.
  - `objetivoLectura({ t, plan, escenaMontaje, fps, iniciosFrases })` y `objetivoToma({ tiempoToma, duracionToma, escenaMontaje, fps })`. Las dos devuelven `{ tiempo: number; ritmo: number; pausar: boolean }`, con el ritmo limitado a 0.25–4, y son la lógica de `sincronizarPrevia` y `previaConToma` sin tocar el DOM.

- [ ] **Step 1: Tests que fallan** (en todos, `t` es lo que muestra el teleprompter):
  - **Números:**
    - «dos mil veintiséis.» → `2026.`;
    - «diecinueve punto tres» → `19.3`;
    - «treinta y cinco» → `35`;
    - «ciento veinte» → `120`.
    - «uno, dos» quedan aparte;
    - «uno» suelto en mitad de una frase no cambia, y «Uno:» → `1:`.
    - «dos tres» quedan separados.
  - **Nombres:**
    - «App punto jsx» → `App.jsx`;
    - «archivos punto jsx» → `archivos` y `.jsx`;
    - «punto barra» → `./`;
    - «el punto de» no cambia;
    - «Math punto random» → `Math.random`.
  - **`dichas`:** «dos mil veintiséis» guarda las tres palabras.
  - **`calcularPlan`:** a 150 ppm, una frase de dos palabras cortas termina con la espera de frase. Una cue con `pausa: 2` añade un paso `pausa`. El total crece si baja el ritmo.
  - **`codificarWav`:** con 2 canales de 3 muestras, el resultado tiene 44 + 6 bytes, `RIFF`/`WAVE`, mono, 16 bits y la frecuencia indicada. Una muestra de 1.5 se recorta a 32767.
  - **`objetivoLectura`:** con el mismo número de frases que el montaje, la frase 2 se mapea a su tramo. Con distinto número, se reparte la escena entera. Pasado el final → `pausar: true`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** lint y tests.
- [ ] **Step 5: Commit** `Lógica del teleprompter: ritmo, números, nombres, WAV y sincronía`.

### Tarea 6: Datos, acciones y subida de tomas (web)

**Files:**
- Modify: `src/lib/tipos.ts` y `src/lib/api.ts`
- Create: `src/lib/acciones-teleprompter.ts` (`"use server"`), `src/lib/trabajos.ts` y `src/app/grabar/[curso]/[numero]/[escena]/route.ts`
- Test: `src/lib/acciones-teleprompter.test.ts`, `src/lib/trabajos.test.ts` y `src/app/grabar/[curso]/[numero]/[escena]/route.test.ts`

**Interfaces:**
- **Consumes:** las rutas de las tareas 2 a 4.
- **Produces:**
  - En `tipos.ts`: `Teleprompter`, `EscenaTeleprompter`, `Montaje`, `EstadoPrevia`, `Trabajo` y `TomaGuardada`, que reflejan los modelos de la API.
  - En `api.ts`: `obtenerTeleprompter(curso: string, numero: number): Promise<Teleprompter | null>`, que da `null` en un 404.
  - En `acciones-teleprompter.ts`, con el patrón de `acciones.ts` (validar, reconstruir, comprobar host y origin, `detail` en texto y devolver `{ ok, … }`):
    - `guardarTextos(curso, numero, version, escenas): Promise<{ ok: true; teleprompter: Teleprompter } | { ok: false; mensaje: string; conflicto?: true }>`;
    - `generarPreviaGrabacion(curso, numero): Promise<{ ok: true; trabajo: Trabajo } | { ok: false; mensaje: string }>`.
  - En `trabajos.ts` (navegador): `leerTrabajo(id: number): Promise<Trabajo>`, que lee la URL pública de la API como `urlMedio`.
  - **`route.ts`, con `PUT` únicamente:**
    - valida `curso`, `numero` y `escena` con los patrones;
    - exige `origin === ORIGEN_ESTUDIO`, `host === HOST_ESTUDIO`, `content-type: audio/wav` y un `content-length` de 1 a 209715200;
    - reenvía `request.body` en streaming a la API, con `X-Estudio-Token`, el mismo `Content-Length`, `duplex: "half"` y `redirect: "error"`;
    - devuelve el estado y el JSON de la API.
    - Lo que esté mal se rechaza sin llamar a la API: 400, 403, 411, 413 o 415.

- [ ] **Step 1: Tests que fallan:**
  - **`route.ts`:**
    - con un origin ajeno → 403 sin `fetch`;
    - sin `content-length` → 411;
    - con 209715201 → 413;
    - con `escena=E1` → 400;
    - con una válida llama a `fetch` con el token, el método `PUT` y el cuerpo, y devuelve el 201.
    - El token nunca aparece en la respuesta.
  - **`guardarTextos`:**
    - un texto con salto de línea → `ok: false` sin `escribir`;
    - un 409 → `ok: false, conflicto: true` con el mensaje de la API;
    - uno válido llama a `escribir(".../guion/textos", {version, escenas}, "PUT")`.
  - **`generarPreviaGrabacion`:** un 409 muestra «Ya hay un trabajo en marcha».
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** lint, tests y build.
- [ ] **Step 5: Commit** `Teleprompter: lecturas, acciones y subida de tomas`.

### Tarea 7: Teleprompter de voz (web)

**Files:**
- Modify: `src/app/teleprompter/page.tsx` y la página de la lección (el botón «Abrir en el teleprompter» pasa a ser un `<Link>` a `/teleprompter?curso=…&leccion=…`)
- Create, en `src/components/teleprompter/`: `Teleprompter.tsx` (cliente), `BarraAjustes.tsx`, `BarraEscenas.tsx`, `TextoConRitmo.tsx` y `PieControles.tsx`
- Create: `src/lib/teleprompter/preferencias.ts` y `src/lib/teleprompter/grabadora.ts`
- Test: `Teleprompter.test.tsx`, `BarraEscenas.test.tsx` y `preferencias.test.ts`

**Interfaces:**
- **Consumes:** las tareas 5 y 6.
- **Produces:**
  - **Página:** lee los parámetros, pide `obtenerTeleprompter` y pinta `<Teleprompter datos=… lecciones=…>`. Sin parámetros, aplica la regla de URL de Global Constraints: el componente cliente hace `router.replace` a la preferencia guardada.
  - **Ajustes:** selector de lección («React · 4: Título»), ritmo con su valor en ppm, letra, micrófono (con los dispositivos tras el primer permiso) y la barra de nivel (verde, roja si el pico pasa de 0.95).
  - **Escenas:** botones con el id; los de voz llevan ✓ si están grabados y la actual va resaltada. Se abre en la primera escena de voz sin grabar.
  - **Texto:** cada frase va troceada con `trocear`, con un `<span>` por palabra y la barra de «⏸ Pausa para pensar: sigue en silencio».
    - La animación usa `requestAnimationFrame` y **cambia clases por refs, sin `setState` en cada fotograma**.
    - Mantiene la palabra actual al 35 % de la altura.
  - **Controles:** Ensayar, ● Grabar, ■ Parar, ↺ Repetir, Editar texto, el reloj `m:ss`, el estado y el reproductor de la toma.
    - Las cuentas atrás, los textos de estado y los atajos son los de Global Constraints.
  - **`grabadora.ts`:**
    - `abrirMicro(deviceId)` usa `getUserMedia` con `echoCancellation`, `noiseSuppression` y `autoGainControl` desactivados, y un canal;
    - `grabar(flujo)` usa MediaRecorder con el primer tipo admitido de `audio/webm;codecs=opus`, `audio/webm` y `audio/mp4`, a 256 kbps y en trozos de 250 ms;
    - `aWav(blob, contexto)` decodifica y llama a `codificarWav`;
    - `subirToma(curso, numero, escena, wav)` hace `fetch("/grabar/…", { method: "PUT", body: wav, headers: { "Content-Type": "audio/wav" } })`.
  - **Tras guardar:** «Guardada: E03.wav. Escúchala o pasa a la siguiente con →.», la barra de escenas se refresca con `router.refresh()` y la toma se carga con `urlMedio(toma)` y `&v=<version_toma>`.

- [ ] **Step 1: Tests que fallan** (jsdom, con `MediaRecorder` y `getUserMedia` simulados con `vi.stubGlobal`):
  - La barra muestra `E03 ✓` y `E04`, sin la escena de animación, y abre en E04.
  - «App punto jsx» sale como `App.jsx`, y un texto con `<script>` se pinta como texto.
  - Espacio llama a ensayar y muestra la cuenta atrás «3 / ensayo: no se graba».
  - → cambia a la escena siguiente, y no lo hace con el foco en un `<input>`.
  - Si se deniega el micrófono → «No se puede usar el micrófono: …» y los botones vuelven a su estado.
  - Grabar y después Parar llama a `subirToma` con un `Blob` de tipo `audio/wav`. Si la subida falla, sale «No se pudo guardar: …».
  - Las preferencias se leen y se guardan con `localStorage` caído (lanza al acceder) sin romper la página.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** lint, tests y build.
- [ ] **Step 5: Commit** `Teleprompter: lectura con ritmo y grabación de voz`.

### Tarea 8: Cámara, edición del texto y vista previa (web)

**Files:**
- Create: `src/components/teleprompter/PanelPrevia.tsx` y `src/components/teleprompter/EditorTextos.tsx`
- Modify: `Teleprompter.tsx`, `BarraEscenas.tsx` y `PieControles.tsx`
- Test: `PanelPrevia.test.tsx`, `EditorTextos.test.tsx` y casos de cámara en `Teleprompter.test.tsx`

**Interfaces:**
- **Consumes:** `objetivoLectura`, `objetivoToma`, `guardarTextos`, `generarPreviaGrabacion` y `leerTrabajo`.
- **Produces:**
  - **Escena a cámara:**
    - lleva 🎥 en la barra (✓ si `grabada`), la etiqueta «Cámara · con tus palabras» y la línea «🎥 Se graba con la cámara · horizontal»;
    - el botón «Ver solo puntos / Ver guion con ritmo» cambia la vista, que se recuerda en las preferencias;
    - con guion, los puntos van en la franja fija de arriba y la frase de referencia se mueve al ritmo;
    - Grabar está desactivado y «Empezar» hace la cuenta atrás «dale a grabar en la cámara»;
    - el botón «⬆ Entregar los vídeos de la cámara» sale desactivado, con el título «Llega en la fase 6».
  - **Edición:**
    - «Editar texto» pasa las frases (o los puntos) a `textarea` de una línea, con «Guardar texto» y «Cancelar», y desactiva Ensayar y Grabar;
    - guardar llama a `guardarTextos` con la `version` del teleprompter cargado;
    - un conflicto muestra el mensaje junto a «Recargar», sin perder lo escrito.
  - **Vista previa:**
    - `<video muted playsInline>` con `urlMedio(previa.ruta)` y `&v=<version>`, colocado al inicio de la escena;
    - mientras se lee, la sincronía va con `objetivoLectura`, y al escuchar la toma, con `objetivoToma`.
    - Sus estados son:
      - «Esta lección aún no tiene montaje.»;
      - «Generar vista previa»;
      - «Generando la vista previa… N %», con la barra, consultando `leerTrabajo` cada 2 s;
      - «Falló la última vez (…).»;
      - «el montaje ha cambiado: regénerala», con un botón «Regenerar».
    - Cuando el trabajo acaba en `hecho`, se hace `router.refresh()`.

- [ ] **Step 1: Tests que fallan:**
  - **Cámara:** la escena muestra 🎥 y sus puntos; Grabar está desactivado y Entregar también, con su título.
  - **Edición:**
    - cambiar la frase 1 y guardar llama a `guardarTextos("react", 4, <version>, [{ id: "E03", cues: [...] }])` con todas las frases de la escena;
    - con un conflicto, el texto escrito sigue y aparece «Recargar».
  - **Previa:**
    - sin montaje sale el texto de vacío;
    - con un trabajo `en_marcha` al 40 % muestra «40 %», y al volver `hecho` llama a `router.refresh`;
    - con `desactualizada` aparece «Regenerar»;
    - el tamaño «Oculta» quita el panel y el margen del texto.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** lint, tests y build.
- [ ] **Step 5: Commit** `Teleprompter: escenas a cámara, edición del texto y vista previa`.

### Tarea 9: Verificación real y cierre

- [ ] **Step 1: Paridad (en local, sin comitear).** Un script en `~/tech-study-herramientas` ejecuta el `trocear` de la página actual y el de la tarea 5 sobre todas las cues de `ESTUDIO_DIR/lecciones/*.json` y compara los resultados `t` y `dichas`. El resultado tiene que ser 0 diferencias.
- [ ] **Step 2: Arranque.** Hacer clones APFS de `Cursos youtube/REACT` y de `ESTUDIO_DIR` (con su `node_modules`), y una copia de la BD real v2, en el scratchpad. Arrancar la API apuntando a ellos y la web con `npm run estudio`.
- [ ] **Step 3: Recorrido con Playwright**, en Chromium con `--use-fake-ui-for-media-stream --use-fake-device-for-media-stream`:
  - **BD:** la copia migra a la v3 y deja `.v2`.
  - **Entrada:** «Abrir en el teleprompter» desde la lección 4 abre esa lección.
  - **Voz:**
    - ensayar una escena de voz;
    - grabar 3 s y parar: el WAV aparece en el clon y la escena queda ✓;
    - repetirla: la anterior está en `tomas/`;
    - al escuchar la toma, la vista previa se mueve.
  - **Cámara:** la escena muestra 🎥 y los puntos.
  - **Texto:** editar una frase y guardar. El JSON del clon cambia solo en esa frase y existe `.antes-de-editar`. Si se cambia el JSON a mano y se vuelve a guardar → mensaje de conflicto.
  - **Previa:** generar la vista previa en el clon: el progreso avanza y acaba en `hecho`.
  - **Calidad:** 0 errores de consola y nada de scroll horizontal a 390 px.
- [ ] **Step 4:** `/security-review` en los dos repos, con atención a la subida y al proceso. Guardar los informes y arreglar lo que salga.
- [ ] **Step 5:** Revisión final de las dos ramas con un revisor nuevo, y arreglos.
- [ ] **Step 6:** Push y PR de cada repo con la CI en verde, con el permiso del autor. Merge solo con su visto bueno.

## Fuera de esta fase

- **Entrega de tomas a cámara y ganchos verticales:** fase 6.
- **Resto de acciones** (alinear voz, montaje, render, LUFS, shorts…), su panel y la marca «guion cambiado: regenerar el montaje»: fase 5, sobre el motor de la tarea 1.
- **Teleprompter de los ganchos de shorts (`TELEPROMPTER.txt`):** la página actual no lo tiene; se valorará con la fase 6.
- **Retirar la página actual:** solo cuando el autor confirme que la app la cubre.
