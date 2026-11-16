#!/usr/bin/env bash
# Audita configuración de FastAPI/Uvicorn y GitHub Actions.
set -euo pipefail

PROJECT_ROOT="${1:-.}"
FINDINGS=0

finding() {
    local severity="$1" detail="$2"
    printf '[%s] %s\n' "$severity" "$detail"
    case "$severity" in CRITICAL|HIGH) FINDINGS=$((FINDINGS + 1));; esac
}

echo "=== Escáner de configuración ==="

for required_dir in estudio_api tests scripts .github/workflows; do
    if [ ! -d "$PROJECT_ROOT/$required_dir" ]; then
        finding HIGH "Falta la raíz de escaneo requerida: $required_dir/"
    fi
done

exposed=$(grep -RInE '(--host[[:space:]]+(0\.0\.0\.0|::)|host[[:space:]]*:[[:space:]]*(0\.0\.0\.0|::))' \
    "$PROJECT_ROOT/estudio_api" "$PROJECT_ROOT/tests" "$PROJECT_ROOT/scripts" \
    "$PROJECT_ROOT/.github" --include='*.py' --include='*.sh' --include='*.yml' \
    --exclude='scan_*.sh' 2>/dev/null || true)
[ -z "$exposed" ] || finding HIGH "Configuración de servidor expuesta fuera de loopback: $exposed"

wide_cors=$(grep -RInE "allow_origins[[:space:]]*=[[:space:]]*\\[['\"]\\*['\"]\\]|Access-Control-Allow-Origin.*\\*" \
    "$PROJECT_ROOT/estudio_api" "$PROJECT_ROOT/tests" --include='*.py' 2>/dev/null || true)
[ -z "$wide_cors" ] || finding HIGH "CORS permite cualquier origen: $wide_cors"

if [ -d "$PROJECT_ROOT/.github/workflows" ]; then
    while IFS= read -r workflow; do
        [ -z "$workflow" ] && continue
        if grep -q 'pull_request_target' "$workflow"; then
            finding CRITICAL "$workflow usa pull_request_target."
        fi
        if grep -Eq '^[[:space:]]*permissions:[[:space:]]*write-all([[:space:]]*(#.*)?)?$' "$workflow"; then
            finding HIGH "$workflow concede write-all."
        fi
        write_permissions=$(grep -En '^[[:space:]]*[A-Za-z0-9_-]+:[[:space:]]*write([[:space:]]*(#.*)?)?$' "$workflow" || true)
        [ -z "$write_permissions" ] || finding HIGH "$workflow concede permisos de escritura: $write_permissions"
        while IFS= read -r ref; do
            [ -z "$ref" ] && continue
            ref=$(printf '%s' "$ref" | sed -E 's/[[:space:]]*#.*$//')
            version=${ref##*@}
            if ! printf '%s' "$version" | grep -Eq '^[0-9a-f]{40}$'; then
                finding HIGH "$workflow usa una acción sin SHA de 40 caracteres: $ref"
            fi
        done < <(grep -E '^[[:space:]]*(-[[:space:]]+)?uses:[[:space:]]*' "$workflow" | sed -E 's/.*uses:[[:space:]]*//' || true)
    done < <(find "$PROJECT_ROOT/.github/workflows" -type f \( -name '*.yml' -o -name '*.yaml' \) -print)
fi

if [ "$FINDINGS" -gt 0 ]; then
    echo "Bloqueo: $FINDINGS hallazgo(s) CRITICAL/HIGH."
    exit 1
fi
echo "OK: sin configuraciones CRITICAL/HIGH."
