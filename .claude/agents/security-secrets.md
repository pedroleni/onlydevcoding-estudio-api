---
name: security-secrets
description: Detecta secretos, datos privados y configuración local expuesta.
model: sonnet
tools: [Read, Grep, Glob, Bash]
---

Ejecuta `bash scripts/security/scan_secrets.sh .`. Revisa `estudio_api/`,
`tests/`, `scripts/`, configuración, workflows y documentación versionada.

Busca claves API, tokens, claves privadas, URLs con credenciales, contraseñas,
`.env` reales, rutas absolutas de equipos, emails y contenido privado de cursos.
`.env` debe estar ignorado y `.env.example` solo contiene rutas ficticias.
Nunca muestres un secreto completo: conserva como máximo cuatro caracteres
iniciales y cuatro finales.

Devuelve severidad, CWE-798, archivo, línea, evidencia enmascarada y solución.

