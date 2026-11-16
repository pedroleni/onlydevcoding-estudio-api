#!/usr/bin/env bash
# Configura los hooks versionados de este repositorio.
set -euo pipefail

PROJECT_ROOT="${1:-.}"
cd "$PROJECT_ROOT"

git rev-parse --show-toplevel >/dev/null 2>&1 || {
    echo "ERROR: no es un repositorio Git: $PROJECT_ROOT" >&2
    exit 1
}

chmod +x .githooks/pre-commit
git config core.hooksPath .githooks
echo "OK: core.hooksPath apunta a .githooks; el escaneo de secretos está activo."

