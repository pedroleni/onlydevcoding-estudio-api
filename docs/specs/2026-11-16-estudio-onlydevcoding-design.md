# Estudio OnlyDevCoding — diseño

Fecha: 2026-11-16. Bocetos aprobados en `.superpowers/brainstorm/` (lección, publicar, tareas, teleprompter).

## Por qué

El canal OnlyDevCoding (cursos de programación en YouTube, más shorts y reels en Instagram, TikTok y LinkedIn) se produce hoy con carpetas, guías en Markdown, una página de grabación suelta y la memoria de la conversación. Cada lección pasa por guion, grabación de voz y cámara, montaje, render, portadas, textos por red y publicación, y no hay un sitio donde ver de un vistazo qué hay hecho, qué falta, qué portada se eligió o qué está publicado. La app es ese sitio: **una herramienta local y visual para gestionar el canal**, que lee lo que ya existe en disco y guarda solo las decisiones del autor.

## Objetivos

1. **Cursos**: cursos → lecciones → piezas (la lección completa, el reel de salida, cada short), con todo su contenido ordenado de forma visual.
2. **Editar el guion** desde la app y **lanzar las herramientas** del estudio (montaje, vista previa, render…) con botones.
3. **Publicar**: para cada pieza, su portada (elegir la buena) y sus textos por red (YouTube, Instagram, TikTok, LinkedIn) listos para copiar; marcar qué está publicado y dónde.
4. **Teleprompter**: todo lo que hace hoy la página de grabación, más las escenas a cámara y la entrega de sus vídeos.
5. **Tareas**: por día y por semana, agrupadas por curso y por tipo, enlazadas a la lección y la pieza.

## No objetivos (por ahora)

- Publicar la app en internet, usuarios, login o permisos. **Es local, en el Mac del autor.**
- Subir vídeos a YouTube/Instagram/TikTok/LinkedIn por API: se publica a mano desde cada plataforma copiando los textos.
- Sustituir el estudio Remotion ni sus herramientas: la app las usa, no las reescribe.
- Estadísticas de las redes.

## Antiobjetivos (fallaría aunque funcione)

- **Duplicar datos a mano**: si lo que se prepara en las carpetas no aparece solo en la app, no sirve.
- **Filtrar datos privados a los repos públicos**: rutas del disco, tomas, voz, emails, textos de lecciones sin publicar.
- **Una API local que cualquier web del navegador pueda llamar** (ver Seguridad): la app ejecuta herramientas y escribe en disco.
- **Romper el flujo actual**: las carpetas, los nombres de archivo y las herramientas siguen funcionando igual con o sin la app.

## Decisiones del autor

- **Front: Next.js con TypeScript. Back: API en Python.** Dos repos públicos en GitHub (`pedroleni`).
- **Local, sin autenticación.** No se despliega ahora. (Si algún día se publica, ver «Desplegar el back más adelante».)
- **La API lee las carpetas existentes** y guarda aparte (base de datos local) solo las decisiones: portada elegida, publicado, tareas.
- **Lección = pestañas por etapa + panel de estado fijo a la derecha** (mezcla de los bocetos A y B).
- **Guion editable** desde la app; al cambiarlo, la lección queda marcada «guion cambiado: hay que regenerar el montaje». Y **botones para lanzar las herramientas**.
- **Publicar**: selector de pieza → portadas (clic en la buena) → pestañas por red con «Copiar» → fecha programada → «Marcar como publicado en <red>». **LinkedIn es la cuarta red.**
- **Tareas**: vista de día y vista de semana con un botón para cambiar; agrupadas por curso y por tipo (grabar, editar, publicar…). **Enlazadas a su lección**: «Publicar…» abre la pestaña Publicar con sus textos, y marcar algo como publicado completa la tarea.
- **Teleprompter**: hace todo lo de la página de grabación actual. Las escenas a cámara se marcan 🎥, muestran su texto, y tienen un botón para **entregar los vídeos**; la app los identifica, renombra y coloca.
- **Mismas medidas de seguridad que tech-study-tracker** a nivel de agentes (ver Seguridad).

## Decisiones mías (revisables)

- API con **FastAPI** + **SQLite** (SQLModel), Python 3.14 con **uv**; front con **App Router** y Tailwind. Tests: pytest + ruff (API), Vitest + ESLint (front).
- Las rutas a las carpetas van en un `.env` local no versionado (`CURSOS_DIR`, `ESTUDIO_DIR`).
- Tema oscuro con los colores de la marca (azul `#299BC6`, carbón `#28272A`), el mismo aire que la página de grabación.
- Herramientas: **lista cerrada de acciones**, nunca comandos libres; se ejecutan como trabajos en segundo plano con progreso y registro, de uno en uno.
- Textos de publicación en un formato estructurado nuevo por lección (ver «Datos»), que yo (Claude) escribo a partir de ahora; las guías `PUBLICAR-*.md` se siguen generando para el móvil.
- Abre por defecto en la vista de tareas de **hoy**; el filtro por curso y tipo vale para día y semana.
- Además de tareas enlazadas, se pueden crear tareas sueltas sin lección.
- **Las tareas las crea el autor** (lo pidió: «un gestor de tareas donde crearemos las tareas»), con un selector opcional de curso → lección → pieza → red. La app no genera tareas sola en esta versión. Si la pieza enlazada desaparece del disco, la tarea se conserva y muestra el enlace como roto.
- **Cursos**: los que existen en disco, más los que el autor dé de alta en la app aunque aún no tengan carpeta (p. ej. Python), para poder asignarles tareas.
- **Edición del guion = solo textos**: frases de la voz en off (`cues[].texto`), textos a cámara (`TELEPROMPTER.txt` y `puntos`) y ganchos. No se añaden, borran ni reordenan escenas, ni se cambian `modo`, `tipo`, `datos` o `codigos` (los ids `E03…` dan nombre a grabaciones y transcripciones). Copia de seguridad antes de escribir, como hoy (`.antes-de-editar`).
- **Se pueden adaptar las herramientas del estudio** (repo `tech-study-videos`) para que la app las use bien: leer rutas de variables de entorno en lugar de rutas fijas y emitir progreso legible (p. ej. líneas `PROGRESO n/total`). Son cambios en ese repo, por PR propio.
- **Entrega de tomas a cámara**: el autor arrastra las exportaciones tal como salen (Facetune/iPhone). La app conserva el original con su nombre en `grabaciones/videos/`, coloca la copia renombrada (`E17.mov`) donde la usa el render y deja la escena «grabada». La mejora con IA (`superres.sh`, la que genera `videos/ia/`) entra en la lista de acciones como paso opcional. Los **ganchos verticales** de los shorts van a la carpeta de tomas del short de esa lección y se les aplica `piel-natural` (solo a los ganchos, nunca a los cierres).
- **Las guías `PUBLICAR-*.md|html` las regenera la app** a partir de `publicacion.json` cada vez que se guardan cambios de textos (reutilizando `md-a-html.py`), para que la versión del móvil no quede desfasada.
- **Repos propuestos**: `pedroleni/onlydevcoding-estudio-web` (Next.js) y `pedroleni/onlydevcoding-estudio-api` (FastAPI). Nombres cambiables.
- La página de grabación actual (`npm run grabar`) sigue funcionando en paralelo hasta que el teleprompter de la app la sustituya.

## Datos: qué existe hoy (fuente de verdad en disco)

Dos raíces, configurables:

**`CURSOS_DIR`** (`Cursos youtube/`, repo privado `tech-study-videos-material`):

- `<CURSO>/` (hoy `REACT/`; vendrá `PYTHON/`) → `<NN-slug>/` por lección:
  - `GUION.md`, `TELEPROMPTER.txt` (textos a cámara y ganchos de shorts).
  - `grabaciones/E03.wav…` (voz en off; tomas anteriores en `grabaciones/tomas/`), `grabaciones/videos/` (tomas a cámara originales e `ia/E01.mov…` mejoradas).
  - `previa/previa-vN.mp4` (versiones del render).
  - `publicar/1-youtube-leccion/` (vídeo final `curso-react-NN-<slug>.mp4`, `miniatura-*.jpg`), `publicar/2-shorts-y-reels/` (`short-N-*.mp4`, `reel-*.mp4`, `portada-*.jpg`, `portadas-opciones/`, `anteriores/`, `descartadas/`), `publicar/4-linkedin/`, `PUBLICAR-leccion-N.md|html`.

**`ESTUDIO_DIR`** (`tech-study-herramientas/videos-youtube/estudio/`, repo privado `tech-study-videos`):

- `lecciones/react-NN.json`: el guion de verdad (escenas con `id`, `modo` voz/camara/animacion, `tipo`, `titulo`, `datos`, `cues[{texto, paso, pausa}]`, `ganchos`, `carpeta`).
- `public/lecciones/react-NN/montaje.json`: tiempos y duraciones (fotogramas a 30 fps), códigos.
- `shorts/lN/shorts.json` y `public/shorts/<id>/montaje.json`: shorts.
- `herramientas/`: `preparar-leccion.mjs`, `alinear-voz.mjs`, `preparar-shorts.mjs`, `publicar/sonido-redes.sh`, `color/piel-natural`, `transcribir/Transcribir.app`, `grabacion/` (página de grabación actual: `servidor.mjs` + `index.html`, a portar).
- Renders: `npx remotion render src/index.ts <Composición> <salida> --props=…`.

**Nuevo — `publicar/publicacion.json` por lección** (lo escribe Claude; la app lo lee y permite editarlo): por pieza (`leccion`, `reel-salida`, `short-N`): archivo de vídeo, portadas candidatas, y por red `{titulo, descripcion, etiquetas, texto, notas}`, más ajustes de Studio y fecha propuesta. Hay que migrar a este formato las guías de las lecciones 1 a 4.

**Base de datos local (SQLite)**: portada elegida por pieza; estado por pieza y red (programado con fecha, publicado con fecha y URL opcional); tareas (fecha, curso, tipo, lección y pieza enlazadas opcionales, texto, hecha); tipos de tarea configurables; registro de trabajos lanzados.

## Pantallas

1. **Cursos**: lista de cursos → rejilla de lecciones con su estado (guion, voz, vídeo final, miniatura, publicado por red).
2. **Lección**: cabecera, botón «Abrir en el teleprompter», pestañas **Guion** (escenas con fotograma, modo y texto, editable) · **Grabaciones** (voz y cámara, escuchar/ver tomas) · **Vídeo final** (versiones, lanzar render) · **Shorts y reels** · **Publicar**; **panel de estado** fijo a la derecha.
3. **Publicar** (pestaña): ver bocetos.
4. **Teleprompter**: ver boceto; incluye ritmo, letra, micrófono, nivel, ensayar, grabar, parar, repetir, editar texto, vista previa sincronizada con la lectura y con la toma, conversión de nombres hablados («App punto jsx» → `App.jsx`) y números en cifras, como hoy.
5. **Tareas**: vista día / semana, filtros, crear y marcar.

## Acciones (lista cerrada)

Por lección o pieza, con progreso: mejorar con IA las tomas a cámara (opcional), alinear la voz grabada, preparar el montaje, generar la vista previa de grabación, render de la lección (nueva `previa-vN`), copia a −14 LUFS para publicar, preparar y renderizar shorts y reels, ajustar el color de los ganchos verticales (`piel-natural`), identificar y colocar tomas a cámara entregadas (transcribiendo con `Transcribir.app` y emparejando con los textos a cámara y los ganchos). Cada acción es una invocación fija con argumentos validados.

## Seguridad

Mismo marco que tech-study-tracker, adaptado a una app local sin login:

- **`AGENTS.md`** en cada repo: reglas, flujo de ramas `feat/…`/`fix/…` + PR contra `main`, nunca commits directos, merge solo con CI verde y revisada; orquestación de Codex como en tech-study-tracker.
- **`.claude/agents/security-*.md`** + **`/security-review`** + **`security/security-review-instructions.md`** con los precedentes de este proyecto. El agente de auth/RLS se sustituye por uno de **API local** (exposición, CSRF/DNS rebinding, ejecución de procesos, rutas).
- **Scanners `scripts/security/*.sh`**, **pre-commit** con `scan_secrets.sh` y **GitHub Actions** en cada PR; `security/reviews/` para auditorías.
- **Riesgos propios a cubrir**: API escuchando solo en `127.0.0.1`; comprobación estricta de `Origin` y `Host` y cabecera propia obligatoria (una web cualquiera no puede llamar a la API local); rutas resueltas siempre dentro de las dos raíces (sin `..`), ids validados con patrón; procesos solo de la lista cerrada, con lista de argumentos y sin shell; límites de tamaño y tipo en las subidas; copias de seguridad antes de escribir guiones; nada de datos privados en los repos públicos (las rutas en `.env`, ejemplos con datos falsos); dependencias fijadas con lockfile (`uv.lock`, `package-lock.json`).

## Desplegar el back más adelante

No hace falta ahora. Si algún día se publica, la API depende de carpetas y herramientas del Mac (Remotion, Swift, `Transcribir.app`), así que no basta con subirla: habría que pasar los archivos a un almacenamiento en la nube y separar las herramientas. Para una API Python sencilla, opciones habituales son Render, Railway o Fly.io.

## Lo que queda para quien la construya

Estructura interna de los repos, nombres de endpoints y componentes, el detalle visual fino dentro del estilo de los bocetos, el formato exacto de `publicacion.json` y de la base de datos, cómo portar la página de grabación (puede reutilizar su lógica de ritmo, troceado y grabación a WAV en el navegador), y el orden de construcción por fases.
