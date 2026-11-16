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
  cabecera o no coincide, 401. Debe haber un único `Content-Length` decimal:
  sin él o si es inválido se devuelve 411, y por encima de 256 KB, 413. CORS
  continúa permitiendo solo `GET`.
- Las únicas escrituras permitidas bajo `CURSOS_DIR` son
  `publicar/publicacion.json`, `publicar/PUBLICAR-leccion-N.md` y
  `publicar/PUBLICAR-leccion-N.html` dentro de una lección. Se escriben en un
  temporal de la misma carpeta, se sustituyen con `os.replace` y conservan una
  única copia `<archivo>.antes-de-editar`. No se escribe en `ESTUDIO_DIR`.
- Los tests usan datos ficticios bajo `tmp_path`; no deben incorporar rutas ni
  contenido reales.

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
