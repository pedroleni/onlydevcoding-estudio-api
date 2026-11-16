#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
SCANNER="$PROJECT_ROOT/scripts/security/scan_configs.sh"
TEMP_ROOT=$(mktemp -d)
trap 'rm -rf "$TEMP_ROOT"' EXIT

crear_proyecto() {
    local nombre="$1"
    local proyecto="$TEMP_ROOT/$nombre"
    mkdir -p "$proyecto/estudio_api" "$proyecto/tests" "$proyecto/scripts" \
        "$proyecto/.github/workflows"
    printf '%s\n' "$proyecto"
}

esperar_bloqueo() {
    local proyecto="$1"
    local patron="$2"
    local salida
    local estado=0
    salida=$(bash "$SCANNER" "$proyecto" 2>&1) || estado=$?
    if [ "$estado" -eq 0 ]; then
        printf 'El scanner no bloqueó %s\n' "$patron" >&2
        return 1
    fi
    if ! grep -Eq "$patron" <<<"$salida"; then
        printf 'El scanner no informó %s. Salida:\n%s\n' "$patron" "$salida" >&2
        return 1
    fi
}

proyecto=$(crear_proyecto permissions-write-all)
cat >"$proyecto/.github/workflows/prueba.yml" <<'YAML'
name: Prueba
permissions: write-all
jobs: {}
YAML
esperar_bloqueo "$proyecto" 'write-all'

proyecto=$(crear_proyecto permissions-scope-write)
cat >"$proyecto/.github/workflows/prueba.yml" <<'YAML'
name: Prueba
permissions:
  contents: write
jobs: {}
YAML
esperar_bloqueo "$proyecto" 'contents: write'

proyecto=$(crear_proyecto uses-sin-guion)
cat >"$proyecto/.github/workflows/prueba.yml" <<'YAML'
name: Prueba
permissions:
  contents: read
jobs:
  prueba:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
YAML
esperar_bloqueo "$proyecto" 'actions/checkout@v4'

proyecto=$(crear_proyecto pull-request-target)
cat >"$proyecto/.github/workflows/prueba.yml" <<'YAML'
name: Prueba
on: pull_request_target
permissions:
  contents: read
jobs: {}
YAML
esperar_bloqueo "$proyecto" 'pull_request_target'

bash "$SCANNER" "$PROJECT_ROOT"
printf 'OK: contrato de scan_configs verificado.\n'
