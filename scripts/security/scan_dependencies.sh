#!/usr/bin/env bash
# Comprueba reproducibilidad de dependencias Python sin usar la red.
set -euo pipefail

PROJECT_ROOT="${1:-.}"
FINDINGS=0

blocking() {
    printf '[HIGH] %s\n' "$1"
    FINDINGS=$((FINDINGS + 1))
}

echo "=== Escáner de dependencias Python ==="

[ -d "$PROJECT_ROOT" ] || blocking "Falta la raíz del proyecto: $PROJECT_ROOT"
[ -f "$PROJECT_ROOT/pyproject.toml" ] || blocking "Falta pyproject.toml."
[ -f "$PROJECT_ROOT/uv.lock" ] || blocking "Falta uv.lock."
[ -f "$PROJECT_ROOT/.gitignore" ] || blocking "Falta .gitignore."
if [ -f "$PROJECT_ROOT/.gitignore" ] && grep -Eq '(^|/)uv\.lock([[:space:]]|$)' "$PROJECT_ROOT/.gitignore"; then
    blocking "uv.lock está ignorado."
fi

if [ -f "$PROJECT_ROOT/pyproject.toml" ] && [ -f "$PROJECT_ROOT/uv.lock" ]; then
    PYTHON_COMMAND=(python3)
    if ! python3 -c 'import tomllib' >/dev/null 2>&1; then
        if [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
            PYTHON_COMMAND=("$PROJECT_ROOT/.venv/bin/python")
        else
            blocking "Se necesita Python 3.11 o posterior para validar los archivos TOML."
            PYTHON_COMMAND=()
        fi
    fi

    if [ "${#PYTHON_COMMAND[@]}" -gt 0 ] && ! "${PYTHON_COMMAND[@]}" - "$PROJECT_ROOT" <<'PY'
import re
import sys
import tomllib
from pathlib import Path

root = Path(sys.argv[1])
project = tomllib.loads((root / "pyproject.toml").read_text())
lock = tomllib.loads((root / "uv.lock").read_text())

requirements = list(project.get("project", {}).get("dependencies", []))
for group in project.get("dependency-groups", {}).values():
    requirements.extend(group)

def name_of(requirement: str) -> str:
    match = re.match(r"\s*([A-Za-z0-9_.-]+)", requirement)
    if not match:
        raise SystemExit(f"[HIGH] Requisito no interpretable: {requirement}")
    return match.group(1).lower().replace("_", "-").replace(".", "-")

locked = {}
for package in lock.get("package", []):
    name = str(package.get("name", "")).lower().replace("_", "-").replace(".", "-")
    if name:
        locked[name] = package

errors = []
for requirement in requirements:
    name = name_of(requirement)
    package = locked.get(name)
    if not package or not package.get("version"):
        errors.append(f"dependencia directa sin versión resuelta en uv.lock: {name}")
    if " @ git+" in requirement or re.search(r"git\+.*@(main|master|HEAD)(#|$)", requirement):
        errors.append(f"referencia VCS flotante: {requirement}")

for package in lock.get("package", []):
    source = package.get("source", {})
    git = source.get("git") if isinstance(source, dict) else None
    if git and not re.search(r"[?&]rev=[0-9a-f]{40}($|&)", str(git)):
        errors.append(f"fuente Git no fijada a commit: {package.get('name')}")

if errors:
    for error in errors:
        print(f"[HIGH] {error}")
    raise SystemExit(1)
print(f"OK: {len(requirements)} dependencias directas fijadas mediante uv.lock.")
PY
    then
        FINDINGS=$((FINDINGS + 1))
    fi

    if command -v uv >/dev/null 2>&1; then
        UV_SCAN_CACHE="$(mktemp -d "${TMPDIR:-/tmp}/estudio-api-security-uv.XXXXXX")"
        trap 'rm -rf "$UV_SCAN_CACHE"' EXIT
        if UV_CACHE_DIR="$UV_SCAN_CACHE" \
            uv --project "$PROJECT_ROOT" lock --check --offline >/dev/null 2>&1; then
            echo "OK: uv.lock es coherente con pyproject.toml en modo offline."
        else
            blocking "uv.lock no es coherente con pyproject.toml en modo offline."
        fi
    else
        echo "[INFO] No se encuentra uv; se omite uv lock --check."
    fi
fi

echo "[INFO] pip-audit omitido: la consulta de vulnerabilidades puede requerir red y este escaneo es offline."

if [ "$FINDINGS" -gt 0 ]; then
    echo "Bloqueo: $FINDINGS comprobación(es) fallida(s)."
    exit 1
fi
echo "OK: sin problemas CRITICAL/HIGH de cadena de suministro."
