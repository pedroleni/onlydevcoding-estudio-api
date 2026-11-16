#!/usr/bin/env bash
# Busca indicadores de prompt injection sin escanear su propia documentación.
set -euo pipefail

PROJECT_ROOT="${1:-.}"
FINDINGS=0

finding() {
    local severity="$1" detail="$2"
    printf '[%s] %s\n' "$severity" "$detail"
    case "$severity" in CRITICAL|HIGH) FINDINGS=$((FINDINGS + 1));; esac
}

echo "=== Escáner de prompt injection ==="

for required_dir in estudio_api tests scripts docs .claude; do
    if [ ! -d "$PROJECT_ROOT/$required_dir" ]; then
        finding HIGH "Falta la raíz de escaneo requerida: $required_dir/"
    fi
done
for required_file in README.md AGENTS.md CLAUDE.md pyproject.toml; do
    if [ ! -f "$PROJECT_ROOT/$required_file" ]; then
        finding HIGH "Falta el archivo de escaneo requerido: $required_file"
    fi
done

if ! python3 - "$PROJECT_ROOT" <<'PY'
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
roots = [
    root / "estudio_api",
    root / "tests",
    root / "scripts",
    root / "docs",
    root / ".claude",
]
config_files = [
    root / "README.md",
    root / "AGENTS.md",
    root / "CLAUDE.md",
    root / "pyproject.toml",
]
suffixes = {".py", ".sh", ".md", ".toml", ".yml", ".yaml", ".json"}
files = list(config_files)
for base in roots:
    if base.exists():
        files.extend(
            path for path in base.rglob("*")
            if path.is_file()
            and path.suffix in suffixes
            and not (
                base == root / "scripts"
                and path.parent == root / "scripts/security"
                and path.name.startswith("scan_")
            )
        )

invisible = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff\u00ad]")
directive = re.compile(
    r"ignore.{0,30}(previous|above).{0,20}instruction|"
    r"you are now|system prompt|disregard.{0,30}(previous|all)|"
    r"act as.{0,20}(root|system|unrestricted)|"
    r"(hidden|secret).{0,20}instruction",
    re.IGNORECASE,
)
encoded = re.compile(r"(?:[A-Za-z0-9+/]{4}){15,}={0,2}")
errors = []
for path in dict.fromkeys(files):
    if not path.exists() or path.stat().st_size > 1_000_000:
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    for number, line in enumerate(text.splitlines(), 1):
        if invisible.search(line):
            errors.append(f"carácter Unicode invisible en {path.relative_to(root)}:{number}")
        if directive.search(line):
            errors.append(f"directiva dirigida a agentes en {path.relative_to(root)}:{number}")
        if encoded.search(line) and line.lstrip().startswith(("#", "//", "<!--")):
            errors.append(f"payload codificado en comentario en {path.relative_to(root)}:{number}")
for error in errors:
    print(f"[CRITICAL] {error}")
if errors:
    raise SystemExit(1)
print("OK: sin caracteres ocultos, directivas maliciosas ni payloads codificados.")
PY
then
    FINDINGS=$((FINDINGS + 1))
fi

for config in "$PROJECT_ROOT/AGENTS.md" "$PROJECT_ROOT/CLAUDE.md"; do
    [ -f "$config" ] || continue
    if grep -Eqi 'dangerously-skip-permissions|always[[:space:]]+approve|auto[- ]?execute' "$config"; then
        finding CRITICAL "Configuración de agente permisiva en $config."
    fi
done

if [ "$FINDINGS" -gt 0 ]; then
    echo "Bloqueo: $FINDINGS hallazgo(s) CRITICAL/HIGH."
    exit 1
fi
echo "OK: sin indicadores CRITICAL/HIGH de prompt injection."
