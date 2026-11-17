# Instrucciones de revisión de seguridad — API local del estudio

Precedentes y decisiones de seguridad específicos del proyecto. Los agentes de
`.claude/agents/`, `/security-review` y cualquier revisión manual deben leer
este archivo antes de informar de un hallazgo.

## Rol y filtro

Revisa solo implicaciones de seguridad del diff o alcance indicado. Reporta
únicamente hallazgos con más del 80 % de confianza y prioriza fuga de archivos,
escrituras en las raíces, ejecución de procesos e exposición fuera del equipo.
No reportes DoS teórico, falta genérica de rate limiting o hardening sin una
ruta de explotación concreta.

## Decisiones aceptadas

- La API no tiene autenticación por diseño. No reportes su ausencia.
- Debe escuchar exclusivamente en `127.0.0.1`; enlazarla a `0.0.0.0` o `::` es
  un hallazgo HIGH.
- Los únicos hosts son `127.0.0.1:8000` y `localhost:8000`. Validar `Host`
  mitiga DNS rebinding. `Origin`, cuando exista, debe coincidir exactamente con
  `ORIGEN_WEB` (por defecto `http://127.0.0.1:3000`). La web también se abre en
  `127.0.0.1` para compartir sitio con la API. Toda petición HTTP marcada por el
  navegador con `Sec-Fetch-Site: cross-site` se rechaza; es lo que impide que
  otra web incruste los medios. `/api/medios` no envía
  `Cross-Origin-Resource-Policy: same-site` a propósito: Chromium bloquea con
  ella los medios entre `127.0.0.1:3000` y `127.0.0.1:8000`.
- CORS no sustituye las comprobaciones de `Host` y `Origin`.
- La fase 1 es de solo lectura en `CURSOS_DIR` y `ESTUDIO_DIR`.
- Toda petición distinta de `GET`, `HEAD` y `OPTIONS` exige
  `X-Estudio-Token`, comparado con `ESTUDIO_TOKEN` mediante
  `hmac.compare_digest`. Si falta la configuración se devuelve 503; si falta la
  cabecera o no coincide, 401. El token configurado debe tener 32 caracteres o
  más. Todo WebSocket exige también el token y se cierra con 1008 si falta o no
  coincide. Debe haber un único `Content-Length` decimal; `Transfer-Encoding`,
  una longitud ausente o inválida reciben 411. Se cuentan además los bytes que
  llegan por ASGI: superar 256 KB o la longitud declarada recibe 413. CORS
  continúa permitiendo solo `GET`.
- Hasta la fase 3, las únicas escrituras permitidas bajo `CURSOS_DIR` son
  `publicar/publicacion.json`, `publicar/PUBLICAR-leccion-N.md` y
  `publicar/PUBLICAR-leccion-N.html` dentro de una lección. Se escriben en un
  temporal de la misma carpeta, se sustituyen con `os.replace` y conservan una
  única copia `<archivo>.antes-de-editar`. La carpeta `publicar` y cada destino
  deben ser rutas literales, no enlaces simbólicos, aunque el enlace permanezca
  dentro de `CURSOS_DIR`. En la fase 3 no se escribe en `ESTUDIO_DIR`; la fase 4
  añade las escrituras de su sección.
- Los tests usan datos ficticios bajo `tmp_path`; no deben incorporar rutas ni
  contenido reales.
- En la fase 3, la única ejecución de procesos permitida es la llamada concreta
  a `herramientas/publicar/md-a-html.py` para regenerar una guía HTML. Usa
  `sys.executable -I` y la ruta fija del script dentro de `ESTUDIO_DIR`, una
  lista de argumentos, `shell=False`, un entorno limitado a `PATH`, `HOME` y
  `LANG`, salida estándar y error capturados, un grupo de procesos propio, un
  timeout de 60 segundos y `cwd` en la carpeta `publicar/` validada dentro de
  `CURSOS_DIR`. Si vence el timeout se mata el grupo completo con `os.killpg` y
  se intenta recoger el proceso durante un máximo adicional de 5 segundos. Las
  rutas de entrada, salida e imagen se validan dentro de esas raíces; la imagen
  se pasa como ruta absoluta y el HTML se genera en un temporal de `publicar/`
  y se instala de forma atómica.

## Precedentes de la fase 4 (teleprompter y grabación)

Amplían las decisiones anteriores; lo que no se cite aquí sigue igual.

- **Escrituras en `ESTUDIO_DIR`.** Solo dos:
  - `ESTUDIO_DIR/out/previas-grabacion/<guion>.mp4`, la vista previa de
    grabación. Remotion escribe `<guion>.generando.mp4` en esa misma carpeta y
    la API lo instala con `os.replace`; si el render falla, vence el tiempo o se
    apaga la API, el temporal se borra. `<guion>` es el nombre real del archivo
    de guion (`<curso>-NN` o `<curso>-NNN`), resuelto con `ruta_segura`.
  - `ESTUDIO_DIR/lecciones/<curso>-NN.json`, solo los textos (`cues[].texto` y
    `puntos`) con `PUT .../guion/textos`. Usa `escribir_atomico`, conserva una
    única copia `<archivo>.antes-de-editar` y comprueba el SHA-256 del archivo
    antes y justo antes de escribir.
- **Enlaces simbólicos del guion.** La escritura del guion sigue un enlace
  simbólico interno a `ESTUDIO_DIR`: la ruta se resuelve con `ruta_segura` y se
  comprueba que queda dentro de la raíz, así que se escribe en el destino real
  del enlace. Es una decisión aceptada. Un guion enlazado fuera de
  `ESTUDIO_DIR` no cuenta como guion (404).
- **Escrituras en `CURSOS_DIR` para las tomas de voz.** `PUT
  .../grabaciones/E<NN>` escribe `<lección>/grabaciones/E<NN>.wav` y archiva la
  toma anterior en `grabaciones/tomas/`. La carpeta de la lección es la misma
  para la subida, el teleprompter y la ficha: la de disco si existe y, si no, la
  que declara el guion validada dentro de `CURSOS_DIR`. La carpeta de la lección
  se resuelve dentro de `CURSOS_DIR`; `grabaciones`, `tomas` y el destino deben
  ser rutas literales, sin enlaces simbólicos.
- **Límite de cuerpo de 200 MiB solo en la ruta de tomas.** Se aplica únicamente
  a `PUT /api/cursos/{curso}/lecciones/{numero}/grabaciones/E<NN>` con la forma
  literal de la ruta (número sin ceros a la izquierda y sin barra final). El
  resto de rutas, métodos y variantes mantiene el límite de 256 KB.
- **Proceso de Remotion.** Es el segundo proceso permitido, junto a
  `md-a-html.py`:
  - lista fija `[<npx>, "--no", "remotion", "render", "src/index.ts",
    "Leccion", <temporal>, '--props={"leccion":"<guion>"}', "--scale=0.5",
    "--muted", "--crf=30"]`, con `<npx>` de `shutil.which`, `shell=False` y
    `cwd` en `ESTUDIO_DIR`. `--no` impide que npx descargue `remotion` fuera
    del lockfile del estudio;
  - entorno mínimo: solo `PATH`, `HOME`, `TMPDIR`, `LANG`, `USER` y
    `NODE_ENV`, los que existan. `ESTUDIO_TOKEN` y el resto no llegan al render;
  - `stdin=DEVNULL`, `start_new_session=True` (grupo de procesos propio) y un
    solo render a la vez;
  - tiempo máximo de 2 horas: al vencer, `os.killpg` con SIGTERM, 10 segundos
    de gracia y SIGKILL; el trabajo queda en `error` y se borra el temporal;
  - al apagar la API, el `lifespan` mata igual el grupo de cada render en
    marcha, lo marca `interrumpido` y borra su temporal. Un SIGKILL a la API no
    pasa por ahí; al arrancar, `interrumpir_huerfanos` marca esas filas y borra
    sus temporales (aceptado: no se guarda el grupo en la base).
- **Errores de los trabajos.** `Trabajo.error` solo guarda mensajes fijos en
  castellano, sin rutas. El detalle técnico va únicamente al log del servidor.
  La salida de Remotion (`registro`) se guarda en la base, pero la API no la
  devuelve.

## Hallazgos prioritarios

- Cualquier ruta derivada de una petición que pueda escapar de las raíces tras
  `Path.resolve()`, incluidos `..`, rutas absolutas y enlaces simbólicos: HIGH.
- Cualquier `subprocess` con `shell=True`, `os.system` u `os.popen`: HIGH o
  CRITICAL según el origen de los argumentos.
- Un proceso permitido debe seleccionarse de una lista cerrada y recibir una
  lista de argumentos; ninguna entrada externa forma una línea de shell.
- Una subida debe limitar nombre, extensión, tamaño y destino, resolver la ruta
  final dentro de una raíz dedicada y no sobrescribir por defecto. Si no hay
  endpoints de subida, esta superficie es N/A.
- Errores HTTP no deben revelar rutas locales ni contenido de archivos.
- Archivos de configuración, `.env`, JSON internos y extensiones no permitidas
  nunca se sirven como medios.

## Formato de hallazgos

```text
# Vuln N: <categoría>: `archivo:línea`
- Severity: Critical | High | Medium | Low
- Description: ...
- Exploit Scenario: ...
- Recommendation: ...
```

Solo se publican CRITICAL, HIGH y MEDIUM. Una auditoría completa añade resumen,
prioridad de remediación y risk score:
`CRITICAL×25 + HIGH×10 + MEDIUM×3 + LOW×1` (máximo 100).
