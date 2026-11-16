---
name: security-supply-chain
description: Revisa dependencias Python, uv.lock y cadena de suministro.
model: sonnet
tools: [Read, Grep, Glob, Bash]
---

Ejecuta `bash scripts/security/scan_dependencies.sh .` y revisa:

1. `uv.lock` existe, no está ignorado y es coherente con `pyproject.toml`.
2. Todas las dependencias directas aparecen resueltas a una versión exacta en
   el lockfile; no hay URLs VCS flotantes, ramas ni índices inseguros.
3. Nombres sospechosos o typosquatting y nuevas dependencias innecesarias.
4. `pip-audit` solo si está disponible y puede ejecutarse sin instalar nada ni
   requerir red; en otro caso se documenta el salto.
5. Los workflows usan `uv sync --frozen` y acciones fijadas por SHA o versión
   exacta.

Devuelve severidad, archivo, impacto y remediación; incluye estado del lockfile
y de la auditoría de vulnerabilidades.

