# Estudio OnlyDevCoding · Fase 1 (cimientos y Cursos en solo lectura) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dos repos públicos (API FastAPI y web Next.js) con el marco de seguridad de tech-study-tracker, y las pantallas Cursos → curso → lección (pestañas + panel de estado) leyendo las carpetas reales, sin escribir nada en disco.

**Architecture:** La API lee `CURSOS_DIR` y `ESTUDIO_DIR` (rutas en `.env`), construye modelos `Curso`/`Leccion`/`Escena`/`Pieza` y calcula el estado de cada lección a partir de los archivos; sirve JSON y los medios (con Range) solo dentro de esas dos raíces. La web pide los datos desde componentes de servidor y enseña los vídeos y fotogramas con URLs de medios de la API.

**Tech Stack:** API: Python 3.14, uv, FastAPI, Pydantic v2, pytest, httpx (TestClient), ruff. Web: Next.js (App Router) + TypeScript, Tailwind CSS, Vitest + Testing Library, ESLint. Verificación visual: Playwright (la hace Claude).

**Spec:** `docs/specs/2026-11-16-estudio-onlydevcoding-design.md` (se copia al repo de la API en la tarea 1; original en `<herramientas>/gestor-canal-bocetos/docs/`).

**Fases siguientes (planes aparte):** 2 Publicar · 3 Tareas · 4 Teleprompter y grabación · 5 Editar guion y acciones · 6 Entrega de tomas.

## Contexto de ejecución

- El código lo escribe **Codex** (`codex exec -C <repo> …`) cuando hay cuota; si se queda sin cuota, lo implementa Claude. **No reutilizar el `codex:task` de tech-study-tracker** (cada repo, su propia sesión de Codex).
- Codex no puede abrir puertos ni navegador: **Claude** ejecuta `uv sync`/`npm install`, arranca los servidores y hace la verificación con Playwright.
- Commits sin `Co-Authored-By` ni «Generated with». Rama `feat/fase-1` en cada repo, PR contra `main`; nada directo a `main` salvo el commit inicial vacío que crea la rama por defecto.

## Global Constraints

- Local, sin autenticación. API en `127.0.0.1:8000`; web en `localhost:3000`.
- Repos públicos `pedroleni/onlydevcoding-estudio-api` y `pedroleni/onlydevcoding-estudio-web`.
- **Nada privado en los repos**: ni rutas absolutas del Mac, ni emails, ni tomas, ni textos de lecciones. Los tests usan datos falsos creados en `tmp_path`. Las rutas reales solo en `.env` (ignorado); `.env.example` con valores de ejemplo.
- La fase 1 **no escribe** en `CURSOS_DIR` ni en `ESTUDIO_DIR`.
- Toda ruta que la API abra se resuelve dentro de una de las dos raíces (sin `..`, sin enlaces que salgan); ids de curso `^[a-z0-9-]{1,40}$`, número de lección entero 1–999.
- Solo se aceptan peticiones con `Host` `127.0.0.1:8000` o `localhost:8000`; las de navegador con `Origin` distinto de `ORIGEN_WEB` (por defecto `http://localhost:3000`) se rechazan con 403.
- Dependencias fijadas con lockfile (`uv.lock`, `package-lock.json`).
- Textos de la interfaz en castellano de España. Tema oscuro: fondo `#141416`, superficie `#1E1E21`, borde `#313136`, texto `#F5F5F6`, tenue `#8E8E98`, azul de marca `#299BC6`, carbón `#28272A`.
- Redes, en este orden: YouTube, Instagram, TikTok, LinkedIn.

## Review Focus

1. Lección con guion en el estudio pero sin carpeta en `Cursos youtube` (o al revés): la lista debe mostrarla con el estado vacío, no fallar → test en tarea 3.
2. Petición de medios con `..`, ruta absoluta, enlace simbólico que sale de la raíz o extensión no permitida (`.env`, `.json` fuera de lecciones): 404, nunca el archivo → test en tarea 5.
3. Vídeo grande pedido con `Range` (el navegador salta al segundo de una escena): 206 con el trozo pedido, no el archivo entero → test en tarea 5.
4. Carpeta en `Cursos youtube` que no es un curso (`Asset`, `Fondos de pantalla`, `Intros (propuestas)`): no aparece como curso → test en tarea 3.
5. Web abierta con la API apagada: página con aviso «No se puede conectar con la API», no pantalla en blanco → test en tarea 7.

---

## Repo de la API (`onlydevcoding-estudio-api`)

### Tarea 1: Proyecto, configuración y cortafuegos local

**Files:**
- Create: `pyproject.toml`, `uv.lock`, `.gitignore`, `.env.example`, `README.md`
- Create: `estudio_api/__init__.py`, `estudio_api/config.py`, `estudio_api/app.py`, `estudio_api/seguridad.py`
- Create: `docs/specs/2026-11-16-estudio-onlydevcoding-design.md` (copia del diseño), `docs/plans/2026-11-16-estudio-onlydevcoding-fase-1.md` (este plan)
- Test: `tests/test_app.py`

**Interfaces:**
- Produces:
  - `class Config(BaseModel): cursos_dir: Path; estudio_dir: Path; origen_web: str = "http://localhost:3000"`
  - `def cargar_config() -> Config` (lee `CURSOS_DIR`, `ESTUDIO_DIR`, `ORIGEN_WEB` de entorno / `.env`; falla con mensaje claro si faltan o no existen)
  - `def crear_app(config: Config) -> FastAPI` (con el middleware de `seguridad.py` y `GET /api/salud` → `{"ok": true}`)
  - Arranque: `uv run uvicorn estudio_api.app:app --host 127.0.0.1 --port 8000`

- [ ] **Step 1:** Crear el repo público y la rama:
```bash
gh repo create pedroleni/onlydevcoding-estudio-api --public --description "API local del estudio de OnlyDevCoding (FastAPI)"
git clone … && cd onlydevcoding-estudio-api && git commit --allow-empty -m "Inicio" && git push -u origin main && git switch -c feat/fase-1
```
- [ ] **Step 2: Tests que fallan** en `tests/test_app.py`:
```python
def test_salud(cliente): assert cliente.get("/api/salud").json() == {"ok": True}
def test_host_ajeno_rechazado(cliente): assert cliente.get("/api/salud", headers={"Host": "evil.com"}).status_code == 400
def test_origen_ajeno_rechazado(cliente): assert cliente.get("/api/salud", headers={"Origin": "https://evil.com"}).status_code == 403
def test_origen_web_aceptado(cliente): assert cliente.get("/api/salud", headers={"Origin": "http://localhost:3000"}).status_code == 200
def test_config_sin_rutas_falla(monkeypatch): ...  # sin CURSOS_DIR → ValueError con «CURSOS_DIR»
```
(`cliente` = fixture con `TestClient(crear_app(Config(cursos_dir=tmp, estudio_dir=tmp)), base_url="http://127.0.0.1:8000")`.)
- [ ] **Step 3:** `uv run pytest -q` → FAIL.
- [ ] **Step 4:** Implementar. `seguridad.py`: middleware puro ASGI que comprueba `Host` y `Origin` como en Global Constraints; CORS solo para `ORIGEN_WEB`, métodos `GET` en esta fase.
- [ ] **Step 5:** `uv run pytest -q && uv run ruff check .` → PASS.
- [ ] **Step 6: Commit** `Proyecto, configuración y cortafuegos local`.

### Tarea 2: Marco de seguridad (copiado de tech-study-tracker y adaptado)

**Files:**
- Create: `AGENTS.md`, `CLAUDE.md`, `.claude/agents/security-{agent-env,secrets,code-vulns,supply-chain,injection,local-api,infrastructure,prompt-injection}.md`, `.claude/commands/security-review.md`, `security/security-review-instructions.md`, `security/reviews/README.md`, `scripts/security/scan_*.sh`, `scripts/security/install_hooks.sh`, `.githooks/pre-commit`, `.github/workflows/security-scan.yml`, `.github/workflows/ci.yml`
- Origen: `<proyectos>/tech-study-tracker/` (mismos nombres)

**Interfaces:**
- Produces: `bash scripts/security/install_hooks.sh` instala el hook; los scanners salen con código ≠ 0 si hay CRITICAL/HIGH.

- [ ] **Step 1:** Copiar los archivos de origen y adaptar:
  - `AGENTS.md`: proyecto (API local FastAPI de OnlyDevCoding), qué leer (`docs/specs`, `docs/plans`), comandos (`uv run pytest`, `uv run ruff check .`), flujo de ramas idéntico, reglas de Global Constraints («nada privado en el repo», «no escribir en las carpetas de datos salvo en las fases que lo especifiquen»).
  - Sustituir `security-auth-crypto.md` por `security-local-api.md`: exposición en `127.0.0.1`, `Host`/`Origin`, DNS rebinding, CSRF, recorrido de rutas, procesos (lista cerrada, sin shell), subidas.
  - `security-review-instructions.md`: precedentes de este proyecto (no hay auth por diseño — no reportarlo; sí reportar cualquier ruta que salga de las raíces o cualquier `subprocess` con `shell=True`).
  - Scanners: rutas de búsqueda `estudio_api/`, `tests/`, `scripts/`; quitar los chequeos de Supabase/RLS.
  - `ci.yml`: en cada PR, `uv sync --frozen`, `uv run ruff check .`, `uv run pytest -q`. `security-scan.yml`: los scanners.
- [ ] **Step 2:** `bash scripts/security/install_hooks.sh && for s in scripts/security/scan_*.sh; do bash "$s"; done` → todos terminan sin CRITICAL/HIGH.
- [ ] **Step 3: Commit** `Marco de seguridad de agentes, scanners, hook y CI`.

### Tarea 3: Lectura de cursos y lecciones

**Files:**
- Create: `estudio_api/rutas.py`, `estudio_api/modelos.py`, `estudio_api/lectura.py`
- Test: `tests/conftest.py` (fábrica de carpetas falsas), `tests/test_lectura.py`

**Interfaces:**
- Produces:
  - `def ruta_segura(raiz: Path, *partes: str) -> Path` — `ValueError` si el resultado (con `resolve()`) no queda dentro de `raiz`.
  - Modelos (Pydantic):
    - `Escena(id: str, modo: Literal["voz","camara","animacion"], tipo: str, titulo: str, textos: list[str], inicio_s: float | None, duracion_s: float | None)`
    - `Pieza(id: str, tipo: Literal["leccion","reel","short"], titulo: str, video: str | None, portadas: list[str])`
    - `LeccionResumen(curso: str, numero: int, slug: str, titulo: str, estado: EstadoLeccion)`
    - `Leccion(LeccionResumen + subtitulo: str, escenas: list[Escena], piezas: list[Pieza], previas: list[str], duracion_s: float | None)`
    - `Curso(id: str, nombre: str, carpeta: str, lecciones: int)`
    - `Avance(hechas: int, total: int)` y `EstadoLeccion(guion: bool, voz: Avance, camara: Avance, video_final: bool, miniatura: str | None, previa: str | None, publicado: dict[str, bool])`; en esta tarea `estado` se rellena con un `EstadoLeccion` vacío (lo calcula la tarea 4).
  - `def leer_cursos(config: Config) -> list[Curso]`, `def leer_lecciones(config: Config, curso: str) -> list[LeccionResumen]`, `def leer_leccion(config: Config, curso: str, numero: int) -> Leccion | None`
- Reglas (del disco real):
  - **Curso** = subcarpeta de `CURSOS_DIR` con al menos una subcarpeta `^\d{2}-`; `id` = nombre en minúsculas (`REACT` → `react`), `nombre` = el campo `ficha` del primer guion del curso o el nombre de la carpeta.
  - **Lección**: carpeta `NN-slug` del curso, emparejada con `ESTUDIO_DIR/lecciones/<id>-NN.json` (su campo `carpeta` = `<CURSO>/<NN-slug>`). Si falta una de las dos, la lección sale igual con lo que haya.
  - **Escenas**: del guion; `textos` = `cues[].texto`; tiempos de `public/lecciones/<id>-NN/montaje.json` (inicio = suma de `duracion` de las escenas anteriores / `fps`).
  - **Piezas**: `leccion` (vídeo = `publicar/1-youtube-leccion/*.mp4`, portadas = `miniatura-*.jpg`); `reel` por cada `publicar/2-shorts-y-reels/reel-*.mp4`; `short` por cada `short-*.mp4` (portadas: `portadas-opciones/portada-short-<n>-*.jpg` o `portada-*` del mismo nombre). Se ignoran `anteriores/`, `descartadas/` y `*-anterior.*`.
  - **Previas**: `previa/previa-v*.mp4` ordenadas por número de versión.
  - Rutas devueltas relativas a su raíz, con prefijo `cursos/` o `estudio/`.

- [ ] **Step 1: Tests que fallan** (`tests/test_lectura.py`), con una fábrica que crea en `tmp_path` un curso `REACT` con `04-importar-y-exportar` (guion falso con E01 cámara, E03 voz, montaje con fps 30), carpetas `Asset/` y `Fondos/` sin lecciones, y una lección `05-otra` sin guion:
```python
def test_solo_cursos_con_lecciones(cfg): assert [c.id for c in leer_cursos(cfg)] == ["react"]
def test_leccion_sin_guion_aparece(cfg): assert [l.numero for l in leer_lecciones(cfg, "react")] == [4, 5]
def test_escenas_con_tiempos(cfg): e = leer_leccion(cfg, "react", 4).escenas; assert (e[1].id, e[1].inicio_s) == ("E03", 2.0)
def test_piezas(cfg): assert [p.tipo for p in leer_leccion(cfg, "react", 4).piezas] == ["leccion", "reel", "short"]
def test_ignora_anteriores(cfg): assert all("anterior" not in p.video for p in leer_leccion(cfg, "react", 4).piezas if p.video)
def test_ruta_segura_rechaza_salida(tmp_path): pytest.raises(ValueError, ruta_segura, tmp_path, "../x")
```
- [ ] **Step 2:** `uv run pytest tests/test_lectura.py -q` → FAIL.
- [ ] **Step 3:** Implementar según las reglas.
- [ ] **Step 4:** → PASS. **Step 5: Commit** `Lectura de cursos, lecciones, escenas y piezas`.

### Tarea 4: Estado de cada lección

**Files:**
- Create: `estudio_api/estado.py`
- Modify: `estudio_api/lectura.py` (rellena `estado`)
- Test: `tests/test_estado.py`

**Interfaces:**
- Consumes: `EstadoLeccion` y `Avance` de `estudio_api/modelos.py` (tarea 3).
- Produces: `def calcular_estado(config: Config, curso: str, carpeta: Path | None, guion: dict | None) -> EstadoLeccion`
- Reglas: `voz` = escenas `voz` con `grabaciones/<E>.wav`; `camara` = escenas `camara` con toma en `ESTUDIO_DIR/public/grabaciones/<id>-NN/<E>.mov` o en `grabaciones/videos/ia/<E>.mov`; `video_final` = existe el `.mp4` de `1-youtube-leccion`; `miniatura` = `None` en fase 1 (la elige el autor en la fase 2); `previa` = última versión; `publicado` = las cuatro redes a `False` (fase 2).

- [ ] **Step 1: Tests que fallan:**
```python
def test_voz_parcial(cfg): assert calcular_estado(...).voz == Avance(hechas=1, total=2)
def test_camara_desde_ia(cfg): ...  # toma solo en videos/ia → cuenta como hecha
def test_sin_carpeta(cfg): assert calcular_estado(cfg, "react", None, guion).video_final is False
def test_redes(cfg): assert list(calcular_estado(...).publicado) == ["youtube", "instagram", "tiktok", "linkedin"]
```
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS. **Step 5: Commit** `Estado de la lección calculado desde el disco`.

### Tarea 5: Endpoints y medios

**Files:**
- Create: `estudio_api/rutas_api.py`, `estudio_api/medios.py`
- Modify: `estudio_api/app.py`
- Test: `tests/test_api.py`, `tests/test_medios.py`

**Interfaces:**
- Produces:
  - `GET /api/cursos` → `list[Curso]`
  - `GET /api/cursos/{curso}/lecciones` → `list[LeccionResumen]` (404 si el curso no existe)
  - `GET /api/cursos/{curso}/lecciones/{numero}` → `Leccion` (404 si no existe)
  - `GET /api/medios?ruta=<prefijo>/<relativa>` → archivo, con `Range` (206 + `Content-Range`) y `Accept-Ranges: bytes`. Extensiones permitidas: `.mp4 .mov .wav .jpg .jpeg .png`. Cualquier otra cosa o ruta fuera de raíz → 404.
- [ ] **Step 1: Tests que fallan:**
```python
def test_cursos(cliente): assert cliente.get("/api/cursos").json()[0]["id"] == "react"
def test_leccion_404(cliente): assert cliente.get("/api/cursos/react/lecciones/99").status_code == 404
def test_curso_invalido(cliente): assert cliente.get("/api/cursos/..%2Fx/lecciones").status_code in (404, 422)
@pytest.mark.parametrize("ruta", ["cursos/../../etc/passwd", "/etc/passwd", "cursos/REACT/.env", "estudio/lecciones/react-04.json", "cursos/enlace-fuera.mp4"])
def test_medios_prohibidos(cliente, ruta): assert cliente.get("/api/medios", params={"ruta": ruta}).status_code == 404
def test_medios_range(cliente): r = cliente.get("/api/medios", params={"ruta": "cursos/REACT/04-importar-y-exportar/previa/previa-v1.mp4"}, headers={"Range": "bytes=0-9"}); assert (r.status_code, len(r.content)) == (206, 10)
```
(`enlace-fuera.mp4` = enlace simbólico creado en el fixture que apunta fuera de `tmp_path`.)
- [ ] **Step 2:** FAIL. **Step 3:** Implementar (`FileResponse` no sirve `Range`: leer el trozo con `open`/`seek` y `StreamingResponse`). **Step 4:** PASS.
- [ ] **Step 5:** Claude arranca la API con el `.env` real y comprueba `curl -s 127.0.0.1:8000/api/cursos/react/lecciones/4 | jq '.estado'` (voz 13/13, cámara 3/3, vídeo final true).
- [ ] **Step 6: Commit** `Endpoints de cursos y lecciones, y medios con Range`. Push y PR `Fase 1: API de solo lectura`.

---

## Repo web (`onlydevcoding-estudio-web`)

### Tarea 6: Proyecto, tema, navegación y marco de seguridad

**Files:**
- Create: proyecto Next.js (`create-next-app` con TypeScript, App Router, Tailwind, ESLint, `src/`), `vitest.config.ts`, `.env.example` (`API_URL=http://127.0.0.1:8000`, `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000`)
- Create: `src/app/layout.tsx` (barra: OnlyDevCoding · Cursos · Teleprompter · Tareas), `src/app/page.tsx` (redirige a `/cursos`), `src/app/teleprompter/page.tsx` y `src/app/tareas/page.tsx` («Llega en la fase 4/3»), `src/app/globals.css` (tokens del tema)
- Create: `src/lib/api.ts`, `src/lib/tipos.ts`
- Create: marco de seguridad como la tarea 2 (`AGENTS.md`, `CLAUDE.md`, `.claude/agents/security-*`, `/security-review`, `security/`, `scripts/security/`, `.githooks/`, workflows; `ci.yml` = `npm ci && npm run lint && npm test -- --run && npm run build`)
- Test: `src/lib/api.test.ts`

**Interfaces:**
- Consumes: endpoints de la tarea 5.
- Produces:
  - `src/lib/tipos.ts`: `Curso`, `LeccionResumen`, `Leccion`, `Escena`, `Pieza`, `EstadoLeccion`, `Avance` con los mismos campos que la API (snake_case tal cual).
  - `src/lib/api.ts`: `obtenerCursos(): Promise<Curso[]>`, `obtenerLecciones(curso: string): Promise<LeccionResumen[]>`, `obtenerLeccion(curso: string, numero: number): Promise<Leccion | null>`, `urlMedio(ruta: string): string`; `class ApiNoDisponible extends Error` cuando la API no responde.
- [ ] **Step 1:** `gh repo create pedroleni/onlydevcoding-estudio-web --public --description "Web local del estudio de OnlyDevCoding (Next.js)"`, commit vacío inicial en `main`, rama `feat/fase-1`.
- [ ] **Step 2: Tests que fallan** (`api.test.ts`, con `fetch` simulado):
```ts
it('lanza ApiNoDisponible si la API no responde', async () => { fetchFalla(); await expect(obtenerCursos()).rejects.toBeInstanceOf(ApiNoDisponible) })
it('devuelve null en 404', async () => { fetchCon(404); expect(await obtenerLeccion('react', 99)).toBeNull() })
it('urlMedio codifica la ruta', () => { expect(urlMedio('cursos/REACT/a b.mp4')).toBe('http://127.0.0.1:8000/api/medios?ruta=cursos%2FREACT%2Fa%20b.mp4') })
```
- [ ] **Step 3:** FAIL. **Step 4:** Implementar. **Step 5:** `npm run lint && npm test -- --run && npm run build` → PASS; scanners sin CRITICAL/HIGH.
- [ ] **Step 6: Commit** `Proyecto, tema, navegación y marco de seguridad`.

### Tarea 7: Pantallas Cursos, curso y lección

**Files:**
- Create: `src/app/cursos/page.tsx`, `src/app/cursos/[curso]/page.tsx`, `src/app/cursos/[curso]/[numero]/page.tsx`
- Create: `src/components/PanelEstado.tsx`, `src/components/PestanasLeccion.tsx`, `src/components/TarjetaEscena.tsx`, `src/components/ListaPiezas.tsx`, `src/components/AvisoApi.tsx`
- Test: `src/components/PanelEstado.test.tsx`, `src/components/TarjetaEscena.test.tsx`, `src/app/cursos/page.test.tsx`

**Interfaces:**
- Consumes: `src/lib/api.ts`, `src/lib/tipos.ts`.
- Produces (pantallas del boceto «mezcla»):
  - `/cursos`: tarjetas de curso (nombre, nº de lecciones).
  - `/cursos/[curso]`: rejilla de lecciones con número, título y chips de estado (voz n/m, cámara n/m, vídeo final, publicado por red).
  - `/cursos/[curso]/[numero]`: cabecera (curso · lección N, título), botón «Abrir en el teleprompter» (enlace a `/teleprompter?curso=…&leccion=…`, desactivado hasta la fase 4), pestañas **Guion · Grabaciones · Vídeo final · Shorts y reels · Publicar** (estado en `?pestana=`), `PanelEstado` fijo a la derecha.
  - **Guion**: `TarjetaEscena` por escena: fotograma (`<video>` de la última previa con `#t=<inicio_s + 1>`, `preload="metadata"`, sin controles), id y título, chip de modo («cámara» / «voz en off» / «animación»), primeras palabras de `textos`.
  - **Grabaciones / Vídeo final / Shorts y reels**: listas de lo que hay (tomas, previas con reproductor, piezas con su portada); **Publicar**: «Llega en la fase 2».
- [ ] **Step 1: Tests que fallan:**
```tsx
it('PanelEstado marca la voz completa', () => { render(<PanelEstado estado={{...vacio, voz: {hechas: 13, total: 13}}} />); expect(screen.getByText(/Voz grabada/)).toHaveTextContent('✅') })
it('PanelEstado lista las cuatro redes', () => { render(<PanelEstado estado={vacio} />); ['YouTube','Instagram','TikTok','LinkedIn'].forEach(r => expect(screen.getByText(r)).toBeInTheDocument()) })
it('TarjetaEscena salta al segundo de la escena', () => { render(<TarjetaEscena escena={{...e, inicio_s: 32}} previa="cursos/x.mp4" />); expect(document.querySelector('video')!.getAttribute('src')).toMatch(/#t=33$/) })
it('Cursos con la API apagada muestra el aviso', async () => { apiApagada(); render(await PaginaCursos()); expect(screen.getByText('No se puede conectar con la API')).toBeInTheDocument() })
```
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS + `npm run lint && npm run build`.
- [ ] **Step 5: Commit** `Pantallas de cursos, curso y lección con panel de estado`.

### Tarea 8: Verificación real y cierre de la fase (Claude)

- [ ] **Step 1:** Arrancar la API (`.env` real) y la web (`npm run dev`); con Playwright, capturas de `/cursos`, `/cursos/react` y `/cursos/react/4` en sus cinco pestañas. Comprobar: React aparece y `Asset` no; la lección 4 muestra 18 escenas, voz 13/13, cámara 3/3, vídeo final ✓; los fotogramas cargan; con la API apagada sale el aviso.
- [ ] **Step 2:** `/security-review` en los dos repos; guardar el informe en `security/reviews/2026-11-XX-fase-1.md` de cada uno; corregir CRITICAL/HIGH.
- [ ] **Step 3:** Revisión de todo el código por un revisor nuevo; arreglos.
- [ ] **Step 4:** Push de las ramas y PR de cada repo con CI en verde; enseñar capturas al autor y mergear solo con su visto bueno.
