---
allowed-tools: Bash(git diff:*), Bash(git status:*), Bash(git log:*), Bash, Read, Glob, Grep, LS, Task
description: Auditoría de seguridad completa de la API local mediante ocho dominios
---

# Auditoría de seguridad completa

Audita el diff pendiente o, si no existe, el código actual. $ARGUMENTS

## 1. Contexto y descubrimiento

Obtén `git status`, `git diff HEAD` y cuenta archivos Python, shell, TOML y YAML.
Comprueba `pyproject.toml`, `uv.lock`, `.env.example`, `AGENTS.md`, `CLAUDE.md`
y `.github/workflows/`.

## 2. Dominios

Ejecuta en paralelo, si el entorno lo permite, o secuencialmente:

1. `security-agent-env`
2. `security-secrets`
3. `security-code-vulns`
4. `security-supply-chain`
5. `security-injection`
6. `security-local-api`
7. `security-infrastructure`
8. `security-prompt-injection`

Cada agente debe leer `security/security-review-instructions.md` y ejecutar el
scanner aplicable. Si el argumento limita el alcance, usa solo los dominios
relevantes.

## 3. Síntesis

Deduplica por archivo, línea y categoría; ordena CRITICAL, HIGH, MEDIUM, LOW e
INFO. Calcula `CRITICAL×25 + HIGH×10 + MEDIUM×3 + LOW×1`, máximo 100.

El informe contiene resumen ejecutivo, nivel global, score, conteo, top 3,
hallazgos con archivo/línea/descripción/escenario/recomendación y prioridades
P0 (CRITICAL), P1 (HIGH), P2 (MEDIUM).

## 4. Persistencia

Guarda el informe en `security/reviews/YYYY-MM-DD-<tema>.md`, añade su fila al
índice y termina con **Estado**, usando `- [ ] pendiente` por hallazgo. No dejes
la auditoría completa solo en el chat.

