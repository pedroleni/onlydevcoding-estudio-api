#!/usr/bin/env bash
# Puerta automática de clean code (docs/clean-code.md). La ejecutan la CI de GitHub,
# Jenkins y cualquiera antes de abrir una PR: uv run --frozen bash scripts/clean_code.sh
set -uo pipefail
cd "$(dirname "$0")/.."

fallos=0
paso() {
    echo "== $1"
    shift
    if ! "$@"; then
        echo "   ✗ falla: $*"
        fallos=$((fallos + 1))
    fi
}

# Estilo, complejidad, tamaño, simplificaciones y argumentos sin usar.
paso "ruff (normas y complejidad)" ruff check .
paso "ruff (formato)" ruff format --check .
# Bloques repetidos de 6 líneas o más en el código de la API.
paso "duplicados" pylint estudio_api --disable=all --enable=duplicate-code \
    --min-similarity-lines=6 --ignore-imports=y --ignore-signatures=y --score=n
# Código muerto con confianza alta (cls es el primer argumento de los validadores).
paso "código muerto" vulture estudio_api --min-confidence 80 --ignore-names cls

if [ "$fallos" -ne 0 ]; then
    echo "Clean code: $fallos comprobaciones fallan. Mira docs/clean-code.md."
    exit 1
fi
echo "Clean code: todo en orden."
