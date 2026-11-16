# Auditoría de seguridad — Tarea 4 de fase 2

- **Fecha:** 2026-11-17
- **Alcance:** cambios del árbol de trabajo para la vista de publicación, elección
  de portada, estado por red y cálculo del estado publicado de una lección.
- **Procedimiento:** revisión secuencial de los ocho dominios de
  `.claude/agents/security-*.md`, aplicando los precedentes de
  `security/security-review-instructions.md`, más los scanners y sus tests de
  contrato.

## Resumen ejecutivo

No se han encontrado hallazgos CRITICAL, HIGH ni MEDIUM con más del 80 % de
confianza. Los nuevos parámetros HTTP se validan mediante patrones cerrados
antes de ejecutar el controlador. Las portadas solo se guardan si coinciden de
forma exacta con una candidata obtenida de rutas resueltas dentro de la raíz.
Las cuatro redes usan una lista cerrada y las consultas SQLite siguen
parametrizadas.

Cada controlador que consulta o cambia decisiones abre una conexión local con
`abrir_bd(config.bd_ruta)` y la cierra mediante `contextlib.closing`; no hay
conexión global. Los PUT quedan detrás del middleware de token, límite de cuerpo,
Host, Origin y `Sec-Fetch-Site` ya existente. El cambio no añade procesos,
subidas, SSRF, dependencias ni escrituras en `CURSOS_DIR` o `ESTUDIO_DIR`.

También se endureció la lectura de `publicacion.json`: los destinos reales que
atraviesan un enlace hacia carpetas ocultas o `node_modules` se descartan, las
cadenas que no pueden codificarse como UTF-8 invalidan el archivo y los ids de
pieza solo aceptan dígitos ASCII.

## Nivel global y puntuación

| Métrica | Valor |
|---|---|
| Nivel global | **Sin hallazgos** |
| Risk score | **0 / 100** (`0×25 + 0×10 + 0×3 + 0×1`) |

| Severidad | Nº |
|---|---|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM | 0 |
| LOW | 0 |

## Resultados de comprobaciones

| Comprobación | Resultado |
|---|---|
| `scan_code_patterns.sh` | OK, sin patrones CRITICAL/HIGH |
| `scan_configs.sh` y su test | OK |
| `scan_dependencies.sh` | OK: lock coherente offline; `pip-audit` omitido por posible acceso de red |
| `scan_prompt_injection.sh` | OK |
| `scan_secrets.sh` | OK, sin secretos ni datos privados CRITICAL/HIGH |
| `test_scanners_cobertura.sh` | OK |
| Suite, lint y formato | OK; detalle exacto en el informe de la tarea |

## Dominios

| Dominio | Resultado |
|---|---|
| security-agent-env | Sin cambios de instrucciones, permisos, hooks o MCP |
| security-secrets | Sin secretos, rutas locales, emails ni textos reales añadidos |
| security-code-vulns | Entradas tipadas, errores fijos y consultas parametrizadas; sin hallazgos |
| security-supply-chain | Sin cambios de dependencias ni lockfile |
| security-injection | Rutas canónicas y selección exacta de candidatas; sin comandos ni SSRF |
| security-local-api | PUT protegido; Host/Origin/sitio y tamaño siguen centralizados en middleware |
| security-infrastructure | Sin cambios de bind, workflows o configuración de despliegue |
| security-prompt-injection | Sin contenido oculto ni instrucciones dinámicas nuevas |

## Hallazgos y prioridad de remediación

No hay hallazgos que remediar en este alcance.

## Estado

**CERRADA — sin hallazgos CRITICAL, HIGH o MEDIUM.**
