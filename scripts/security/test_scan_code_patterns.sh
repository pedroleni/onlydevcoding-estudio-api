#!/usr/bin/env bash
# Contrato: el escáner de patrones de código pasa con código limpio, bloquea cada patrón
# peligroso de Python y avisa sin bloquear de las trazas internas.
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
SCANNER="$PROJECT_ROOT/scripts/security/scan_code_patterns.sh"
TEMP_ROOT=$(mktemp -d)
trap 'rm -rf "$TEMP_ROOT"' EXIT
FALLOS=0

crear_proyecto() {
    local proyecto="$TEMP_ROOT/$1"
    mkdir -p "$proyecto/estudio_api" "$proyecto/tests" "$proyecto/scripts"
    printf 'def sumar(a, b):\n    return a + b\n' >"$proyecto/estudio_api/limpio.py"
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

# Cada caso planta una línea en un .py. Los patrones van troceados para que este
# archivo no los contenga literalmente.
planta() {
    local nombre="$1" carpeta="$2" linea="$3"
    local proyecto
    proyecto=$(crear_proyecto "$nombre")
    printf '%s\n' "$linea" >"$proyecto/$carpeta/plantado.py"
    printf '%s\n' "$proyecto"
}

espera 0 "código limpio" "$(crear_proyecto limpio)"
espera 0 "el código real del repo" "$PROJECT_ROOT"

espera 1 "shell activado" "$(planta shell estudio_api "run(orden, shell""=True)")" "Inyección de comandos"
espera 1 "os.system" "$(planta system tests "import os; os.sys""tem('ls')")" "Inyección de comandos"
espera 1 "eval" "$(planta eval scripts "resultado = ev""al(texto)")" "Ejecución dinámica"
espera 1 "pickle" "$(planta pickle estudio_api "datos = pickle.lo""ads(cuerpo)")" "Deserialización insegura"
espera 1 "TLS sin verificar" "$(planta tls estudio_api "get(url, verify""=False)")" "TLS sin verificar"
espera 1 "servidor expuesto" "$(planta host estudio_api "run(app, host=\"0.0.""0.0\")")" "Servidor expuesto"
espera 1 "ruta desde la petición" "$(planta ruta estudio_api "open(request"".args['f'])")" "Posible traversal"
espera 0 "traza interna: avisa sin bloquear" "$(planta traza estudio_api "texto = traceback.format""_exc()")" "Traza interna"

proyecto=$(crear_proyecto sin-tests)
rmdir "$proyecto/tests"
espera 1 "falta una carpeta que se escanea" "$proyecto" "Falta la raíz de escaneo requerida: tests/"

if [ "$FALLOS" -gt 0 ]; then
    echo "test_scan_code_patterns: $FALLOS fallos"
    exit 1
fi
echo "test_scan_code_patterns: OK"
