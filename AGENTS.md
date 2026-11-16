# AGENTS.md — API local del estudio de OnlyDevCoding

Instrucciones para cualquier agente de código que trabaje en este repositorio.

## Proyecto

API local en FastAPI y Python 3.14, gestionada con `uv`. Lee las carpetas de
cursos y del estudio para servir datos a una web local. No tiene autenticación
por diseño y solo debe escuchar en `127.0.0.1:8000`.

## Documentación que hay que leer

Lee solo lo necesario para la tarea:

1. La especificación aplicable de `docs/specs/`.
2. El plan aplicable de `docs/plans/`.
3. Este archivo.

No inventes requisitos si la documentación no resuelve una decisión que afecte
al producto o a la seguridad: señala la duda.

## Comandos del proyecto

- Arranque: `uv run uvicorn --factory estudio_api.app:crear_app_desde_entorno --host 127.0.0.1 --port 8000`
- Tests: `uv run pytest -q`
- Tests sin red: `uv run --offline pytest -q`
- Lint: `uv run ruff check .`
- Scanners: `for s in scripts/security/scan_*.sh; do bash "$s"; done`

## Seguridad obligatoria

La auditoría cubre ocho dominios mediante `.claude/agents/security-*.md`. Si no
se pueden delegar, recórrelos de forma secuencial. Lee también
`security/security-review-instructions.md`, que contiene los precedentes del
proyecto.

Antes de cerrar cambios que afecten a:

- límites locales, `Host`, `Origin`, rutas, procesos o subidas:
  `.claude/agents/security-local-api.md`;
- variables de entorno o datos sensibles: `security-secrets.md`;
- entradas, rutas o contenido servido: `security-injection.md`;
- dependencias o `uv.lock`: `security-supply-chain.md`;
- código general: `security-code-vulns.md`;
- workflows o configuración: `security-infrastructure.md`.

Una auditoría completa recorre: `security-agent-env`, `security-secrets`,
`security-code-vulns`, `security-supply-chain`, `security-injection`,
`security-local-api`, `security-infrastructure` y
`security-prompt-injection`.

Reporta hallazgos CRITICAL, HIGH o MEDIUM con más del 80 % de confianza. El
risk score es `CRITICAL×25 + HIGH×10 + MEDIUM×3 + LOW×1`, con tope 100. Guarda
las auditorías completas en `security/reviews/YYYY-MM-DD-<tema>.md` siguiendo
su README; los chequeos puntuales no requieren un informe allí.

## Enforcement

- `bash scripts/security/install_hooks.sh` configura `.githooks/pre-commit`.
- El hook ejecuta `scan_secrets.sh` y bloquea CRITICAL/HIGH.
- `.github/workflows/security-scan.yml` ejecuta todos los scanners en cada PR y
  push a `main`.
- `.github/workflows/ci.yml` valida lockfile, lint y tests.

## Flujo de ramas

1. Parte de `main` actualizado y crea `feat/<nombre-corto>` o
   `fix/<nombre-corto>`.
2. Una rama contiene una tarea o un grupo pequeño y cohesionado.
3. Ejecuta scanners, `uv run ruff check .` y `uv run pytest -q`.
4. Haz commits normales en la rama, push y PR contra `main`.
5. Solo integra cuando CI esté verde y la revisión haya terminado. Nunca hagas
   push directo a `main`.

Si el entorno no permite escribir en `.git`, deja los cambios en el árbol de
trabajo e indica los pasos manuales pendientes.

## Restricciones globales

- Nada privado en el repositorio: no incluyas rutas absolutas de equipos,
  emails, tomas ni textos reales de lecciones. Los tests crean datos falsos en
  `tmp_path`; las rutas reales solo viven en `.env`, que está ignorado.
- No escribas en `CURSOS_DIR` ni `ESTUDIO_DIR`, salvo en una fase que lo
  autorice explícitamente. La fase 1 es solo lectura.
- Toda ruta abierta debe resolverse dentro de una raíz permitida. Rechaza `..`,
  rutas absolutas y enlaces simbólicos que salgan de ella.
- Los ids de curso cumplen `^[a-z0-9-]{1,40}$`; las lecciones son enteros de 1
  a 999.
- Solo se admiten `Host` `127.0.0.1:8000` y `localhost:8000`. Un `Origin` de
  navegador distinto de `ORIGEN_WEB` se rechaza con 403.
- Los procesos usan una lista cerrada de ejecutables y argumentos, nunca
  `shell=True` ni comandos construidos con entrada externa.
- Mantén las dependencias reproducibles mediante `uv.lock`.

