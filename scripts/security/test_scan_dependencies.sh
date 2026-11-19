#!/usr/bin/env bash
# Contrato: el escáner de dependencias pasa con el pyproject.toml y el uv.lock reales y
# bloquea cuando falta el lock, está ignorado, deja una dependencia sin resolver o
# apunta a una fuente Git sin fijar a un commit.
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
SCANNER="$PROJECT_ROOT/scripts/security/scan_dependencies.sh"
TEMP_ROOT=$(mktemp -d)
trap 'rm -rf "$TEMP_ROOT"' EXIT
FALLOS=0

# Copia del pyproject.toml, el uv.lock y el .gitignore reales: coherentes entre sí.
crear_proyecto() {
    local proyecto="$TEMP_ROOT/$1"
    mkdir -p "$proyecto"
    cp "$PROJECT_ROOT/pyproject.toml" "$PROJECT_ROOT/uv.lock" "$PROJECT_ROOT/.gitignore" "$proyecto/"
    # Si el python3 del sistema es anterior a 3.11, el escáner usa el del .venv del proyecto.
    if [ -d "$PROJECT_ROOT/.venv" ]; then
        ln -s "$PROJECT_ROOT/.venv" "$proyecto/.venv"
    fi
    printf '%s\n' "$proyecto"
}

# esperado: 0 = pasa, 1 = bloquea; patron: texto que debe aparecer en la salida.
espera() {
    local esperado="$1" descripcion="$2" proyecto="$3" patron="${4:-}"
    local salida obtenido=0
    salida=$(bash "$SCANNER" "$proyecto" 2>&1) || obtenido=1
    if [ "$obtenido" != "$esperado" ]; then
        echo "FALLO: $descripcion (salida $obtenido, esperada $esperado)"
        FALLOS=$((FALLOS + 1))
    elif [ -n "$patron" ] && ! grep -q "$patron" <<<"$salida"; then
        echo "FALLO: $descripcion no informa «${patron}»"
        FALLOS=$((FALLOS + 1))
    fi
}

espera 0 "pyproject.toml y uv.lock reales" "$(crear_proyecto limpio)"

proyecto=$(crear_proyecto sin-lock)
rm "$proyecto/uv.lock"
espera 1 "falta uv.lock" "$proyecto" "Falta uv.lock"

proyecto=$(crear_proyecto lock-ignorado)
printf 'uv.lock\n' >>"$proyecto/.gitignore"
espera 1 "uv.lock en .gitignore" "$proyecto" "uv.lock está ignorado"

proyecto=$(crear_proyecto dependencia-sin-resolver)
sed -i.bak 's/^dependencies = \[$/dependencies = [\n    "paquete-ficticio-sin-lock>=1.0",/' "$proyecto/pyproject.toml"
espera 1 "dependencia que no está en uv.lock" "$proyecto" "sin versión resuelta en uv.lock: paquete-ficticio-sin-lock"

proyecto=$(crear_proyecto vcs-flotante)
sed -i.bak 's/^dependencies = \[$/dependencies = [\n    "paquete-ficticio-vcs @ git+https:\/\/example.invalid\/p.git@main",/' "$proyecto/pyproject.toml"
espera 1 "dependencia de Git que apunta a una rama" "$proyecto" "referencia VCS flotante"

proyecto=$(crear_proyecto grupo-sin-resolver)
sed -i.bak 's/^dev = \[$/dev = [\n    "herramienta-ficticia-sin-lock>=1.0",/' "$proyecto/pyproject.toml"
espera 1 "dependencia de desarrollo que no está en uv.lock" "$proyecto" "sin versión resuelta en uv.lock: herramienta-ficticia-sin-lock"

# uv lock --check: una restricción que el lock no cumple, sin ningún otro fallo.
if command -v uv >/dev/null 2>&1; then
    proyecto=$(crear_proyecto lock-incoherente)
    sed -i.bak 's/"fastapi>=[0-9.]*"/"fastapi>=999.0"/' "$proyecto/pyproject.toml"
    espera 1 "pyproject.toml incoherente con uv.lock" "$proyecto" "uv.lock no es coherente"
else
    echo "AVISO: sin uv no se prueba la comprobación de coherencia del lock"
fi

proyecto=$(crear_proyecto git-flotante)
cat >>"$proyecto/uv.lock" <<'TOML'

[[package]]
name = "paquete-ficticio-git"
version = "0.1.0"
source = { git = "https://example.invalid/paquete.git?branch=main#abc" }
TOML
espera 1 "fuente Git sin fijar a un commit" "$proyecto" "fuente Git no fijada a commit: paquete-ficticio-git"

if [ "$FALLOS" -gt 0 ]; then
    echo "test_scan_dependencies: $FALLOS fallos"
    exit 1
fi
echo "test_scan_dependencies: OK"
