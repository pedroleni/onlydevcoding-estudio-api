#!/usr/bin/env bash
# Detecta patrones vulnerables en el código Python del proyecto.
set -euo pipefail

PROJECT_ROOT="${1:-.}"
FINDINGS=0

check() {
    local severity="$1" category="$2" pattern="$3"
    local matches
    matches=$(grep -RInE "$pattern" "$PROJECT_ROOT/estudio_api" "$PROJECT_ROOT/tests" \
        "$PROJECT_ROOT/scripts" --include='*.py' 2>/dev/null || true)
    if [ -n "$matches" ]; then
        while IFS= read -r line; do
            printf '[%s] %s: %s\n' "$severity" "$category" "$line"
            case "$severity" in CRITICAL|HIGH) FINDINGS=$((FINDINGS + 1));; esac
        done <<< "$matches"
    fi
}

echo "=== Escáner de patrones de código Python ==="
check CRITICAL "Inyección de comandos" 'shell[[:space:]]*=[[:space:]]*True|os\.(system|popen)[[:space:]]*\('
check HIGH "Ejecución dinámica" '(^|[^[:alnum:]_])(eval|exec)[[:space:]]*\('
check HIGH "Deserialización insegura" 'pickle\.loads?[[:space:]]*\(|yaml\.load[[:space:]]*\('
check CRITICAL "TLS sin verificar" 'verify[[:space:]]*=[[:space:]]*False'
check HIGH "Servidor expuesto" "(host[[:space:]]*=[[:space:]]*['\"](0\\.0\\.0\\.0|::)['\"]|--host[[:space:]]+(0\\.0\\.0\\.0|::))"
check HIGH "Posible traversal directo" '(open|Path)[[:space:]]*\([[:space:]]*(request|form|args)\.'
check MEDIUM "Traza interna en respuesta" 'traceback\.format_exc|HTTPException\([^)]*detail[[:space:]]*=[[:space:]]*(str\()?error'

if [ "$FINDINGS" -gt 0 ]; then
    echo "Bloqueo: $FINDINGS hallazgo(s) CRITICAL/HIGH."
    exit 1
fi
echo "OK: sin patrones CRITICAL/HIGH."
