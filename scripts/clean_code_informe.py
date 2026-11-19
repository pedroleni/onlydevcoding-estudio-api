"""Informe completo de clean code (docs/clean-code.md) en Markdown por la salida estándar.

Deuda congelada (los ``# noqa`` de complejidad), duplicados contando los tests y
candidatos a código muerto con confianza baja. Lo usa la revisión semanal de GitHub y el
agente clean-code en modo auditoria:

    uv run --frozen python scripts/clean_code_informe.py
"""

import re
import subprocess
from collections import Counter
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
REGLAS_DEUDA = re.compile(r"#\s*noqa:\s*([A-Z0-9, ]+)")
CODIGOS_COMPLEJIDAD = {"C901", "PLR0911", "PLR0912", "PLR0913", "PLR0915"}


def ejecutar(*orden: str) -> str:
    resultado = subprocess.run(
        orden, cwd=RAIZ, capture_output=True, text=True, check=False
    )
    return (resultado.stdout + resultado.stderr).strip()


def deuda_congelada() -> str:
    por_regla: Counter[str] = Counter()
    por_archivo: Counter[str] = Counter()
    for ruta in sorted((RAIZ / "estudio_api").rglob("*.py")):
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            coincidencia = REGLAS_DEUDA.search(linea)
            if not coincidencia:
                continue
            codigos = {
                c.strip() for c in coincidencia.group(1).split(",")
            } & CODIGOS_COMPLEJIDAD
            por_regla.update(codigos)
            if codigos:
                por_archivo[str(ruta.relative_to(RAIZ))] += 1
    lineas = [
        "## Deuda congelada (`# noqa` de complejidad)",
        "",
        f"**{sum(por_archivo.values())}** funciones en {len(por_archivo)} archivos.",
        "",
        "| Regla | Funciones |",
        "|---|---|",
        *(f"| `{regla}` | {n} |" for regla, n in por_regla.most_common()),
        "",
        "Archivos con más deuda:",
        "",
        *(f"- `{archivo}`: {n}" for archivo, n in por_archivo.most_common(10)),
    ]
    return "\n".join(lineas)


def duplicados() -> str:
    salida = ejecutar(
        "pylint",
        "estudio_api",
        "tests",
        "--disable=all",
        "--enable=duplicate-code",
        "--min-similarity-lines=6",
        "--ignore-imports=y",
        "--ignore-signatures=y",
        "--score=n",
    )
    bloques = salida.count("R0801")
    detalle = "\n".join(
        linea for linea in salida.splitlines() if linea.startswith("==")
    )
    return "\n".join(
        [
            "## Duplicados (contando los tests)",
            "",
            (
                f"**{bloques}** bloques repetidos de 6 líneas o más. La puerta de CI solo mira "
                "`estudio_api/`; aquí entran los tests, para ver dónde convendría un `parametrize` o "
                "una fábrica."
            ),
            "",
            f"```\n{detalle}\n```" if detalle else "Sin bloques repetidos.",
        ]
    )


def codigo_muerto() -> str:
    salida = ejecutar(
        "vulture", "estudio_api", "--min-confidence", "60", "--ignore-names", "cls"
    )
    candidatos = [linea for linea in salida.splitlines() if "confidence" in linea]
    return "\n".join(
        [
            "## Candidatos a código muerto (vulture, confianza 60 %)",
            "",
            (
                f"**{len(candidatos)}** candidatos. Con confianza baja hay muchos falsos positivos "
                "(campos de Pydantic, rutas de FastAPI, validadores): revisarlos a mano."
            ),
            "",
            "```\n" + "\n".join(candidatos[:30]) + "\n```"
            if candidatos
            else "Sin candidatos.",
        ]
    )


def main() -> None:
    commit = ejecutar("git", "rev-parse", "--short", "HEAD")
    print(
        "\n\n".join(
            [
                "# Informe de clean code de la API",
                f"Generado el {date.today().isoformat()} sobre `{commit}`.",
                deuda_congelada(),
                duplicados(),
                codigo_muerto(),
            ]
        )
    )


if __name__ == "__main__":
    main()
