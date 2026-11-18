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

## Precedentes de la fase 5 (acciones del estudio)

Amplían las decisiones anteriores; lo que no se cite aquí sigue igual.

- **Catálogo cerrado.** Las únicas acciones son `alinear-voz`,
  `preparar-montaje`, `previa-grabacion`, `render-leccion`, `video-final`,
  `preparar-shorts` y `render-short`. Cada una tiene un comando fijo, con
  `shell=False` y `cwd` en `ESTUDIO_DIR`:
  - `node herramientas/{alinear-voz,preparar-leccion}.mjs <guion>`;
  - `node herramientas/preparar-shorts.mjs l<N>`;
  - `npx --no remotion render src/index.ts {Leccion|Short} <temporal>
    --props=...` (la previa de grabación conserva el comando de la fase 4);
  - `/bin/zsh -f herramientas/publicar/sonido-redes.sh <previa> <temporal>`;
    `-f` evita que zsh lea `~/.zshenv` u otra configuración del usuario.

  `node` y `npx` salen de `shutil.which`. Del cliente solo llegan el id de la
  acción (`Literal`), `previa` (tiene que ser una versión existente de
  `previa/`) y `short` (`^[a-z0-9-]{1,60}$` y presente en el `shorts.json` del
  guion). Cualquier otro valor da 422 sin lanzar nada.
- **Entorno de las herramientas.** El mínimo de la fase 4 más `CURSOS_DIR`,
  tomado de la configuración, en las acciones que leen o escriben la lección.
  Nunca `ESTUDIO_TOKEN`. Las herramientas viven en `ESTUDIO_DIR`, son del autor
  y su alcance de escritura (alineaciones, `montaje.json`, `public/shorts/…`)
  queda fuera de la API: la API solo garantiza el temporal y la instalación del
  resultado final.
- **Escrituras en `CURSOS_DIR` de la fase 5.** Los destinos son:
  - `previa/previa-vN.mp4`, que no pisa nada (`os.link(...,
    follow_symlinks=False)`);
  - `shorts/<id>.mp4` y
    `publicar/1-youtube-leccion/curso-<curso>-NN-<slug>.mp4`, que archivan el
    anterior en `anteriores/<nombre>-<marca>.mp4`.

  `previa/`, `shorts/`, `publicar/` y `publicar/1-youtube-leccion/`, y el
  propio destino, son rutas literales: un enlace simbólico en cualquier
  componente, aunque apunte dentro de `CURSOS_DIR`, da 503 «No se puede
  preparar la carpeta del resultado». Las carpetas que faltan se crean nivel a
  nivel y tienen que acabar siendo directorios reales.
- **Temporal y `anteriores/`.** El temporal es `.<nombre>.generando.mp4` en la
  carpeta del destino. Antes de lanzar, lo que haya en esa ruta (archivo o
  enlace) se borra con `unlink`, que no sigue enlaces; no se crea con
  `O_EXCL` para no depender de que Remotion acepte un archivo ya existente. Al
  instalar, el temporal tiene que ser un archivo regular (`lstat`), el destino
  no puede ser un enlace ni algo distinto de un archivo y `anteriores/` tiene
  que ser un directorio real (se crea si falta). Cualquier violación deja el
  trabajo en `error` con el mensaje de guardado, sin mover ni pisar nada. El
  temporal se borra si el trabajo falla, se cancela, vence el tiempo o se
  apaga la API.
- **Motor de trabajos.** Un trabajo a la vez para toda la API. La carpeta del
  resultado se prepara y el temporal se borra dentro de `lanzar`, con el
  trabajo ya reservado: un 409 «Ya hay un trabajo en marcha» no crea carpetas
  ni borra el temporal de otro trabajo. Tiempo máximo por acción: alinear 1 h,
  preparar el montaje y los shorts 30 min, previa 2 h, render de la lección
  4 h, vídeo final 30 min, short 1 h. Cancelar solo afecta a trabajos lanzados
  por este proceso: SIGTERM al grupo, 10 s y SIGKILL, sin borrar el temporal
  hasta que el grupo muere (aceptado: la reutilización del pid del líder en
  ese intervalo no es explotable). `GET /api/trabajos` acepta `limite` de 1 a
  100.
- **Lección ocupada.** Mientras corre `alinear-voz`, `preparar-montaje` o
  `preparar-shorts` de una lección, `PUT .../guion/textos` y `PUT
  .../grabaciones/E<NN>` de esa lección responden 409 sin escribir; la subida
  lo comprueba antes de leer el cuerpo.
- **Tests y `datos/`.** Ningún test puede abrir la base real. Una fixture
  `autouse` sustituye `sqlite3.connect` por un envoltorio que falla antes de
  abrir cualquier ruta bajo `datos/`, y una guarda de sesión comprueba además
  que `datos/` no cambia.

## Precedentes de la fase 6 (entregas de tomas)

Amplían las decisiones anteriores; lo que no se cite aquí sigue igual.

- **Límite de 4 GiB solo en la ruta de entregas.** `PUT
  /api/cursos/{curso}/lecciones/{numero}/entregas/<un segmento>` admite hasta
  `4_294_967_296` bytes y un `Content-Length` de hasta 10 dígitos; si se
  supera, 413 «La toma supera el límite de 4 GiB». El patrón exige la forma
  literal de la ruta (número sin ceros a la izquierda) y un único segmento:
  un nombre con `/` (también `%2F`) cae en el límite general de 256 KB. El
  resto de rutas y métodos mantiene sus límites. No hay tope de subidas
  simultáneas ni comprobación de espacio libre: se acepta (exige el token).
- **Subida a `grabaciones/entregas/`.**
  - El nombre cumple
    `^[A-Za-z0-9_(][A-Za-z0-9 _().-]{0,115}\.(?i:mov|mp4)$`: solo ASCII, sin
    barra, sin punto ni guion inicial. Con otro nombre se responde 422 sin
    leer el cuerpo.
  - `Content-Type` tiene que ser `video/quicktime` o `video/mp4` (si no,
    415), y los bytes 4–8 tienen que ser `ftyp` (si no, 422).
  - La carpeta de la lección se resuelve dentro de `CURSOS_DIR`, como en la
    fase 4. `grabaciones/`, `entregas/`, `videos/` y `.analisis/` tienen que
    ser directorios literales.
  - El temporal es `.<archivo>.subiendo`. Se crea con
    `O_CREAT|O_EXCL|O_NOFOLLOW`, permisos `0600` y `dir_fd` sobre `entregas/`
    abierta con `O_NOFOLLOW`. Se instala con `os.link(...,
    follow_symlinks=False)` y nunca pisa nada: si el nombre ya existe en
    `entregas/` o en `grabaciones/videos/`, 409. Si la subida falla o se
    corta, el temporal se borra.
  - Un temporal regular que quede de una subida anterior se borra al volver
    a subir ese mismo nombre (un enlace da 503). Un SIGKILL deja el temporal
    oculto en disco; se acepta.
  - `DELETE` solo borra la entrega regular con el nombre exacto, sus
    `.analisis/<archivo>.{json,wav,origen}` regulares (nombres exactos, no
    por prefijo) y su entrada de `propuesta.json`, que se borra si queda
    vacía. `propuesta.json` se abre con `O_NOFOLLOW`: un enlace da 503.
- **`propuesta.json` es un dato no confiable.** La escribe
  `identificar-tomas`, pero la API la trata como entrada externa:
  - se abre con `O_NOFOLLOW|O_NONBLOCK` y tiene que ser un archivo regular de
    tamaño no mayor que `MAX_TAMANO_JSON`;
  - `version` tiene que ser `1` y `guion` el del archivo de guion real; la API
    usa siempre el nombre del archivo de guion, nunca el que trae el JSON;
  - cada entrada pasa por Pydantic estricto: nombre con el patrón de subida y
    presente en `entregas/` con el mismo tamaño que `bytes`, números finitos
    dentro de `[0, duracion + 0.005]` (redondeo de la herramienta; al
    escribir en el guion se limitan a `duracion`), destinos que existen en
    el guion y tantos `cues` como el guion. Las entradas que no cumplen se
    descartan.

  Ningún valor del archivo forma una ruta salvo `archivo`, ya validado. Una
  propuesta tiene que referirse al mismo archivo que se analizó (`bytes`
  igual al tamaño actual) y el texto de un cierre pasa por
  `validar_texto_toma` (una línea, sin controles ni bidireccionales, hasta
  2000 caracteres) antes de llegar a `shorts.json`; si no cumple, 422 sin
  tocar nada. Resueltos L1 y L2 de `security/reviews/2026-11-18-fase-6.md`.
- **Escrituras de colocar.**
  - En `CURSOS_DIR`: mueve `entregas/<archivo>` a
    `grabaciones/videos/<archivo>` sin pisar (409), borra
    `.analisis/<archivo>.{json,wav,origen}` y reescribe o borra
    `entregas/propuesta.json`.
  - En `ESTUDIO_DIR`:
    - `public/grabaciones/<guion>/E<NN>.mov` y
      `lecciones/tomas/<guion>/E<NN>-camara.json`;
    - `public/shorts/l<N>/tomas/{original/,}<id>.mov`;
    - `shorts/l<N>/tomas/<id>.{json,wav}`;
    - `shorts/l<N>/shorts.json` (`tomas` y `ganchosEntregados`, que se crea
      vacío si falta; un cierre no pisa un `tomas[<id>]` que ya exista);
    - `escenas[].toma` del guion: `original`, `video`, `desde`, `hasta` y
      `cues`.
  - `<id>` son 8 caracteres hexadecimales en mayúsculas, tomados del nombre
    `Facetune` o del SHA-256 del nombre.
  - Todas las rutas son literales: un enlace en cualquier componente da 503
    con mensaje fijo y no se toca nada. Los temporales
    `.<nombre>.colocando<ext>` se crean con `O_EXCL|O_NOFOLLOW`, después de
    borrar con `unlink` lo que hubiera.
  - Lo que se sustituye se archiva en `anteriores/` (`instalar_archivando`).
  - El guion y `shorts.json` se escriben con `escribir_json_versionado`: doble
    comprobación de SHA-256 y una sola copia `.antes-de-editar`.
  - Si algo falla antes de terminar, se deshace todo en orden inverso. Un
    cambio hecho desde fuera de la API no se pisa al deshacer.
- **Acciones de la fase 6.** El catálogo cerrado suma tres acciones:
  - `identificar-tomas`: `node herramientas/identificar-tomas.mjs <guion>`,
    con `CURSOS_DIR`, tiempo máximo de 1 h. Escribe `.analisis/` y
    `propuesta.json` en `entregas/` (alcance de la herramienta);
  - `color-ganchos`: `node herramientas/color/ganchos.mjs l<N>`, sin
    `CURSOS_DIR`, 1 h;
  - `mejorar-toma`: `/bin/zsh -f herramientas/superres/superres.sh
    <original> <temporal>`, 3 h. Del cliente solo llega `escena`
    (`^E[0-9]{2}$`, una escena de cámara del guion). `<original>` es la ruta
    absoluta de `toma.original` del guion, que tiene que ser
    `grabaciones/videos/[<subcarpeta>/]<nombre>` literal dentro de la carpeta
    de la lección: subcarpeta opcional de un nivel `[a-z0-9-]+`, nombre con
    `PATRON_ARCHIVO_ENTREGA` (`.mov`/`.mp4`), sin enlaces en ningún
    componente y archivo regular. Si no, 409 «Esa escena aún no tiene toma».
    - El resultado se instala archivando en
      `ESTUDIO_DIR/public/grabaciones/<guion>/E<NN>.mov`.
    - Después se guarda una copia durable en
      `<lección>/grabaciones/videos/ia/E<NN>.mov`, archivando la anterior.
      Primero se copia a `.E<NN>.copiando.mov` con `O_EXCL|O_NOFOLLOW`; ese
      temporal se borra antes de cada lanzamiento.
    - Las carpetas de los dos destinos son literales y se crean nivel a
      nivel dentro de `lanzar`.
- **Ocupación y cerrojos.**
  - Colocar es síncrona y ocupa el hueco global de los trabajos
    (`ocupar_sin_trabajo`, dentro del mismo `_BLOQUEO` que `lanzar`). Mientras
    dura, `lanzar` responde 409, y colocar responde 409 si hay un trabajo vivo
    o una fila `en_marcha` en la base.
  - Colocar y `PUT …/guion/textos` comparten un `RLock` del guion
    (`cerrojo_escritura_guion`). El orden de los cerrojos es siempre guion →
    trabajos.
  - `identificar-tomas` ocupa la lección para `PUT …/guion/textos` y para
    `PUT` y `DELETE` de `…/entregas/<archivo>` (409 «lección ocupada» antes
    de leer el cuerpo; resuelto L1). No ocupa `PUT …/grabaciones/E<NN>`: la
    herramienta no lee las tomas de voz.
- **Enlaces duros.** `O_NOFOLLOW` y `S_ISREG` no detectan un enlace duro
  plantado en `entregas/` o `.analisis/`. Se acepta: plantarlo exige escribir
  en `CURSOS_DIR` y poder leer ya el archivo de destino.

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
