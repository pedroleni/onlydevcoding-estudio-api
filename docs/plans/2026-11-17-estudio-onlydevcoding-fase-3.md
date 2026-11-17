# Estudio OnlyDevCoding · Fase 3 (Tareas) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un gestor de tareas del canal. La app abre en las tareas de hoy. Hay vista de día y de semana, con filtros por curso y por tipo, y cada tarea puede enlazarse a una lección, una pieza y una red. «Publicar…» abre la pestaña Publicar, y marcar algo como publicado completa su tarea.

**Architecture:**
- **Datos:** las tareas, los tipos de tarea y los cursos dados de alta en la app viven en la misma base SQLite de la API. El esquema pasa a la versión 2, con una migración que conserva los datos de la fase 2.
- **Validación:** la API valida los enlaces contra lo que hay en disco al crear la tarea. Al leerlas, marca como roto el enlace que ya no existe.
- **Escrituras:** la web escribe como en la fase 2. Server Action → `escribir()` (server-only, con `X-Estudio-Token`) → API. Ahora también con `POST` y `DELETE`.

**Tech Stack:**
- **API:** Python 3.14, uv, FastAPI, Pydantic v2, `sqlite3` de la biblioteca estándar, pytest, ruff.
- **Web:** Next.js 16 (App Router, `cacheComponents`, Server Actions), TypeScript, Tailwind, Vitest y Testing Library.
- **Verificación:** Playwright, la hace Claude sobre un clon APFS de los datos y una copia de la BD.

**Spec:** `docs/specs/2026-11-16-estudio-onlydevcoding-design.md`, secciones «Decisiones del autor → Tareas», «Decisiones mías» (tareas creadas por el autor, sueltas, cursos dados de alta, abrir en hoy, enlace roto), «Datos → Base de datos local» y «Pantallas → Tareas».

**Boceto aprobado:** `tareas.html` de `.superpowers/brainstorm/` del proyecto de bocetos. Muestra dos cosas:
- **Vista de día:** «‹ dom 15 · lun 16 nov · mar 17 ›», «+ Tarea» y las tareas agrupadas por curso y después por tipo, con un punto de color. Cada tarea lleva su casilla, el texto y la hora opcional.
- **Vista de semana:** columnas lun…, con las tareas en corto. El color indica el tipo y arriba está el filtro por curso.

**Base:** la fase 2, integrada en `main`. Hay que leer el registro `.superpowers/sdd/2026-11-16-estudio-onlydevcoding-fase-2/progress.md` (Rulings y minors diferidos). Rama `feat/fase-3` en cada repo.

## Contexto de ejecución

Igual que en las fases 1 y 2:
- **Codex** implementa (sin red y sin escribir en `.git`). Si no tiene cuota, implementa Claude.
- **Claude** hace los commits (sin `Co-Authored-By` ni «Generated with»), verifica con Playwright sobre un clon y encarga las revisiones.
- Los commits nuevos se firman con el email `noreply` de GitHub (`user.email` local).

## Global Constraints

- **Las de las fases 1 y 2 siguen en vigor:**
  - local en `127.0.0.1`, con Host, Origin y `Sec-Fetch-Site`;
  - toda escritura con `X-Estudio-Token`, cuerpo de hasta 256 KB y `Content-Length` obligatorio;
  - CORS solo para `GET`;
  - nada privado en los repos;
  - castellano de España, tema oscuro y redes en el orden YouTube, Instagram, TikTok, LinkedIn.
- **Esquema de la BD:** `PRAGMA user_version = 2`.
  - Desde 0 se crea todo, desde 1 se migra y la 2 se abre tal cual. Cualquier otra versión da `RuntimeError`.
  - La creación y la migración van en **una sola transacción** (`BEGIN` explícito; SQLite admite DDL transaccional). Si fallan a medias, la base queda como estaba.
- **Tarea:**
  - `fecha`: `YYYY-MM-DD`, y tiene que ser una fecha real.
  - `hora`: opcional, `HH:MM` entre `00:00` y `23:59`.
  - `texto`: se recorta; entre 1 y 300 caracteres y sin saltos de línea.
  - `tipo`: id de un tipo que exista.
  - `hecha`: booleano.
- **Enlace de una tarea (opcional y jerárquico):** `curso` → `numero` → `pieza` → `red`.
  - No puede haber `numero` sin `curso`, ni `pieza` sin `numero`, ni `red` sin `pieza`.
  - Patrones: curso `^[a-z0-9-]{1,40}$`; número de 1 a 999; pieza `^(leccion|reel-salida(-[1-9][0-9]*)?|short-[1-9][0-9]*)$`; red `youtube|instagram|tiktok|linkedin`.
  - Se pueden enlazar los cursos de la app que no tienen carpeta, pero solo a nivel de curso.
- **Tipos de tarea:**
  - `id` `^[a-z0-9-]{1,30}$`, `nombre` de 1 a 40 caracteres y `orden` entero.
  - `color`, uno de: `#299BC6`, `#4BC98C`, `#E8A33D`, `#E5534B`, `#A371F7`, `#6CCBEF`, `#F778BA`, `#9B9BA4`.
  - Al crear la base se siembran, en este orden: `preparar` «Preparar» `#A371F7`, `grabar` «Grabar» `#E5534B`, `editar` «Editar» `#E8A33D`, `publicar` «Publicar» `#4BC98C` y `otro` «Otro» `#9B9BA4`.
- **Cursos de la app:** el `id` sigue el patrón de curso y el `nombre` tiene de 1 a 60 caracteres.
  - No se puede dar de alta un id que ya exista en disco (409).
  - Si más adelante aparece en disco una carpeta con ese id, manda la del disco y el curso de la app deja de listarse.
- **Rango de lectura de tareas:** `desde ≤ hasta` y como mucho 62 días, inclusive. Fuera de eso, 422.
  - Las atrasadas son las pendientes con fecha anterior a `desde`: como mucho 200, ordenadas por fecha.
- **Fechas en la web:**
  - «Hoy» es la fecha local del Mac en el momento de la petición.
  - La semana va de lunes a domingo.
  - Se muestran en castellano con `Intl.DateTimeFormat("es-ES")`, por ejemplo «lun 16 nov».
- **URL de la vista:** `/tareas?vista=dia|semana&dia=YYYY-MM-DD&curso=<id>|sin-curso&tipo=<id>`. Un parámetro que no es válido se ignora y se usa el valor por defecto: día, hoy, todos y todos.
- **Orden dentro de la vista de día:**
  - Cursos: primero los de disco en su orden, después los de la app y al final «Sin curso».
  - Dentro de cada curso, tipos por `orden`.
  - Dentro de cada tipo, por hora (las que no tienen van al final) y después por id.

## Review Focus

1. **La base de la fase 2 ya existente (versión 1, con portadas y estados) se migra a la 2 sin perder ninguna fila.** Si la migración falla a mitad, queda en la versión 1 intacta. Test en la tarea 1.
2. **Una tarea enlazada a una pieza o lección que ya no está en disco** (renombrada o borrada) sigue saliendo, con el enlace marcado como roto y sin 500. Test en la tarea 3.
3. **Una tarea pendiente de un día anterior no desaparece:** en la vista de hoy sale en el grupo «Atrasadas». Tests en las tareas 3 y 6.
4. **Fechas límite:** un cambio de mes, una semana que cruza el año (lun 29 dic 2025 → dom 4 ene 2026) y un 29 de febrero (válido en 2028 y no en 2026). Tests en las tareas 1 y 6.
5. **Borrar un tipo con tareas, o un curso de la app con tareas:** responde 409 y no deja tareas huérfanas. Tests en las tareas 2 y 3.

---

### Tarea 1: Esquema v2 y almacén de tareas (API)

**Files:**
- Modify: `estudio_api/decisiones.py` (`abrir_bd`)
- Create: `estudio_api/tareas.py`
- Test: `tests/test_tareas_bd.py` (y los casos de migración en `tests/test_decisiones.py`)

**Interfaces:**
- **Produces, en `estudio_api/tareas.py`:**
  - Modelos Pydantic, todos con `extra="forbid"`:
    - `EnlaceTarea(curso: str, numero: int | None = None, pieza: str | None = None, red: str | None = None)`, con la jerarquía de Global Constraints.
    - `TareaNueva(fecha: date, hora: str | None = None, texto: str, tipo: str, enlace: EnlaceTarea | None = None)`.
    - `Tarea(TareaNueva)`, con `id: int`, `hecha: bool` y `hecha_en: datetime | None`.
    - `TipoTarea(id: str, nombre: str, color: str, orden: int)`.
    - `CursoApp(id: str, nombre: str)`.
  - Funciones (todas reciben `bd: sqlite3.Connection` y usan parámetros `?`):
    - `crear_tarea(bd, nueva: TareaNueva) -> Tarea`
    - `editar_tarea(bd, id: int, nueva: TareaNueva) -> Tarea | None`
    - `marcar_hecha(bd, id: int, hecha: bool) -> Tarea | None`: pone `hecha_en` a ahora, o a `None` al desmarcar.
    - `borrar_tarea(bd, id: int) -> bool`
    - `tareas_entre(bd, desde: date, hasta: date) -> list[Tarea]`
    - `tareas_atrasadas(bd, antes_de: date, limite: int = 200) -> list[Tarea]`
    - `completar_tareas_de_red(bd, curso: str, numero: int, pieza: str, red: str) -> int`: marca como hechas las pendientes cuyo enlace coincide exactamente y devuelve cuántas.
    - `tipos(bd) -> list[TipoTarea]`, `crear_tipo`, `editar_tipo` y `borrar_tipo(bd, id) -> Literal["borrado","no_existe","en_uso"]`.
    - `cursos_app(bd) -> list[CursoApp]`, `crear_curso_app` y `borrar_curso_app(bd, id) -> Literal["borrado","no_existe","en_uso"]`.
- **Produces, en `decisiones.py`:** `abrir_bd` crea o migra hasta la versión 2. Tablas nuevas:
  - `tipo_tarea(id PK, nombre, color, orden)`
  - `curso_app(id PK, nombre)`
  - `tarea(id INTEGER PK AUTOINCREMENT, fecha, hora, texto, tipo REFERENCES tipo_tarea(id), curso, numero, pieza, red, hecha INTEGER NOT NULL DEFAULT 0, hecha_en)`, con índice por `fecha`.

- [ ] **Step 1: Tests que fallan:**
  - **Base v0:** al abrirla queda en la versión 2, con los 5 tipos sembrados en su orden.
  - **Base v1 con portadas y estados de ejemplo:** tras abrirla está en la versión 2 y conserva todas las filas. Si se fuerza un fallo a mitad de la migración (`monkeypatch` sobre la sentencia de siembra), sigue en la versión 1 con sus filas y sin tablas nuevas.
  - **Versión 3:** `RuntimeError`.
  - **Validación:**
    - `TareaNueva` con fecha `2026-02-29` → `ValidationError`; con `2028-02-29` es válida.
    - Una hora `24:00` → `ValidationError`.
    - Un texto vacío, de solo espacios, con salto de línea o de 301 caracteres → `ValidationError`.
    - Enlaces con `pieza` sin `numero`, o con `red` sin `pieza` → `ValidationError`.
  - **Texto exacto:** `crear_tarea` con texto `Grabar «gancho» 🎬 <b>x</b>` lo devuelve tal cual (recortado), con un `id`.
  - **Rangos:** `tareas_entre(2025-12-29, 2026-01-04)` devuelve las de los dos años y no las del 28 de diciembre. `tareas_atrasadas(hoy)` devuelve solo las pendientes anteriores a hoy, por fecha.
  - **Hecha:** `marcar_hecha(True)` rellena `hecha_en` y `marcar_hecha(False)` lo vacía.
  - **Completar por red:** con dos tareas enlazadas a (react, 4, reel-salida, instagram) y una a tiktok, `completar_tareas_de_red(...instagram)` devuelve 2 y deja la de tiktok pendiente.
  - **Borrados con dependencias:** `borrar_tipo("grabar")` con una tarea de ese tipo → `"en_uso"`; sin tareas → `"borrado"`. `borrar_curso_app` igual con una tarea enlazada.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS, más `ruff check` y `ruff format --check`.
- [ ] **Step 5: Commit** `Base de datos v2 con tareas, tipos y cursos de la app`.

### Tarea 2: Cursos de la app (API)

**Files:**
- Modify: `estudio_api/modelos.py` (`Curso`), `estudio_api/lectura.py` (`leer_cursos`) y `estudio_api/rutas_api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- **Consumes:** `cursos_app`, `crear_curso_app` y `borrar_curso_app` (tarea 1).
- **Produces:**
  - `Curso` pasa a `{id, nombre, carpeta: str | None, lecciones: int, en_disco: bool}`.
  - `GET /api/cursos` devuelve primero los de disco y después los de la app que no chocan con ninguno de disco (`carpeta: null`, `lecciones: 0`, `en_disco: false`).
  - `POST /api/cursos` con cuerpo `CursoApp`: devuelve 201 con el `Curso`, o 409 si el id ya existe en disco o en la app.
  - `DELETE /api/cursos/{curso}`: 204, 404 si no es un curso de la app y 409 si tiene tareas.
  - `GET /api/cursos/{curso}/lecciones`: devuelve `[]` (200) para un curso de la app, o de disco, sin lecciones. Era el minor M11 diferido de la fase 1. Un curso que no existe sigue dando 404.

- [ ] **Step 1: Tests que fallan:**
  - Dar de alta `python` «Python»: el GET lo lista después de `react`, con `en_disco: false`.
  - Dar de alta `react`, que existe en disco → 409.
  - Un `POST` sin token → 401.
  - `GET /api/cursos/python/lecciones` → 200 `[]`; `GET /api/cursos/no-existe/lecciones` → 404.
  - Si se crea en disco la carpeta `PYTHON/` tras darlo de alta, sale una sola vez, con `en_disco: true`.
  - `DELETE` de `python` con una tarea enlazada → 409, y la tarea sigue; sin tareas → 204.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS.
- [ ] **Step 5: Commit** `Cursos dados de alta en la app`.

### Tarea 3: API de tareas y tipos

**Files:**
- Create: `estudio_api/rutas_tareas.py` y `estudio_api/vista_tareas.py`
- Modify: `estudio_api/app.py` (registrar el router)
- Test: `tests/test_tareas_api.py`

**Interfaces:**
- **Consumes:** tarea 1; de `lectura.py`, `leer_cursos`, `leer_lecciones` (títulos de lección) y `leer_leccion(config, curso, numero, bd)` (títulos de las piezas en `Leccion.piezas`).
- **Produces:**
  - `TareaVista(Tarea)`, con `enlace_vista: EnlaceVista | None`.
    - `EnlaceVista = {curso_nombre: str | None, leccion_titulo: str | None, pieza_titulo: str | None, roto: bool}`.
    - Lo calcula `vista_tareas.py`, que lee cada curso y cada lección una sola vez por petición, con una caché local en un diccionario.
  - `GET /api/tareas?desde=YYYY-MM-DD&hasta=YYYY-MM-DD&atrasadas=true|false` devuelve `{tareas: list[TareaVista], atrasadas: list[TareaVista]}`. `atrasadas` va vacía si no se pide.
  - `POST /api/tareas` (`TareaNueva`) → 201 `TareaVista`.
    - Valida el enlace contra el disco: que exista el curso (de disco o de la app); que exista la lección, solo en cursos de disco; y que exista la pieza en `leer_leccion(...).piezas`. Si algo no existe → 422 con un `detail` en castellano.
    - También da 422 si el tipo no existe.
  - `PUT /api/tareas/{id}` (`TareaNueva`) → `TareaVista`, o 404.
  - `PUT /api/tareas/{id}/hecha` (`{"hecha": bool}`) → `TareaVista`, o 404.
  - `DELETE /api/tareas/{id}` → 204, o 404.
  - `GET /api/tipos-tarea` → `list[TipoTarea]` por `orden`.
  - `POST /api/tipos-tarea` → 201, o 409 si el id ya existe.
  - `PUT /api/tipos-tarea/{id}` (`nombre`, `color`, `orden`) → 200 o 404.
  - `DELETE /api/tipos-tarea/{id}` → 204, 404 o 409 si está en uso.

- [ ] **Step 1: Tests que fallan:**
  - **Rango:** crear tareas el lunes y el domingo de una semana y el lunes siguiente. El GET de esa semana devuelve las dos primeras. Un rango de 63 días, o con `hasta < desde`, → 422.
  - **Atrasadas:** una tarea pendiente de ayer, otra hecha de ayer y otra de hoy. Con `atrasadas=true` y `desde=hoy`, `atrasadas` trae solo la pendiente de ayer.
  - **Enlace roto:** crear una tarea enlazada a (react, 4, reel-salida, instagram) y borrar después en disco el reel del fixture. El GET da 200 con `enlace_vista.roto == true`, y la tarea sigue ahí. Lo mismo si se renombra la carpeta de la lección.
  - **Enlace inválido al crear:** con la lección 99 → 422; con la pieza `short-7`, que no existe → 422; con el curso de la app `python` y `numero` → 422.
  - **Enlace válido:** `enlace_vista` trae el título de la lección y el de la pieza.
  - **Tipos:** `DELETE /api/tipos-tarea/grabar` con una tarea de ese tipo → 409, y la tarea sigue.
  - **Seguridad:** `POST` y `DELETE` sin token → 401. Un `Origin` ajeno → 403. Un cuerpo con un campo extra → 422.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS.
- [ ] **Step 5: Commit** `API de tareas y tipos de tarea`.

### Tarea 4: Marcar como publicado completa la tarea (API)

**Files:**
- Modify: `estudio_api/rutas_publicar.py` (`cambiar_estado`)
- Test: `tests/test_publicar_api.py`

**Interfaces:**
- **Consumes:** `completar_tareas_de_red` (tarea 1).
- **Produces:** cuando `cambiar_estado` guarda `publicado`, en la misma conexión llama a `completar_tareas_de_red(curso, numero, pieza, red)`. Pasar a `programado` o a `pendiente` no reabre ni completa nada.

- [ ] **Step 1: Tests que fallan:**
  - Una tarea pendiente enlazada a (react, 4, leccion, youtube): al poner YouTube en `publicado` queda hecha, con `hecha_en`.
  - Otra enlazada solo a (react, 4) sigue pendiente.
  - Volver a `pendiente` deja la tarea hecha.
  - Pasar a `programado` no la completa.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS.
- [ ] **Step 5: Commit** `Publicar una pieza completa sus tareas`.

### Tarea 5: Lecturas y acciones de tareas (web)

**Files:**
- Modify: `src/lib/api-escritura.ts`, `src/lib/api.ts` y `src/lib/tipos.ts`
- Create: `src/lib/acciones-tareas.ts` (`"use server"`) y `src/lib/fechas.ts`
- Test: `src/lib/acciones-tareas.test.ts` y `src/lib/fechas.test.ts`

**Interfaces:**
- **Consumes:** la API de las tareas 2 y 3.
- **Produces:**
  - `escribir(ruta, cuerpo, metodo: "PUT" | "POST" | "DELETE" = "PUT")`. Un `DELETE` envía el cuerpo `{}`, porque la API exige `Content-Length`. Lo demás no cambia: token, límite de 256 KB y `redirect: "error"`.
  - En `tipos.ts`:
    - `Curso` con `carpeta: string | null` y `en_disco: boolean`.
    - `TareaVista`, `EnlaceTarea`, `EnlaceVista`, `TipoTarea`, `TareasDelRango = { tareas: TareaVista[]; atrasadas: TareaVista[] }` y `TareaNueva`.
  - En `api.ts`: `obtenerTareas(desde: string, hasta: string, atrasadas: boolean): Promise<TareasDelRango>` y `obtenerTiposTarea(): Promise<TipoTarea[]>`.
  - En `acciones-tareas.ts`:
    - `crearTarea(nueva)`, `editarTarea(id, nueva)`, `marcarHecha(id, hecha)` y `borrarTarea(id)`.
    - `crearTipoTarea(tipo)`, `editarTipoTarea(id, cambios)` y `borrarTipoTarea(id)`.
    - `crearCurso(id, nombre)` y `borrarCurso(id)`.
    - Las lecturas para el selector en cascada: `opcionesLecciones(curso): Promise<{numero: number; titulo: string}[]>` y `opcionesPiezas(curso, numero): Promise<{id: string; titulo: string}[]>`.
    - Todas siguen el patrón de `acciones.ts`:
      - validan los argumentos en tiempo de ejecución con las reglas de Global Constraints;
      - reconstruyen los objetos;
      - comprueban `host` y `origin` con `headers()` (las constantes de `origen-estudio.ts`);
      - pasan el `detail` en texto de los 4xx;
      - llaman a `refresh()` tras escribir;
      - devuelven `{ ok: true; ... } | { ok: false; mensaje: string }`.
  - En `fechas.ts` (funciones puras):
    - `fechaLocal(ahora: Date): string` (`YYYY-MM-DD` en la zona local).
    - `sumarDias(fecha: string, dias: number): string`.
    - `lunesDe(fecha: string): string`.
    - `diasDeSemana(fecha: string): string[]` (7 días, de lunes a domingo).
    - `esFechaValida(fecha: string): boolean`.
    - `fechaLegible(fecha: string): string`, por ejemplo «lun 16 nov».

- [ ] **Step 1: Tests que fallan:**
  - **`fechas`:**
    - `diasDeSemana("2026-01-01")` empieza en `"2025-12-29"` y acaba en `"2026-01-04"`.
    - `sumarDias("2026-02-28", 1)` da `"2026-03-01"`.
    - `esFechaValida("2026-02-29")` da `false` y `esFechaValida("2028-02-29")` da `true`.
    - `fechaLegible("2026-11-16")` da `"lun 16 nov"`.
    - `fechaLocal` de las 23:59 y de las 00:01 locales da el día correcto. El test fija `TZ`, o construye la `Date` con componentes locales.
  - **Acciones:**
    - `crearTarea` con una hora `25:00`, una fecha inválida, un texto con salto de línea o un `red` sin `pieza` → `ok: false` sin llamar a `escribir`.
    - `crearTarea` válida llama a `escribir("/api/tareas", <objeto reconstruido>, "POST")`.
    - `borrarTarea(3)` llama con `"DELETE"`.
    - Un host o un origin ajenos → `ok: false` sin llamar a la API.
    - Un 409 con `detail` en texto lo muestra tal cual.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** lint, tests y build.
- [ ] **Step 5: Commit** `Lecturas y acciones de tareas en la web`.

### Tarea 6: Vista de día (web)

**Files:**
- Modify: `src/app/page.tsx` (redirige a `/tareas`) y `src/app/tareas/page.tsx`
- Create: `src/components/tareas/VistaDia.tsx`, `src/components/tareas/FilaTarea.tsx`, `src/components/tareas/CabeceraTareas.tsx` y `src/lib/vista-tareas.ts`
- Test: `src/components/tareas/VistaDia.test.tsx` y `src/lib/vista-tareas.test.ts`

**Interfaces:**
- **Consumes:** la tarea 5.
- **Produces:**
  - `leerParametrosTareas(params, hoy: string) -> { vista: "dia" | "semana"; dia: string; curso: string | null; tipo: string | null }`, con las reglas de la URL de Global Constraints.
  - `agruparDia(tareas: TareaVista[], cursos: Curso[], tipos: TipoTarea[]) -> GrupoCurso[]`, con el orden de Global Constraints. `GrupoCurso = { curso: string | null; nombre: string; tipos: { tipo: TipoTarea; tareas: TareaVista[] }[] }`.
  - `hrefEnlace(t: TareaVista): string | null`:
    - con `red`, `/cursos/{curso}/{numero}?pestana=publicar&pieza={pieza}&red={red}`;
    - con `pieza` y sin `red`, lo mismo sin `red`;
    - con solo `numero`, `/cursos/{curso}/{numero}`;
    - con solo `curso`, `/cursos/{curso}`;
    - sin enlace, o con el enlace roto, `null`.
  - **Página:** pide las tareas del día. Si el día es hoy, pide también las atrasadas.
    - Muestra la cabecera «‹ dom 15 · lun 16 nov · mar 17 ›», el botón Día/Semana, los filtros de curso y tipo (como enlaces o `<select>` que cambian la URL) y «+ Tarea».
    - «Hoy» se calcula en la petición; consulta en `node_modules/next/dist/docs/` cómo leer la hora actual con `cacheComponents` (`connection()` dentro de `<Suspense>`).
  - **`FilaTarea`:**
    - casilla accesible que llama a `marcarHecha` (con `useTransition` y el error junto a ella);
    - texto, hora y chip del enlace («Lección 4 · Reel de salida · Instagram» como `<Link>`), o el chip «Enlace roto» sin enlace;
    - botones Editar y Borrar (Borrar pide confirmación).
  - **Grupo «Atrasadas»:** va arriba, solo cuando el día es hoy, con la fecha de cada tarea.
  - **Sin tareas:** «No hay tareas para este día».

- [ ] **Step 1: Tests que fallan:**
  - **`leerParametrosTareas`:**
    - `?vista=mes` → `dia`.
    - `?dia=2026-02-29` → hoy.
    - `?curso=../x` → `null`.
    - `?curso=sin-curso` → `"sin-curso"`.
  - **`agruparDia`:** React antes que Python (de la app) y «Sin curso» al final. Dentro de React, Grabar antes que Publicar, y dentro del tipo, la de las 09:00 antes que la que no tiene hora.
  - **`hrefEnlace`:** los cinco casos.
  - **`VistaDia`:**
    - un texto con `<script>` se pinta como texto;
    - una tarea con el enlace roto muestra «Enlace roto» y no lleva `<a>`;
    - con atrasadas y el día de hoy se ve el grupo «Atrasadas», y con otro día no;
    - al pulsar la casilla se llama a `marcarHecha(id, true)`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** lint, tests y build.
- [ ] **Step 5: Commit** `Tareas: vista de día y la app abre en hoy`.

### Tarea 7: Vista de semana (web)

**Files:**
- Create: `src/components/tareas/VistaSemana.tsx`
- Modify: `src/app/tareas/page.tsx`
- Test: `src/components/tareas/VistaSemana.test.tsx`

**Interfaces:**
- **Consumes:** `diasDeSemana`, `obtenerTareas(lunes, domingo, false)`, los filtros y `TipoTarea.color`.
- **Produces:**
  - Siete columnas de lunes a domingo, con «lun 16» como cabecera. Pulsar la cabecera lleva a la vista de día de esa fecha.
  - Las tareas van en corto: texto truncado con un borde o punto del color de su tipo, tachadas si están hechas.
  - Navegación «‹ semana anterior · semana siguiente ›».
  - En pantallas estrechas, las columnas se apilan.

- [ ] **Step 1: Tests que fallan:**
  - La semana del 2026-01-01 muestra de «lun 29» a «dom 4».
  - Una tarea del miércoles sale en la tercera columna.
  - Una tarea hecha lleva `line-through`.
  - El filtro `tipo=publicar` solo pinta las de Publicar.
  - El enlace de la cabecera del martes apunta a `?vista=dia&dia=<martes>`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** lint, tests y build.
- [ ] **Step 5: Commit** `Tareas: vista de semana`.

### Tarea 8: Crear, editar y borrar tareas (web)

**Files:**
- Create: `src/components/tareas/FormularioTarea.tsx` (cliente)
- Modify: `VistaDia.tsx`, `FilaTarea.tsx` y `CabeceraTareas.tsx`
- Test: `src/components/tareas/FormularioTarea.test.tsx`

**Interfaces:**
- **Consumes:** `crearTarea`, `editarTarea`, `borrarTarea`, `opcionesLecciones`, `opcionesPiezas` y `REDES` de `src/lib/curso.ts`.
- **Produces:** un formulario (diálogo `<dialog>` accesible, con foco al abrir y Escape para cerrar). Lo abren «+ Tarea», con la fecha del día que se ve, y «Editar», con la tarea cargada.
  - **Campos:** texto (contador `n/300`), fecha, hora opcional, tipo y el enlace en cascada (curso → lección → pieza → red).
    - Cada nivel se activa al elegir el anterior, y cambiar uno vacía los de debajo.
    - Un curso de la app no ofrece lecciones.
  - **Botones:** «Guardar», desactivado si el texto está vacío o pasa de 300, y «Cancelar».
  - **Errores:** el de la acción sale en el diálogo y no se pierde lo escrito.

- [ ] **Step 1: Tests que fallan:**
  - **Cascada:**
    - al elegir `react` se llama a `opcionesLecciones("react")` y se activa Lección;
    - al cambiar de curso se vacían la lección, la pieza y la red;
    - con `python` (de la app), Lección queda desactivado.
  - **Guardar:**
    - envía a `crearTarea` el objeto con la jerarquía correcta;
    - con un enlace solo hasta la lección, no envía ni `pieza` ni `red`.
  - **Error:** si la acción devuelve `ok: false`, el mensaje se muestra y el texto sigue.
  - **Editar:** abre el formulario con los valores de la tarea, y guardar llama a `editarTarea(id, …)`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** lint, tests y build.
- [ ] **Step 5: Commit** `Tareas: crear, editar y borrar con enlace en cascada`.

### Tarea 9: Tipos de tarea y alta de cursos (web)

**Files:**
- Create: `src/app/tareas/tipos/page.tsx` y `src/components/tareas/EditorTipos.tsx`
- Create: `src/components/FormularioCurso.tsx`
- Modify: `src/app/cursos/page.tsx`
- Test: `src/components/tareas/EditorTipos.test.tsx` y `src/components/FormularioCurso.test.tsx`

**Interfaces:**
- **Consumes:** las acciones de tipos y de cursos de la tarea 5.
- **Produces:**
  - **`/tareas/tipos`:** la lista de tipos con su nombre, su color (selector con los 8 de Global Constraints) y su orden.
    - Se puede crear un tipo (id derivado del nombre: minúsculas, sin tildes y con espacios a guiones, y editable).
    - Borrar un tipo en uso muestra el 409 en castellano: «Hay tareas de este tipo; cámbialas antes de borrarlo».
    - Se llega con un enlace «Tipos» desde la cabecera de Tareas.
  - **`/cursos`:** «+ Curso» abre un formulario con nombre e id derivado.
    - Los cursos de la app salen en la lista con la etiqueta «Sin carpeta todavía».
    - Al entrar en uno se ve «Este curso aún no tiene lecciones en disco», no un 404.
    - Borrar un curso de la app solo se ofrece si no tiene carpeta.

- [ ] **Step 1: Tests que fallan:**
  - La derivación de id: «Edición rápida» → `edicion-rapida`.
  - El 409 de borrar se muestra.
  - Un curso con `en_disco: false` muestra «Sin carpeta todavía».
  - La página de un curso con `[]` lecciones muestra el texto vacío y no el 404.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** lint, tests y build.
- [ ] **Step 5: Commit** `Tipos de tarea configurables y alta de cursos`.

### Tarea 10: Verificación real y cierre

- [ ] **Step 1: Arranque.** Crear un clon APFS de `Cursos youtube/REACT` y una copia de la BD real (versión 1) en el scratchpad. Arrancar la API con `CURSOS_DIR` y `BD_RUTA` apuntando a ellos, y la web con `npm run estudio`.
- [ ] **Step 2: Recorrido con Playwright.**
  - **Arranque y migración:**
    - `/` abre las tareas de hoy;
    - la copia de la BD se ha migrado a la versión 2 y conserva las portadas y los estados.
  - **Crear y completar:**
    - crear una tarea enlazada a (react, 4, reel-salida, instagram), otra solo de React y otra suelta;
    - el enlace abre Publicar con esa pieza y esa red;
    - marcar Instagram como publicado deja la tarea hecha.
  - **Vistas:**
    - las atrasadas aparecen hoy;
    - la vista de semana y sus filtros funcionan.
  - **Configuración:**
    - crear y borrar un tipo, y que el tipo en uso dé 409;
    - dar de alta Python y crear una tarea suya;
    - borrar en el clon una pieza enlazada → «Enlace roto».
  - **Calidad:** 0 errores de consola.
- [ ] **Step 3:** `/security-review` en los dos repos. Guardar los informes y arreglar lo que salga.
- [ ] **Step 4:** Revisión final de las dos ramas con un revisor nuevo, y arreglos.
- [ ] **Step 5:** Push y PR de cada repo con la CI en verde, con el permiso del autor. Merge solo con su visto bueno.
