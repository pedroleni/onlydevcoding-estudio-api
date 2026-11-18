# Estudio OnlyDevCoding · Fase 6 (Entrega de tomas a cámara y ganchos verticales) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** El autor arrastra a la app las exportaciones de la cámara tal como salen (Facetune o iPhone). La app las reconoce por lo que dice en ellas y propone a qué escena a cámara o a qué gancho vertical pertenece cada una. Cuando el autor confirma, conserva el original con su nombre, coloca la copia renombrada donde la usa el render y deja la escena «grabada». A los ganchos les aplica `piel-natural`. Mejorar una toma con IA (`superres.sh`) queda como acción opcional.

**Architecture:**
- **Tres pasos con estado en disco:**
  1. **Entregar:** subida por streaming a `<lección>/grabaciones/entregas/`.
  2. **Identificar:** una herramienta nueva del estudio transcribe cada toma con `Transcribir.app`, la puntúa contra los textos a cámara y los ganchos, y escribe `entregas/propuesta.json`.
  3. **Colocar:** la API mueve, copia y escribe `escena.toma` en el guion o `shorts.json`, con las asignaciones que el autor confirma.
- **Reparto del trabajo:** lo que necesita el Mac (transcribir, `ffprobe`, CoreImage, VideoToolbox) va en herramientas del estudio, lanzadas como trabajos. Mover archivos y escribir JSON lo hace la API, con sus rutas seguras y su forma de instalar.
- **Reutilizar la alineación:** el emparejamiento por palabras de `alinear-voz.mjs` sale a un módulo común. Sirve para puntuar las tomas y para calcular `desde`, `hasta` y `cues` de las escenas a cámara. `alinear-voz` produce lo mismo que antes, byte a byte.
- **Web:** un componente `EntregaTomas` (soltar → subir con progreso → identificar → revisar la propuesta → colocar) en la pestaña Grabaciones y en la escena a cámara del teleprompter. Grabaciones enseña además las tomas a cámara y los ganchos con su vídeo y los botones «Mejorar con IA» y «Ajustar el color».

**Tech Stack:**
- **API:** Python 3.14, uv, FastAPI, Pydantic v2, pytest y ruff.
- **Web:** Next.js 16, TypeScript, Tailwind, Vitest y Testing Library.
- **Estudio:** Node (ESM) con `node --test`, sin dependencias nuevas.
- **Verificación:** Playwright sobre clones APFS.

**Spec:** `docs/specs/2026-11-16-estudio-onlydevcoding-design.md`, en estos apartados:
- «Decisiones del autor», Teleprompter: escenas a cámara 🎥 con botón para entregar los vídeos; la app los identifica, renombra y coloca.
- «Decisiones mías», Entrega de tomas a cámara: original con su nombre en `grabaciones/videos/`, copia renombrada donde la usa el render, escena «grabada», `superres.sh` como paso opcional, y ganchos a la carpeta de tomas del short con `piel-natural` (solo ganchos, nunca cierres).
- «Acciones»: mejorar con IA, ajustar el color de los ganchos, e identificar y colocar las tomas (transcribiendo con `Transcribir.app` y emparejando con los textos a cámara y los ganchos).
- «Seguridad»: límites de tamaño y tipo en las subidas, rutas dentro de las dos raíces y procesos de la lista cerrada.

**Bocetos:** `teleprompter.html`. En la escena a cámara aparece «⬆ Entregar los vídeos de la cámara · Arrastra aquí las tomas (Facetune, iPhone…) · La app los reconoce por lo que dices, los renombra (E17.mov), los copia a su sitio y la escena queda ✓ grabada.».

**Base:** la fase 5, integrada en `main`. Rama `feat/fase-6` en la API y en la web; rama `feat/entrega-tomas` en `tech-study-videos`.

## Contexto de ejecución

Igual que en la fase 5:
- **Implementación:** Codex implementa; si no tiene cuota, implementa Claude. Codex no abre nada en `datos/`. La tarea 1 va en una sesión de Codex aparte, con `-C` en el repo del estudio.
- **Commits:** los hace Claude, sin `Co-Authored-By` ni «Generated with», con el email `noreply` de GitHub en los repos públicos.
- **Verificación y revisión:** Claude verifica con Playwright sobre clones y encarga las revisiones.
- **El flujo actual no cambia:** las tomas ya colocadas a mano (lecciones 1–5) no se tocan, y las herramientas se siguen lanzando igual desde la terminal.

## Hoy, a mano (lo que la app automatiza)

- **Cámara:**
  - el original queda en `<lección>/grabaciones/videos/<nombre de Facetune>.MOV`;
  - la copia, en `ESTUDIO/public/grabaciones/<guion>/<E>.mov`;
  - en el guion, `escena.toma = {original: "grabaciones/videos/<nombre>", video: "grabaciones/<guion>/<E>.mov", desde, hasta, cues[], momentos?, cortes?}` (segundos del vídeo; `cues[i]` es el segundo en que empieza la frase `i`).
  - `preparar-leccion.mjs` usa la toma (duración, audio del vídeo) solo si existe `escena.toma`.
- **IA:** `superres.sh <original> <salida>` deja la mejorada en `public/grabaciones/<guion>/<E>.mov` y una copia durable en `<lección>/grabaciones/videos/ia/<E>.mov`.
- **Ganchos:**
  - id de la toma = 8 primeros hex del UUID de Facetune (`B0C045C7`);
  - copias en `public/shorts/l<N>/tomas/original/<ID>.mov` y `public/shorts/l<N>/tomas/<ID>.mov`, este último con `piel-natural`;
  - palabras reconocidas en `shorts/l<N>/tomas/<ID>.json` (formato de `Transcribir.app`: `[{t, desde, dura}]`) y audio en `<ID>.wav` (16 kHz, mono);
  - en `shorts/l<N>/shorts.json`, `tomas[ID]` = texto corregido.
  - Los cierres (la toma vertical común al final de los shorts) van igual, pero sin color.

## Global Constraints

- **Siguen en vigor las de las fases 1 a 5:**
  - `127.0.0.1`, Host, Origin y `Sec-Fetch-Site`;
  - escrituras con `X-Estudio-Token`, `Content-Length` obligatorio y 256 KB (salvo las subidas);
  - nada privado en los repos públicos (ni rutas del Mac ni textos de lecciones; los tests usan datos falsos);
  - castellano de España y tema oscuro;
  - trabajos de uno en uno → 409 «Ya hay un trabajo en marcha»;
  - mensajes de error fijos, sin rutas;
  - entorno mínimo de los procesos más `CURSOS_DIR`;
  - guion escrito con `indent=2` + `\n`, copia `.antes-de-editar` y versión SHA-256.
- **Subida de tomas** (`PUT /api/cursos/{curso}/lecciones/{numero}/entregas/{archivo}`):
  - `archivo` cumple `^[A-Za-z0-9_(][A-Za-z0-9 _().-]{0,115}\.(?i:mov|mp4)$`; si no, 422 «Ese nombre de archivo no se admite: renómbralo con letras sin acentos, números, espacios, guiones o puntos».
  - `Content-Type` `video/quicktime` o `video/mp4`; si no, 415 «La toma tiene que ser un vídeo MOV o MP4».
  - Tamaño máximo `TAMANO_MAXIMO_ENTREGA = 4_294_967_296` (4 GiB), con hasta 10 dígitos de `Content-Length`; si no, 413 «La toma supera el límite de 4 GiB».
  - Los bytes 4–8 son `ftyp`; si no, 422 «El archivo no es un vídeo MOV o MP4».
  - Se escribe en un temporal oculto `.<archivo>.subiendo` del mismo directorio y se instala sin pisar.
  - Si ya existe ese nombre en `entregas/` o en `grabaciones/videos/` → 409 «Ya hay una toma con ese nombre».
  - Si la subida se corta, no queda nada.
- **Id de una toma vertical:** `^Facetune([0-9A-Fa-f]{8})` → esos 8 caracteres en mayúsculas; si no, los 8 primeros hex en mayúsculas de `sha256(archivo)`.
- **Carpeta de shorts de la lección:** `ESTUDIO/shorts/l<numero>/`, con `public/shorts/l<numero>/` (como `preparar-shorts`).
- **Ajuste aprobado de `piel-natural`** (literal): `exposicion=-0.05,altas=0.88,calidez=-450,tinte=3,vibrancia=0,curva=0.02,detalle=0.7,grano=0.05`.
- **Acciones nuevas** (`cwd=ESTUDIO_DIR`, `<guion>` = `f"{curso}-{numero:02d}"`):

  | id | Etiqueta | Comando | Resultado | Tiempo máx. | Progreso |
  |---|---|---|---|---|---|
  | `identificar-tomas` | Identificar las tomas | `[node, "herramientas/identificar-tomas.mjs", <guion>]` | escribe `entregas/propuesta.json` | 1 h | `^PROGRESO (\d+)/(\d+)$` |
  | `color-ganchos` (objetivo: gancho; opción `gancho` obligatoria, `^[A-Za-z0-9_-]{1,40}$`, que esté en `ganchosEntregados` o 422 «Ese gancho no está entregado»; `opciones` = ganchos entregados, `ultimos` = el último trabajo por gancho) | Ajustar el color de los ganchos | `[node, "herramientas/color/ganchos.mjs", "l<numero>", <ID de la toma del gancho>]` | escribe en su sitio, solo esa toma | 1 h | `^PROGRESO (\d+)/(\d+)$` |
  | `mejorar-toma` (objetivo: escena) | Mejorar con IA | `["/bin/zsh", "-f", "herramientas/superres/superres.sh", <original absoluto>, <temporal>]` | `public/grabaciones/<guion>/<E>.mov`, archivando el anterior, y copia en `<lección>/grabaciones/videos/ia/<E>.mov`, archivando la anterior | 3 h | ninguno |

  - **Requisitos** (409 con el mensaje literal):
    - `identificar-tomas`: hay al menos un vídeo en `entregas/` → «No hay tomas entregadas».
    - `color-ganchos`: `shorts.json` con `ganchosEntregados` no vacío → «No hay ganchos entregados».
    - `mejorar-toma`: la opción `escena` es una escena de cámara del guion (si no, 422 «Esa escena no existe») y tiene `toma.original`, que existe dentro de la carpeta de la lección → «Esa escena aún no tiene toma».
  - **Lección ocupada:** `identificar-tomas` se suma a `alinear-voz`, `preparar-montaje` y `preparar-shorts`. Mientras corre, la edición de textos da 409 como en la fase 5.
  - **Mensajes:** `MENSAJES_HERRAMIENTA`.
- **Propuesta** (`entregas/propuesta.json`, la escribe la herramienta; la API la valida al leerla y descarta las entradas que no cumplen o cuyo archivo ya no está):

  ```json
  {"version": 1, "guion": "react-04", "archivos": [
    {"archivo": "Facetune… 2.MOV", "bytes": 123, "orientacion": "horizontal", "duracion": 40.6,
     "texto": "<reconocido, ≤ 2000 caracteres>", "propuesta": {"tipo": "camara", "id": "E17"}, "repite": null,
     "candidatos": [{"tipo": "camara", "id": "E17", "puntuacion": 0.62, "desde": 0.0, "hasta": 40.6, "cues": [0.0, 14.1, 30.0]}]}]}
  ```

  - `tipo`: `camara` (ids `^E\d{2}$`) o `gancho` (ids de `guion.ganchos`).
  - `propuesta` y `repite`: `null` o un destino.
  - Números finitos, entre 0 y la duración.
  - `cues`: tantos como frases tenga la escena.
- **Colocar** (`POST /api/cursos/{curso}/lecciones/{numero}/entregas/colocar`, cuerpo `{"asignaciones": [{"archivo": str, "destino": str | null}]}`, con `extra="forbid"`):
  - **Destinos:** `E\d{2}` (cámara), id de gancho o `"cierre"`. `null` = no usar: el archivo se queda en `entregas/`.
  - **Validación previa, sin tocar nada si algo falla:**
    - sin propuesta → 409 «Identifica las tomas antes de colocarlas»;
    - un trabajo en marcha → 409 «Ya hay un trabajo en marcha»;
    - archivo fuera de la propuesta o del disco → 422 «Esa toma no está entregada»;
    - destino inexistente → 422 «Ese destino no existe»;
    - horizontal a gancho o cierre, o vertical a escena de cámara → 422 «Esa toma no encaja con ese destino»;
    - dos archivos al mismo destino (salvo `cierre`) → 422 «Hay dos tomas para el mismo destino».
  - **Cámara `E`:**
    1. mover `entregas/<archivo>` → `<lección>/grabaciones/videos/<archivo>` (`os.rename`);
    2. copiar a `ESTUDIO/public/grabaciones/<guion>/<E>.mov`, archivando la anterior;
    3. `.analisis/<archivo>.json` → `ESTUDIO/lecciones/tomas/<guion>/<E>-camara.json`;
    4. en el guion, `escena.toma = {"original": "grabaciones/videos/<archivo>", "video": "grabaciones/<guion>/<E>.mov", "desde", "hasta", "cues"}` del candidato `camara/E`. Sustituye la toma anterior entera; sus `momentos` y `cortes` se pierden porque iban medidos sobre otro vídeo.
  - **Gancho o cierre:**
    1. mover el original como arriba;
    2. copiar a `public/shorts/l<N>/tomas/original/<ID>.mov` y a `public/shorts/l<N>/tomas/<ID>.mov`, archivando las anteriores;
    3. `.analisis/<archivo>.json` y `.wav` → `shorts/l<N>/tomas/<ID>.json|.wav`;
    4. en `shorts.json`, que se crea si falta como `{"leccion": <guion>, "numero": N, "tomas": {}, "ganchosEntregados": {}, "frases": {}, "shorts": []}`: `tomas[ID]` = el texto del gancho del guion (o, en un cierre, el texto reconocido) y, solo en ganchos, `ganchosEntregados[<id gancho>] = ID`.
  - **Al terminar:** se borran `.analisis/<archivo>.*` y la entrada de la propuesta; si `entregas/` queda sin vídeos, se borra también `propuesta.json`.
  - **Respuesta:** `{"colocadas": [{"archivo", "destino"}], "ganchos": <n de ganchos colocados>}`.
  - Guion y `shorts.json` se escriben bajo el cerrojo de escritura del guion, con su copia `.antes-de-editar`.
- **Emparejar (herramienta):**
  - **Puntuación** de un destino = palabras de su texto que casan con lo reconocido / palabras de su texto. Se usa la subsecuencia común con `casan` de `alinear-voz` y la conversión de cifras a letra. El texto de una escena de cámara son sus `cues[].texto` unidos; el de un gancho, su `texto`.
  - **Orientación:** horizontal si el ancho mostrado (aplicando la rotación) ≥ el alto. Las horizontales solo se comparan con escenas de cámara; las verticales, con ganchos.
  - **Candidatos:** uno por cada destino de su orientación (todas las escenas de cámara o todos los ganchos), con sus tiempos, para que al cambiar el destino a mano también los haya.
  - **Propuesta:** el mejor destino si su puntuación ≥ 0,35 y supera al segundo en ≥ 0,10; si no, `null`.
  - **Repeticiones:** si varias tomas proponen el mismo destino, se queda la de `creation_time` más reciente (si no hay, `mtime`); las demás pasan a `propuesta: null, repite: <destino>`.
  - **Tiempos:**
    - `desde` = inicio de la primera palabra reconocida − 0,2 (mínimo 0);
    - `hasta` = fin de la última + 0,3 (máximo la duración);
    - `cues` de una escena de cámara: el inicio de cada frase con el algoritmo de `alinear-voz`, y `cues[0] = desde`.

## Review Focus

1. **Dos tomas de la misma escena** (lo normal cuando el autor repite): solo una se propone y la otra queda como «repetida de E17». Si se fuerzan las dos al mismo destino → 422 sin mover nada. Tests en las tareas 1 y 4.
2. **La subida se corta, o se sube dos veces el mismo archivo:** no queda ningún `.subiendo` ni archivo a medias, y el segundo intento da 409 sin tocar el primero. Test en la tarea 2.
3. **Entregar de nuevo una escena que ya tenía toma (con `momentos`):** la copia anterior acaba en `anteriores/` byte a byte igual, el guion tiene `.antes-de-editar` y la nueva toma no lleva los `momentos` viejos. La web avisa antes de colocar. Tests en las tareas 4 y 6.
4. **Una `propuesta.json` manipulada o desfasada** (`archivo: "../../x"`, números negativos o `NaN`, un destino que no existe, un archivo ya borrado): la API ignora esas entradas, nunca sale de `entregas/` y no escribe en el guion valores que no ha validado. Tests en las tareas 3 y 4.
5. **Las tomas ya colocadas a mano y las herramientas de siempre no cambian:** `alinear-voz` produce las mismas alineaciones byte a byte, y las lecciones 1–5 se leen igual en la app. Comprobación en la tarea 1 y test en la tarea 5.

---

### Tarea 1: Herramientas del estudio: identificar las tomas y el color de los ganchos (repo `tech-study-videos`)

**Files** (en `ESTUDIO_DIR`, rama `feat/entrega-tomas`):
- Create: `herramientas/alinear.mjs`, `herramientas/identificar-tomas.mjs` y `herramientas/color/ganchos.mjs`
- Modify: `herramientas/alinear-voz.mjs` (importa de `alinear.mjs`, sin cambiar lo que produce) y `herramientas/superres/superres.sh` (`npx --no`)
- Test: `herramientas/alinear.test.mjs` y `herramientas/identificar-tomas.test.mjs` (`node --test herramientas/`)

**Interfaces:**
- **Produces, `alinear.mjs`:** `normalizar`, `palabras`, `aLetra`, `casan` y `alinear` (los de `alinear-voz` tal cual). Además:
  - `reconocidasAPalabras(reconocidas) → [{p, desde, hasta}]`: el reparto de tiempo de `alinear-voz`.
  - `puntuar(texto: string, r) → number` (0–1).
  - `iniciosDeFrases(cuesTexto: string[], r) → number[]`: el inicio de cada frase con las reglas de `alinear-voz` (adelanto por palabras que no casan, reparto de lo sobrante y frases sin palabras entre sus vecinas).
- **Produces, `identificar-tomas.mjs <guion>`:**
  - lee el guion y los vídeos de `<CURSOS_DIR>/<carpeta>/grabaciones/entregas/` (`.mov`/`.mp4` en cualquier caja, sin ocultos);
  - con `npx --no remotion ffprobe` saca ancho, alto, rotación, duración y `creation_time`;
  - extrae `entregas/.analisis/<archivo>.wav` (16 kHz, mono, `pcm_s16le`) y transcribe a `.analisis/<archivo>.json`. Reutiliza ambos si `.analisis/<archivo>.origen` coincide con `"<bytes>:<mtimeMs>"`;
  - escribe `entregas/propuesta.json` con las reglas de «Emparejar» (por un temporal + `rename`);
  - imprime `PROGRESO i/total` por toma.
  - Funciones puras exportadas para los tests: `orientacion({ancho, alto, rotacion})`, `proponer(tomas, destinos)` y `tiempos(r, duracion, cuesTexto?)`. El código que lanza procesos queda tras `if (import.meta.url === pathToFileURL(process.argv[1]).href)`.
- **Produces, `color/ganchos.mjs l<N>`:**
  - para cada `ID` de `ganchosEntregados` de `shorts/l<N>/shorts.json`, ejecuta `herramientas/color/piel-natural video public/shorts/l<N>/tomas/original/<ID>.mov <temporal oculto> <ajuste aprobado>`;
  - después `rename` a `tomas/<ID>.mov` y escribe `shorts/l<N>/tomas/<ID>.color` con el ajuste;
  - `PROGRESO i/total` por gancho; los cierres no se tocan.

- [ ] **Step 1: Tests que fallan** (`node --test`):
  - `puntuar("Tres casas rojas, y el gato duerme tranquilo", r)` con `r` de «tres casas rojas de y el gato duerme tranquilo» → 1; con un texto sin relación → < 0,2.
  - `orientacion({ancho: 1920, alto: 1080, rotacion: -90})` → `"vertical"`; `({ancho: 1080, alto: 1916, rotacion: 0})` → `"vertical"`; `({ancho: 1920, alto: 1080, rotacion: 0})` → `"horizontal"`.
  - `proponer`:
    - con puntuaciones 0,62 y 0,30 → propone la primera;
    - con 0,40 y 0,35 → `null` (margen < 0,10);
    - con 0,30 → `null`;
    - dos tomas a E17 con `creation_time` distinto → la más reciente propuesta y la otra con `repite: "E17"` (Review Focus 1).
  - `tiempos` con palabras de 0,45 a 21,4 s y duración 21,6 → `desde 0.25`, `hasta 21.6`; con dos frases cuya segunda empieza en la palabra de 9,0 s → `cues [0.25, 9.0]`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar.
- [ ] **Step 4: Comprobar sobre clones** (nunca sobre los datos reales; Review Focus 5):
  - En clones APFS del estudio y de `Cursos youtube`, con `CURSOS_DIR=<clon>`, `node herramientas/alinear-voz.mjs react-04` antes y después del cambio → los `*-voz.json` son byte a byte iguales (usa la caché `.origen`).
  - Copiar al `entregas/` de la lección 4 del clon sus tres originales de `grabaciones/videos/` y lanzar `identificar-tomas.mjs react-04` → propone E01, E08 y E17. `desde`, `hasta` y `cues` quedan a ≤ 1 s de los del guion hecho a mano (E01 `0.25/21.6/[0.25, 9.0]`, E08 `0.3/39.0/[0.3, 18.4]`, E17 `0.0/40.6/[0.0, 14.1, 30.0]`); si alguno se aleja más, se anota en el informe con el valor obtenido.
  - Con los tres originales verticales de la lección 3 (`grabaciones/reels videos intro/`) → propone S2, S3 y S4.
  - `color/ganchos.mjs l3` sobre un `shorts.json` del clon con un `ganchosEntregados` de prueba deja `tomas/<ID>.mov` con el tamaño del original y su `.color`.
- [ ] **Step 5: Commit** `Herramientas: identificar las tomas entregadas, color de los ganchos y alineación común` en `feat/entrega-tomas`.

### Tarea 2: Subir y listar las tomas entregadas (API)

**Files:**
- Create: `estudio_api/entregas.py` y `estudio_api/rutas_entregas.py`
- Modify: `estudio_api/seguridad.py` (`LIMITES_POR_RUTA` pasa a llevar también el máximo de dígitos de cada ruta) y `estudio_api/app.py`
- Test: `tests/test_entregas.py`

**Interfaces:**
- **Consumes:** `carpeta_de_trabajo`, `datos_curso`, `ruta_segura` y el patrón de streaming de `tomas.guardar_toma`.
- **Produces:**
  - `PATRON_ARCHIVO_ENTREGA` y `TAMANO_MAXIMO_ENTREGA` (Global Constraints).
  - `guardar_entrega(config, curso, numero, archivo, trozos: AsyncIterator[bytes], longitud) -> ArchivoEntregado{archivo: str, bytes: int}`.
  - `listar_entregas(config, curso, numero) -> list[ArchivoEntregado] | None`, ordenada por nombre.
  - `borrar_entrega(config, curso, numero, archivo) -> bool`, que borra también `.analisis/<archivo>.*`.
  - Rutas: `PUT` y `DELETE /api/cursos/{curso}/lecciones/{numero}/entregas/{archivo}` (201 y 204; 404 si la lección o el archivo no existen) y `GET .../entregas` → `list[ArchivoEntregado]`.
  - `carpeta_entregas(config, curso, numero) -> Path | None`, para las tareas 3 y 4.

- [ ] **Step 1: Tests que fallan:**
  - un MOV falso de 3 MB (con `ftyp`) → 201, el archivo está en `entregas/` con su nombre y aparece en el `GET`;
  - los nombres `../x.mov`, `.oculto.mov`, `Vídeo.mov`, `a/b.mov` y `x.exe` → 422 sin escribir; `Facetune0A1B2C3D-… 2.MOV` y `IMG_1234.mp4` → 201;
  - `Content-Type: text/plain` → 415; `Content-Length` de 11 dígitos → 413 desde el middleware; sin `ftyp` → 422 sin dejar nada;
  - el mismo nombre dos veces → 409 y el primero intacto; un nombre que ya está en `grabaciones/videos/` → 409 (Review Focus 2);
  - un cliente que se desconecta a mitad → 400 y sin `.subiendo` (Review Focus 2);
  - `DELETE` → 204, desaparece con sus `.analisis/*`; uno inexistente → 404;
  - un enlace simbólico plantado como `entregas/` o como el temporal no hace que se escriba fuera de la carpeta de la lección.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS + ruff.
- [ ] **Step 5: Commit** `Entregas: subir, listar y quitar tomas de cámara`.

### Tarea 3: Acciones nuevas y copia durable en el motor (API)

**Files:**
- Modify: `estudio_api/trabajos.py` (`PlanTrabajo.copia`), `estudio_api/acciones.py` (tres acciones y la lección ocupada) y `estudio_api/modelos.py` (`OpcionesAccion.escena`)
- Create: `estudio_api/propuesta.py` (leer y validar `propuesta.json`)
- Test: `tests/test_trabajos.py`, `tests/test_acciones.py` y `tests/test_propuesta.py`

**Interfaces:**
- **Produces:**
  - `PlanTrabajo.copia: Path | None = None`: tras instalar el destino con éxito, se copia a `copia` por un temporal oculto + `os.replace`, archivando la anterior como en `archivar`. Si la copia falla, el trabajo queda `error` con «No se pudo guardar el resultado» y el destino ya instalado se conserva.
  - `IdAccion` suma `identificar-tomas`, `color-ganchos` y `mejorar-toma`, con los comandos, requisitos y mensajes de Global Constraints. `OpcionesAccion` gana `escena: str | None` (`^E\d{2}$`).
  - `EstadoAccion.opciones` de `mejorar-toma` = las escenas de cámara con toma; `ultimos` = el último trabajo por escena.
  - `leer_propuesta(config, curso, numero) -> Propuesta | None`, con los modelos `Propuesta`, `TomaPropuesta` y `Candidato` de Global Constraints validados con Pydantic (`extra="ignore"`, números finitos). Descarta las entradas inválidas o sin archivo en disco; JSON roto o de otro guion → `None`.
  - `GET .../entregas` pasa a devolver `Entregas{archivos: list[ArchivoEntregado], propuesta: Propuesta | None, destinos: Destinos}`:
    - `Destinos{camara: list[{id, titulo, tiene_toma: bool}]; ganchos: list[{id, titulo, entregado: bool}]}`;
    - `tiene_toma` = la escena tiene `toma` en el guion; `entregado` = el id está en `ganchosEntregados`.

- [ ] **Step 1: Tests que fallan:**
  - **Copia:** un plan con `copia` deja destino y copia iguales; con una copia previa, esta queda en `anteriores/`; con `os.replace` de la copia forzado a fallar → `error` y el destino instalado.
  - **Comandos exactos:** `identificar-tomas` → `[node, "herramientas/identificar-tomas.mjs", "react-04"]` con `CURSOS_DIR`; `color-ganchos` → `[node, "herramientas/color/ganchos.mjs", "l4"]`; `mejorar-toma` con `escena="E17"` → `["/bin/zsh", "-f", "herramientas/superres/superres.sh", <original absoluto>, <temporal>]`, con destino y copia de Global Constraints.
  - **Requisitos:** sin entregas → 409 «No hay tomas entregadas»; sin `ganchosEntregados` → 409 «No hay ganchos entregados»; `escena="E99"` → 422 «Esa escena no existe»; escena de cámara sin toma → 409 «Esa escena aún no tiene toma»; `toma.original` = `"../../fuera.mov"` → 409 con el mismo mensaje, sin lanzar.
  - **Lección ocupada:** con `identificar-tomas` en marcha, editar un texto del guion → 409.
  - **Propuesta (Review Focus 4):** una propuesta con `archivo: "../../x.mov"`, `desde: -1`, `cues` con `NaN`, un `id` `"E1"`, una entrada sin archivo en disco y otra válida → solo queda la válida. JSON roto o `guion` de otra lección → `None`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS + ruff.
- [ ] **Step 5: Commit** `Acciones: identificar tomas, color de los ganchos y mejorar con IA`.

### Tarea 4: Colocar las tomas (API)

**Files:**
- Create: `estudio_api/colocar.py`
- Modify: `estudio_api/rutas_entregas.py` y `estudio_api/guion_textos.py` (escribir `escena.toma` con el mismo cerrojo, la misma copia y el mismo formato)
- Test: `tests/test_colocar.py`

**Interfaces:**
- **Consumes:** las tareas 2 y 3, `ruta_segura` y la instalación `archivar` de `trabajos.py`, sacada a una función reutilizable si hace falta.
- **Produces:**
  - `colocar_tomas(config, bd, curso, numero, asignaciones: list[Asignacion]) -> ResultadoColocar` con las reglas de «Colocar» de Global Constraints.
  - Lanza `ColocacionNoValida(estado_http, mensaje)` con esos mensajes.
  - Ruta `POST .../entregas/colocar`.
  - `id_toma_vertical(archivo: str) -> str`.

- [ ] **Step 1: Tests que fallan** (con un guion y un `ESTUDIO_DIR` falsos):
  - **Cámara:** colocar `toma-a.mov` en E17 →
    - el original está en `grabaciones/videos/toma-a.mov` y ya no en `entregas/`;
    - `public/grabaciones/<guion>/E17.mov` es igual byte a byte;
    - `lecciones/tomas/<guion>/E17-camara.json` existe;
    - el guion tiene `toma` con `desde`, `hasta` y `cues` del candidato;
    - `.antes-de-editar` y formato `indent=2`.
  - **Toma anterior (Review Focus 3):** E17 tenía `toma` con `momentos` y su `.mov` → el `.mov` viejo está en `anteriores/`, igual byte a byte, y la toma nueva no tiene `momentos`.
  - **Gancho:** colocar `Facetune0A1B2C3D-… 2.MOV` en S2 → copias en `tomas/original/0A1B2C3D.mov` y `tomas/0A1B2C3D.mov`, `.json` y `.wav` en `shorts/l4/tomas/`; `shorts.json` creado con `tomas["0A1B2C3D"]` = texto del gancho S2 y `ganchosEntregados["S2"] = "0A1B2C3D"`. Con un `shorts.json` existente, solo se añaden esas claves y el resto queda igual.
  - **Cierre:** sin `ganchosEntregados`, con `tomas[ID]` = texto reconocido.
  - **Validación sin efectos:** sin propuesta → 409; con un trabajo en marcha → 409; horizontal a S2 → 422 «Esa toma no encaja con ese destino»; dos a E17 → 422 «Hay dos tomas para el mismo destino» (Review Focus 1); un archivo que no está → 422. En todos, el disco queda igual (hash del árbol antes y después).
  - **Limpieza:** tras colocar todo, desaparecen `.analisis/<archivo>.*`, las entradas de la propuesta y, si no quedan vídeos, `propuesta.json`. `destino: null` deja ese archivo en `entregas/` y en la propuesta.
  - `id_toma_vertical("IMG_1234.MOV")` → 8 hex en mayúsculas, el mismo siempre.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS + ruff.
- [ ] **Step 5: Commit** `Entregas: colocar las tomas de cámara, los ganchos y los cierres`.

### Tarea 5: Tomas a cámara y ganchos en la lección (API)

**Files:**
- Create: `estudio_api/camara.py`
- Modify: `estudio_api/rutas_entregas.py`
- Test: `tests/test_camara.py`

**Interfaces:**
- **Produces:** `GET /api/cursos/{curso}/lecciones/{numero}/camara` → `TomasCamara`:
  - `escenas: list[{id, titulo, video: str | None, version: int | None, original: str | None, mejorada: bool}]`:
    - `video`: ruta pública de `public/grabaciones/<guion>/<E>.mov`, como la usa `medios`;
    - `original`: el nombre de archivo de `toma.original`, sin carpetas;
    - `mejorada`: existe `grabaciones/videos/ia/<E>.mov`.
  - `ganchos: list[{id, titulo, toma: str | None, video: str | None, version: int | None, color: bool}]`:
    - `toma`: el id de `ganchosEntregados`;
    - `color`: `shorts/l<N>/tomas/<ID>.color` existe y su `mtime` ≥ el del `.mov`.
  - 404 si la lección no existe.

- [ ] **Step 1: Tests que fallan:**
  - una escena con toma e IA → `mejorada: true` y `video` con ruta pública; una sin toma → todo `null`;
  - un gancho entregado con `.color` posterior al `.mov` → `color: true`; si se vuelve a colocar (`.mov` posterior) → `false`;
  - **compatibilidad (Review Focus 5):** una lección con tomas colocadas a mano (con `toma.original`, la copia en `public/grabaciones/` e `ia/`, y sin `ganchosEntregados`) se lee sin errores y sus escenas salen con su vídeo.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS + ruff.
- [ ] **Step 5: Commit** `Lección: tomas a cámara y ganchos con su estado`.

### Tarea 6: Entregar las tomas desde la web

**Files** (repo web, rama `feat/fase-6`):
- Create: `src/app/entregar/[curso]/[numero]/[archivo]/route.ts` (proxy `PUT`, como el de `grabar`), `src/components/entregas/EntregaTomas.tsx`, `src/components/entregas/subirEntrega.ts` y `src/lib/acciones-entregas.ts` (Server Actions `leerEntregas`, `quitarEntrega` y `colocarTomas`)
- Modify: `src/lib/tipos.ts` y `src/lib/catalogo-acciones.ts` (acciones nuevas)
- Test: `src/components/entregas/EntregaTomas.test.tsx`, `subirEntrega.test.ts` y `src/app/entregar/.../route.test.ts`

**Interfaces:**
- **Consumes:** las rutas de las tareas 2–4; `lanzarAccion`, `useSeguimientoTrabajo` y `BotonAccion` de la fase 5.
- **Produces:**
  - **Proxy:** el route handler valida Host y Origin, la ruta, el nombre (mismo patrón), `Content-Length` (≤ 4 GiB, ≤ 10 dígitos) y el tipo, y reenvía con el token. Los errores son los de la API.
  - **`subirEntrega(curso, numero, archivo: File, alAvanzar: (fraccion) => void, señal: AbortSignal) -> Promise<ResultadoSubida>`** con `XMLHttpRequest` (para el progreso) y `encodeURIComponent` del nombre.
  - **`<EntregaTomas curso numero escena?>`:**
    1. **Zona de soltar** con el texto del boceto («⬆ Entregar los vídeos de la cámara», «Arrastra aquí las tomas (Facetune, iPhone…)») y un `<input type="file" multiple accept="video/quicktime,video/mp4,.mov,.mp4">` accesible.
    2. **Subidas** de una en una, con barra de progreso por archivo y «Cancelar». Un error de un archivo no corta los demás.
    3. **Identificar:** al acabar las subidas, lanza `identificar-tomas` automáticamente y sigue el trabajo.
    4. **Revisión:** una fila por archivo con nombre, horizontal o vertical, duración, los primeros 140 caracteres de lo reconocido y un `<select>` de destino. Las opciones son las escenas de cámara (horizontal) o los ganchos más «Cierre» (vertical), y «No usar». Va preseleccionado con `propuesta`; si hay `repite`, lo dice: «Repetida de E17». Cada fila tiene «Quitar».
    5. **«Colocar las tomas»:** si algún destino ya tiene toma, pide confirmación con «E17 ya tiene una toma: la nueva la sustituye (la anterior se guarda en anteriores/) y se pierden las animaciones puestas sobre ella.» (Review Focus 3).
    6. **Tras colocar:** si `ganchos > 0`, lanza `color-ganchos` y lo sigue. Después muestra «Tomas colocadas.» y refresca la ruta.
    - Con `escena`, la zona aparece en esa escena del teleprompter y la escena sale preseleccionada si la propuesta la deja en `null`.

- [ ] **Step 1: Tests que fallan:**
  - **Proxy:** sin Origin → 403; `../x.mov` → 400; `Content-Length` de 11 dígitos → 413; `text/plain` → 415; uno válido reenvía con `X-Estudio-Token` y conserva el estado de la API.
  - **`subirEntrega`:** con un `XMLHttpRequest` falso, informa del progreso, codifica el nombre con espacios y resuelve con el error de la API en un 409.
  - **`EntregaTomas`:**
    - soltar dos archivos los sube en orden y lanza `identificar-tomas` una vez;
    - con una propuesta falsa, las filas salen preseleccionadas, una vertical ofrece ganchos y «Cierre» pero no escenas, y «Repetida de E17» aparece;
    - colocar con E17 `tiene_toma` pide confirmación y, si se cancela, no llama a `colocarTomas`;
    - con `ganchos: 1`, lanza `color-ganchos`;
    - un 422 de colocar muestra el mensaje de la API en un `role="alert"`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** lint, `tsc`, tests y build en el clon.
- [ ] **Step 5: Commit** `Entregar las tomas: subir, identificar, revisar y colocar`.

### Tarea 7: Grabaciones y teleprompter con las tomas a cámara

**Files:**
- Create: `src/components/entregas/TomasCamara.tsx` y `src/lib/camara.ts` (lectura de `/camara`)
- Modify: la pestaña Grabaciones de la página de la lección (debajo de `GrabacionesVoz`) y `src/components/teleprompter/Teleprompter.tsx` (escena de cámara)
- Test: `src/components/entregas/TomasCamara.test.tsx` y el caso nuevo en `Teleprompter.test.tsx`

**Interfaces:**
- **Consumes:** la tarea 5 (`TomasCamara`), la 6 (`EntregaTomas`) y `BotonAccion`.
- **Produces:**
  - **En Grabaciones**, la sección «Tomas a cámara y ganchos» tiene:
    - el `EntregaTomas` de la lección;
    - una fila por escena de cámara con `<video controls preload="metadata">` (`?…&v=<version>`), el nombre del original, «✓ Mejorada con IA» si `mejorada` y un `BotonAccion` `mejorar-toma` con `objetivo` = la escena y la confirmación «Tarda unos 15 minutos por toma. ¿Mejorar E17 con IA?»; sin toma, «Sin grabar»;
    - una fila por gancho con su vídeo, «Color ajustado» o «Color sin ajustar», y un `BotonAccion` `color-ganchos` para toda la lección;
    - con `lecturaApiOpcional`, la pestaña no cae si `/camara` falla (como en la fase 5).
  - **En el teleprompter**, la escena de cámara muestra su texto, como hoy, y debajo `<EntregaTomas escena="E17">`; con toma, «✓ Grabada».

- [ ] **Step 1: Tests que fallan:**
  - una escena con `video` tiene `<video>` con `&v=`, otra sin toma «Sin grabar»;
  - `mejorar-toma` envía `{ escena: "E17" }` tras confirmar;
  - un gancho sin `.color` pone «Color sin ajustar»;
  - en el teleprompter, la escena 🎥 tiene la zona de entrega y la de voz no;
  - si `/camara` falla, el resto de Grabaciones se sigue viendo con un aviso.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** lint, `tsc`, tests y build en el clon.
- [ ] **Step 5: Commit** `Grabaciones y teleprompter: tomas a cámara, ganchos, IA y color`.

### Tarea 8: Verificación real y cierre

- [ ] **Step 1: Arranque.** Clones APFS de `Cursos youtube/REACT` y de `ESTUDIO_DIR` (con `node_modules` y la rama `feat/entrega-tomas`), una copia de la BD real y la API y la web de las ramas apuntando a ellos.
- [ ] **Step 2: Recorrido con Playwright:**
  - **Cámara:** en la lección 4 del clon, quitar `escena.toma` de E01, E08 y E17 (y sus copias en `public/grabaciones/react-04/`). Desde Grabaciones, soltar sus tres originales:
    - las subidas avanzan e «Identificar» propone E01, E08 y E17;
    - al colocar, las escenas salen ✓ y el guion tiene la toma con tiempos a ≤ 1 s de los hechos a mano;
    - aparece «Guion cambiado» y «Preparar el montaje» acaba `hecho`.
  - **Repetición:** soltar otra vez uno de ellos con otro nombre → «Repetida de …»; forzarlo al mismo destino → error.
  - **Teleprompter:** en una escena 🎥, la zona de entrega funciona igual.
  - **Ganchos:** en la lección 3 del clon, soltar sus tres verticales:
    - propone S2–S4;
    - al colocar se lanza el color y los ganchos salen «Color ajustado»;
    - `shorts.json` conserva sus `shorts`;
    - «Preparar los shorts» acaba `hecho`.
  - **IA:** «Mejorar con IA» sobre la toma más corta acaba `hecho`, con la copia en `ia/` (o se cancela limpio si tarda más de 20 min, y se anota).
  - **Datos reales intactos:** la carpeta real de la lección y la BD real no cambian.
  - **Calidad:** 0 errores de consola y sin scroll horizontal a 390 px.
- [ ] **Step 3:** `/security-review` en los dos repos, con atención a la subida (nombres, tamaño y enlaces), la propuesta leída del disco y los comandos nuevos. Guardar los informes y arreglar lo que salga.
- [ ] **Step 4:** Revisión final de las dos ramas con un revisor nuevo, y arreglos.
- [ ] **Step 5:** Push y PR de los tres repos (el de `tech-study-videos` primero) con la CI en verde, con permiso del autor. Merge solo con su visto bueno.

## Cambios tras la verificación (decisión del autor)

- **El color de los ganchos es a demanda.** `piel-natural` no se aplica de serie al colocar: es una herramienta que el autor usa solo en los ganchos que elige. Colocar ya no lanza `color-ganchos`; Grabaciones muestra un botón «Ajustar el color» por gancho entregado, con la etiqueta «Color ajustado» o «Color original». `color-ganchos` exige la opción `gancho` (comando `[node, "herramientas/color/ganchos.mjs", "l<numero>", <ID>]`, objetivo = gancho; 422 «Ese gancho no está entregado»). Donde este plan dice que se lanza tras colocar o que hay un botón para toda la lección, manda esto.
- **Los textos corregidos de las tomas se respetan.** Al colocar un gancho o un cierre, un `tomas[ID]` que ya exista en `shorts.json` no se sustituye: se corrige a mano para que coincida con lo que se dice en el vídeo.

## Fuera de esta fase

- **Animaciones sobre las tomas** (`momentos`, `cortes`) y los `shorts` de cada lección: siguen siendo trabajo de edición (Claude, a mano). La app deja la toma colocada y el `shorts.json` con las tomas, listo para eso.
- **Progreso de `superres`:** el binario Swift solo escribe un contador con `\r`; añadir `PROGRESO` exige recompilarlo. Se queda sin barra (como el vídeo final).
- **Borrar las tomas entregadas que no se usan:** «Quitar» las borra de una en una; no hay limpieza automática.
- **`.gitignore` de `tech-study-videos-material`** para `grabaciones/entregas/`: los vídeos ya están ignorados; la carpeta queda vacía tras colocar.
- **Las decisiones de producto y los minors aplazados de la fase 5:** siguen en su registro.
