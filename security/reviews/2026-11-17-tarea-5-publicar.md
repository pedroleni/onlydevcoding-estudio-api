# Auditoría de seguridad — Tarea 5 de fase 2

- **Fecha:** 2026-11-17
- **Alcance:** edición de textos de publicación, escritura de
  `publicacion.json`, regeneración de las guías Markdown y HTML, selección
  compartida de portadas y ejecución acotada de `md-a-html.py`.
- **Procedimiento:** revisión secuencial de los ocho dominios de
  `.claude/agents/security-*.md`, precedentes de
  `security/security-review-instructions.md`, scanners y tests de contrato.

## Resumen ejecutivo

No se han encontrado hallazgos CRITICAL, HIGH ni MEDIUM con más del 80 % de
confianza. El nuevo PUT conserva las validaciones cerradas de curso, lección,
pieza y red; exige el token y el límite de cuerpo mediante el middleware ya
existente; y solo escribe los tres nombres de archivo permitidos dentro de la
carpeta `publicar/` de una lección validada.

La conversión a HTML es la única ejecución de proceso añadida. Invoca el
intérprete actual y el script de ruta fija dentro de `ESTUDIO_DIR` mediante una
lista de argumentos, `shell=False`, timeout de 60 segundos y un directorio de
trabajo validado. La entrada Markdown, la salida temporal y la portada quedan
acotadas a las raíces permitidas. El HTML se instala con backup único y
`os.replace`; un fallo elimina el temporal y conserva el Markdown.

Los nombres de medios recibidos por el PUT se aceptan solo si resuelven a un
archivo servido dentro de `publicar/`. La guía no emite rutas absolutas ni
recorridos, y la portada incluida procede de la misma lista de candidatas
válidas usada por la vista y por la miniatura del estado.

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
| `scan_code_patterns.sh` | OK; la llamada concreta a `subprocess.run` no se marca y no hay `shell=True` |
| `scan_configs.sh` | OK |
| `scan_dependencies.sh` | OK; lock coherente offline, `pip-audit` omitido porque podría requerir red |
| `scan_prompt_injection.sh` | OK |
| `scan_secrets.sh` | OK; sin secretos, rutas privadas ni datos reales |
| Tests de scanners | OK |
| Suite, lint y formato | OK; detalle exacto en el informe de la tarea |

## Dominios

| Dominio | Resultado |
|---|---|
| security-agent-env | Sin cambios de permisos, hooks, MCP ni instrucciones de agentes |
| security-secrets | Solo datos ficticios en tests; sin secretos, emails ni rutas privadas |
| security-code-vulns | Entrada Pydantic, límites por red y errores fijos; sin deserialización ni ejecución dinámica insegura |
| security-supply-chain | Sin dependencias ni cambios en `uv.lock` |
| security-injection | Rutas canónicas, ids cerrados, proceso con argumentos en lista y sin shell |
| security-local-api | PUT protegido; escritura y proceso limitados a las raíces y archivos permitidos |
| security-infrastructure | Sin cambios de bind, CORS, workflows o configuración de despliegue |
| security-prompt-injection | Sin contenido oculto, instrucciones dinámicas ni payloads codificados |

## Hallazgos y prioridad de remediación

No hay hallazgos que remediar en este alcance.

## Estado

**CERRADA — sin hallazgos CRITICAL, HIGH o MEDIUM.**
