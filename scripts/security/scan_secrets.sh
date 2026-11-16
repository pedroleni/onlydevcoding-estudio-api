#!/usr/bin/env bash
# Busca secretos y datos privados en código, tests, scripts y configuración.
set -euo pipefail

PROJECT_ROOT="${1:-.}"
FINDINGS=0

SCAN_DIRS=(
    estudio_api tests scripts .github .githooks docs .claude
)
SCAN_FILES=(
    pyproject.toml .env.example README.md AGENTS.md CLAUDE.md
)

finding() {
    local severity="$1" detail="$2"
    printf '[%s] %s\n' "$severity" "$detail"
    case "$severity" in CRITICAL|HIGH) FINDINGS=$((FINDINGS + 1));; esac
}

scan_regex() {
    local severity="$1" label="$2" pattern="$3"
    local matches
    local targets=()
    local target
    for target in "${SCAN_DIRS[@]}" "${SCAN_FILES[@]}"; do
        [ -e "$PROJECT_ROOT/$target" ] && targets+=("$PROJECT_ROOT/$target")
    done
    matches=$(grep -RInE "$pattern" "${targets[@]}" \
        --include='*.py' --include='*.sh' --include='*.toml' --include='*.yml' \
        --include='*.yaml' --include='*.json' --include='*.env' --include='*.md' \
        --include='.env.example' \
        --exclude='scan_*.sh' 2>/dev/null || true)
    if [ -n "$matches" ]; then
        while IFS= read -r match; do
            finding "$severity" "$label en ${match%%:*} (valor omitido)"
        done <<< "$matches"
    fi
}

echo "=== Escáner de secretos y datos privados ==="
for required_dir in "${SCAN_DIRS[@]}"; do
    if [ ! -d "$PROJECT_ROOT/$required_dir" ]; then
        finding HIGH "Falta la raíz de escaneo requerida: $required_dir/"
    fi
done
for required_file in "${SCAN_FILES[@]}"; do
    if [ ! -f "$PROJECT_ROOT/$required_file" ]; then
        finding HIGH "Falta el archivo de escaneo requerido: $required_file"
    fi
done
scan_regex CRITICAL "Clave privada" '-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----'
scan_regex CRITICAL "Clave de proveedor" '(AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}|sk-ant-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{48,}|gh[pousr]_[A-Za-z0-9_]{36,}'
scan_regex CRITICAL "URL con credenciales" '(postgres(ql)?|mysql|redis|mongodb(\+srv)?)://[^[:space:]:]+:[^[:space:]@]+@'
scan_regex HIGH "Ruta privada de equipo" '(/[U]sers/|/home/[^/[:space:]]+/|[A-Za-z]:\\[U]sers\\)'
scan_regex HIGH "Email privado" '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'

IN_GIT_REPO=false
if git -C "$PROJECT_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    IN_GIT_REPO=true
fi

while IFS= read -r envfile; do
    [ -z "$envfile" ] && continue
    if [ "$IN_GIT_REPO" = true ]; then
        relative_envfile="${envfile#"$PROJECT_ROOT"/}"
        if ! git -C "$PROJECT_ROOT" ls-files --error-unmatch -- "$relative_envfile" \
                >/dev/null 2>&1 \
            && ! git -C "$PROJECT_ROOT" diff --cached --name-only -- \
                "$relative_envfile" | grep -Fxq -- "$relative_envfile"; then
            continue
        fi
    fi
    finding HIGH "Archivo de entorno real presente: $envfile"
done < <(find "$PROJECT_ROOT" -maxdepth 2 -type f -name '.env*' \
    ! -name '.env.example' \
    -not -path '*/.venv/*' -not -path '*/.git/*' 2>/dev/null)

if [ ! -f "$PROJECT_ROOT/.gitignore" ] || ! grep -Eq '^\.env([[:space:]]|$)' "$PROJECT_ROOT/.gitignore"; then
    finding HIGH ".env no está ignorado por .gitignore"
fi
if [ ! -f "$PROJECT_ROOT/.env.example" ]; then
    finding HIGH "Falta .env.example"
fi

if [ "$FINDINGS" -gt 0 ]; then
    echo "Bloqueo: $FINDINGS hallazgo(s) CRITICAL/HIGH."
    exit 1
fi
echo "OK: sin secretos ni datos privados CRITICAL/HIGH."
