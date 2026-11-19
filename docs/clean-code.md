# Normas de clean code

Este documento es la referencia del agente de clean code (`.claude/agents/clean-code.md`)
y de cualquiera que escriba código en el repo, persona o agente. Se basa en una investigación
de noviembre de 2026 sobre las guías oficiales y reconocidas de cada tecnología (las fuentes
están al final) y en las convenciones que ya sigue el repo, que mandan sobre cualquier norma
externa.

## Cómo se aplica

1. **Puerta automática (CI, bloqueante).** Lo que se puede medir lo comprueban herramientas
   en cada PR, en GitHub Actions y en Jenkins: ruff con reglas de complejidad y simplificación, pylint (duplicados) y vulture (código muerto). Se ejecuta en local con
   `uv run --frozen bash scripts/clean_code.sh`.
2. **Revisión del agente (antes de abrir la PR, bloqueante).** Lo que necesita criterio
   (nombres, responsabilidades, abstracciones, efectos, tests) lo revisa el agente
   `clean-code` sobre el diff contra `main`, con la suscripción de Claude Code y sin claves de
   API. Su veredicto va en la sección «Revisión clean code» de la descripción de la PR; la CI
   falla si falta o si no dice `Veredicto: APROBADO`.
3. **Revisión completa periódica.** Cada semana, un workflow de GitHub ejecuta el informe
   completo (`uv run --frozen python scripts/clean_code_informe.py`) y lo deja en el resumen de la ejecución de GitHub Actions y como artefacto
   `informe-clean-code`. Cuando se
   quiera, el agente hace la auditoría completa en modo `auditoria` y propone por dónde
   reducir la deuda.

### Deuda congelada

El código anterior a estas normas ya incumplía algunos umbrales. Esas funciones llevan `# noqa` con el código de la regla (`C901`, `PLR09xx`); son deuda visible que la revisión periódica va quitando, y un `noqa` nuevo de complejidad no se acepta sin justificarlo. Lo nuevo no puede
añadir deuda: una PR que necesite una excepción nueva la justifica en la descripción y el
agente decide si es aceptable.

## Puerta automática de este repo

| Comprobación | Herramienta | Umbral |
|---|---|---|
| Complejidad ciclomática | ruff `C90` (mccabe) | 12 |
| Ramas, `return`, sentencias, argumentos | ruff `PLR0912`, `PLR0911`, `PLR0915`, `PLR0913` | 12, 6, 50, 6 |
| Simplificaciones y legibilidad | ruff `SIM`, `RET`, `PIE`, `C4`, `ERA` | 0 |
| Trampas habituales y sintaxis moderna | ruff `B`, `UP`, `PERF` | 0 |
| Argumentos sin usar | ruff `ARG` (no en tests: fixtures) | 0 |
| Formato | `ruff format --check` | 0 |
| Duplicados | pylint `duplicate-code` en `estudio_api/` | 0 bloques de 6 líneas |
| Código muerto | `vulture --min-confidence 80` | 0 |

Comandos:

- `uv run --frozen bash scripts/clean_code.sh`: la puerta completa, igual que en CI.
- `uv run --frozen python scripts/clean_code_informe.py`: informe completo con la deuda
  congelada (`# noqa` de complejidad), los duplicados contando los tests y los candidatos a
  código muerto con confianza baja.

## Cómo leer este documento

Cada norma lleva:

- **Qué**: la regla en una frase.
- **Por qué**: el motivo, con la fuente.
- **Malo / Bueno**: ejemplo mínimo, con los nombres en español como en los repos.
- **Comprobación**: `DET` = determinista (regla concreta de herramienta) o `LLM` = necesita juicio del revisor.
- **Severidad**: `BLOQUEANTE` (no se integra) o `SUGERENCIA` (se comenta; también vale el prefijo `Nit:` de Google para
  detalles menores).

Criterio general de severidad, tomado de Google eng-practices: se aprueba un cambio cuando *mejora claramente la salud
del código*, aunque no sea perfecto; lo que no es crítico se marca como `Nit:` u opcional
(<https://google.github.io/eng-practices/review/reviewer/standard.html>,
<https://google.github.io/eng-practices/review/reviewer/comments.html>). Qué se mira en una revisión (diseño,
funcionalidad, complejidad, tests, nombres, comentarios, estilo, documentación):
<https://google.github.io/eng-practices/review/reviewer/looking-for.html>.

---

## Convenciones detectadas en los repos (prevalecen sobre las normas externas)

Leídas en `AGENTS.md`, configuración y código. El revisor **no** debe pedir que se cambien.
### Comunes

| Convención | Dónde se ve | Choque con fuente externa |
|---|---|---|
| Identificadores, comentarios, mensajes de error y nombres de test en **español**, en ASCII (sin tildes ni `ñ`: `PestanasLeccion`, `pestana`, `numero`) | todo el código | PEP 8 pide inglés *solo para la biblioteca estándar*; no aplica. Google Style Guides no exigen inglés. Sin choque real. |
| Comentarios que explican el **porqué** (seguridad, carreras, límites), no el qué | `app.py`, `useLectura.ts`, `FormularioTarea.tsx` | *Clean Code* (Martin) trata los comentarios como "fallo"; Google eng-practices pide justo comentarios de porqué. Se sigue al repo y a Google. |
| Supresiones siempre con motivo: `# noqa: BLE001 - motivo`, `// eslint-disable-next-line regla` + comentario encima | API y web | Ninguno: es lo que piden ruff (RUF100/PGH004) y `eslint-comments/require-description`. |
| Repo público: nada de rutas absolutas, emails ni textos reales; datos falsos en tests | `AGENTS.md` | — |
| Añadir dependencias exige autorización | `AGENTS.md` de ambos | Las herramientas de la puerta automática se añadieron con autorización, con versión fija. |
### API

| Convención | Detalle |
|---|---|
| Helpers privados con `_` (`_validar_enlace`, `_PATRON_FECHA`) | PEP 8. |
| Handlers **síncronos** (`def`), porque `sqlite3` y el disco son bloqueantes | Correcto según FastAPI (se ejecutan en el threadpool). |
| Config y BD por petición con `config_peticion(request)` + `with closing(abrir_bd(...)) as bd`, **sin `Depends`** | FastAPI recomienda `Depends` con `yield`; **choca** levemente → solo sugerencia, ver FA-03. |
| `response_model=` además de la anotación de retorno | Ruff FAST001 lo marca como redundante; **choca** → no activar FAST001 o aceptarlo como estilo. |
| Parámetros de ruta llamados `id` (`id: TareaId`) | Ruff A002 (sombrea el builtin) **choca** → ignorar A002 en `rutas_*.py` y `tareas.py`, o no activar `A`. |
| `assert x is not None` para estrechar tipos en código de producción | Ruff S101 **choca**; ver PY-10 (sugerencia, no bloqueo). |
| Modelos Pydantic estrictos: `ConfigDict(extra="forbid")`, `StrictBool`, `Field(strict=True, ge=…, le=…)`, validadores con mensajes en español | Mantener y exigir en modelos de entrada nuevos. |
| SQL siempre parametrizado (`?`), migraciones con `PRAGMA user_version`, `PRAGMA foreign_keys = ON`, copia antes de migrar, `BEGIN IMMEDIATE` para escrituras compuestas | Mantener. |
| Docstrings escasos (solo módulos/funciones no obvias), en español | PEP 257 / ruff `D` **chocan** si se exigen en todo → no activar `D` en bloque. |
| Tests: funciones `test_<frase_en_español>` sin clases, fixtures en `conftest.py`, datos en `tmp_path`, guardas que impiden tocar `datos/` | Mantener. |
| ruff configurado en `pyproject.toml` con las reglas de la puerta automática | Ver «Puerta automática de este repo». |

---

## Normas generales (ambos repos)

### GEN-01 · PR pequeño y cohesionado
- **Qué**: una tarea o grupo pequeño y cohesionado por rama/PR; refactor y cambio de comportamiento, separados.
- **Por qué**: los PR pequeños se revisan mejor y antes, y se revierten con menos riesgo (<https://google.github.io/eng-practices/review/developer/small-cls.html>); además lo exige `AGENTS.md`.
- **Malo**: "feat: tareas + refactor de publicación + subir deps". **Bueno**: tres PR.
- **Comprobación**: LLM (puede ayudar un aviso por tamaño de diff, p. ej. >400 líneas sin tests ni lockfile).
- **Severidad**: SUGERENCIA (BLOQUEANTE si mezcla cambios de seguridad o dependencias no autorizadas con otra cosa).

### GEN-02 · Nombres que revelan intención, con el vocabulario del dominio
- **Qué**: nombres descriptivos en español ASCII, usando siempre el mismo término para el mismo concepto (`curso`, `leccion`, `numero`, `pieza`, `red`, `toma`, `trabajo`, `entrega`). Nada de `data`, `tmp`, `x2`, `manejar`.
- **Por qué**: *Clean Code*, cap. 2; Google TS Style §Naming (<https://google.github.io/styleguide/tsguide.html#naming>); PEP 8 (<https://peps.python.org/pep-0008/#naming-conventions>).
- **Malo**: `const d = await f(c)`. **Bueno**: `const lecciones = await obtenerLecciones(curso)`.
- **Comprobación**: LLM. Lo formal (camelCase/PascalCase/snake_case) es DET: `@typescript-eslint/naming-convention` (no recomendado: ruido alto) y ruff `N` (pep8-naming).
- **Severidad**: SUGERENCIA; BLOQUEANTE si el nombre engaña (p. ej. `esValido` que además escribe en disco).

### GEN-03 · Funciones que hacen una cosa, a un solo nivel de abstracción
- **Qué**: cada función hace una cosa; si mezcla validar, persistir y formatear, se extrae.
- **Por qué**: *Clean Code* cap. 3; *Refactoring* "Extract Function" (<https://refactoring.com/catalog/extractFunction.html>); "Long Function" (<https://refactoring.guru/smells/long-method>).
- **Malo**: un handler de 120 líneas que valida, consulta, construye la vista y maneja errores. **Bueno**: handler corto que llama a `_validar_enlace`, `crear_tarea`, `_vista_unica` (como `rutas_tareas.py`).
- **Comprobación**: DET aproximado con límites («Puerta automática»: complejidad, longitud, parámetros, anidación); el "una cosa" es LLM.
- **Severidad**: BLOQUEANTE si supera el umbral duro de CI; SUGERENCIA por debajo.

### GEN-04 · Cláusulas de guarda en lugar de anidación
- **Qué**: salir pronto (`if (!x) return …`) en vez de pirámides de `if`.
- **Por qué**: "Replace Nested Conditional with Guard Clauses" (<https://refactoring.com/catalog/replaceNestedConditionalWithGuardClauses.html>); la complejidad cognitiva penaliza la anidación (<https://www.sonarsource.com/docs/CognitiveComplexity.pdf>).
- **Malo**: `if (a) { if (b) { if (c) { … } } }`. **Bueno**: `if (!a) return; if (!b) return; …`.
- **Comprobación**: DET: ESLint `max-depth`, `sonarjs/cognitive-complexity`, `no-else-return`; ruff `PLR1702` (preview), `RET505`, `SIM102`.
- **Severidad**: según umbral («Puerta automática»).

### GEN-05 · Sin números ni cadenas mágicas repetidas; límites compartidos en un solo sitio
- **Qué**: los valores con significado (límites de longitud, rangos de días, códigos) van en constantes con nombre. Los límites que valen en web y API (p. ej. 300 caracteres de tarea, lecciones 1–999, `^[a-z0-9-]{1,40}$`) se cambian **a la vez en los dos repos**.
- **Por qué**: *Refactoring* "Replace Magic Literal" (<https://refactoring.com/catalog/replaceMagicLiteral.html>); el contrato web↔API está duplicado (`src/lib/limites.ts`, `src/lib/curso.ts` frente a `tareas.py`, `modelos.py`).
- **Malo**: `if not 1 <= len(t) <= 300` y en la web `maxLength={250}`. **Bueno**: constante con nombre en cada lado y el mismo valor.
- **Comprobación**: DET parcial: ruff `PLR2004` (ruidoso; ignora 0, 1, "", etc.); ESLint `no-magic-numbers` (desaconsejado: demasiado ruido en JSX). La coherencia entre repos es LLM.
- **Severidad**: BLOQUEANTE si un PR cambia un límite en un repo y no en el otro; SUGERENCIA en el resto.

### GEN-06 · Sin duplicación de lógica
- **Qué**: no copiar bloques de lógica; extraer función o tabla de datos. La duplicación en tests (datos de prueba explícitos) se tolera más.
- **Por qué**: DRY y "Duplicated Code" (<https://refactoring.guru/smells/duplicate-code>); Google eng-practices pide código que no sea más complejo de lo necesario.
- **Malo**: dos componentes con el mismo bloque de 15 líneas para el foco del diálogo. **Bueno**: un hook `useDialogoModal`.
- **Comprobación**: DET: `jscpd` (<https://github.com/kucherenko/jscpd>) en TS y Python; `sonarjs/no-identical-functions`, `sonarjs/no-all-duplicated-branches`, `sonarjs/no-duplicated-branches`.
- **Severidad**: BLOQUEANTE si el PR *añade* un clon por encima del umbral («Puerta automática»); SUGERENCIA para clones previos.

### GEN-07 · Sin código muerto ni comentado
- **Qué**: no dejar exports, funciones, archivos o dependencias sin uso, ni código comentado.
- **Por qué**: "Dead Code" (<https://refactoring.guru/smells/dead-code>); el control de versiones ya guarda la historia.
- **Malo**: `// const viejo = calcular(x);`. **Bueno**: borrarlo.
- **Comprobación**: DET: web `knip` (<https://knip.dev>), `@typescript-eslint/no-unused-vars` (ya activa); API `vulture` (<https://github.com/jendrikseipp/vulture>) con `--min-confidence 80` e `--ignore-decorators "@router.*,@field_validator,@model_validator"`, ruff `F401`/`F841` (ya activas), `ERA001` (código comentado).
- **Severidad**: BLOQUEANTE para variables/imports sin uso (ya lo es); SUGERENCIA para exports muertos (knip/vulture dan falsos positivos con convenciones de framework).

### GEN-08 · Comentarios: porqué, en español, actualizados
- **Qué**: comentar decisiones no evidentes (seguridad, carreras, compatibilidad), no parafrasear el código. Si el código cambia, el comentario también.
- **Por qué**: Google eng-practices "Comments" (<https://google.github.io/eng-practices/review/reviewer/looking-for.html#comments>); PEP 8 §Comments (<https://peps.python.org/pep-0008/#comments>).
- **Malo**: `// incrementa i`. **Bueno**: `// Sin /docs: cargan JS de un CDN en el mismo origen que la API.`
- **Comprobación**: LLM.
- **Severidad**: BLOQUEANTE si el comentario queda falso tras el cambio (engaña); SUGERENCIA en el resto.

### GEN-09 · Supresiones justificadas y mínimas
- **Qué**: toda supresión (`eslint-disable`, `@ts-expect-error`, `# noqa`, `# type: ignore`) es de línea, nombra la regla y explica por qué. Prohibido `@ts-ignore` y `noqa` genérico.
- **Por qué**: typescript-eslint `ban-ts-comment` (<https://typescript-eslint.io/rules/ban-ts-comment>); ruff `PGH004` (<https://docs.astral.sh/ruff/rules/blanket-noqa/>) y `RUF100` (<https://docs.astral.sh/ruff/rules/unused-noqa/>); ESLint `reportUnusedDisableDirectives` (<https://eslint.org/docs/latest/use/configure/configuration-files#reporting-unused-disable-directives>).
- **Malo**: `// eslint-disable-next-line`. **Bueno**: `// Solo al abrir el diálogo.` + `// eslint-disable-next-line react-hooks/exhaustive-deps`.
- **Comprobación**: DET: `@typescript-eslint/ban-ts-comment` (ya en recommended), `@eslint-community/eslint-comments/require-description` y `no-unlimited-disable` (dependencia nueva), `linterOptions.reportUnusedDisableDirectives: "error"`; ruff `PGH004`, `RUF100`. Que el motivo sea **válido** es LLM.
- **Severidad**: BLOQUEANTE.

### GEN-10 · Errores: no tragarlos, conservar la causa, mensajes útiles
- **Qué**: capturar solo lo esperado, traducirlo a un error del dominio conservando la causa, y no silenciar excepciones.
- **Por qué**: Google Python Style §2.4 Exceptions (<https://google.github.io/styleguide/pyguide.html#24-exceptions>); ESLint `preserve-caught-error` (<https://eslint.org/docs/latest/rules/preserve-caught-error>); ruff `B904` (<https://docs.astral.sh/ruff/rules/raise-without-from-inside-except/>).
- **Malo**: `except Exception: pass` / `catch { throw new Error("falló") }`. **Bueno**: `raise HTTPException(409, …) from error` / `throw new ApiNoDisponible(undefined, { cause })`.
- **Comprobación**: DET: ruff `BLE001`, `S110` (`try/except/pass`), `B904`, `TRY` (subconjunto), `SIM105`; ESLint `preserve-caught-error`, `@typescript-eslint/only-throw-error` (type-checked), `no-empty`. Que la captura sea la adecuada es LLM.
- **Severidad**: BLOQUEANTE (tragar errores o perder la causa); SUGERENCIA para el texto del mensaje.

### GEN-11 · Cada cambio de comportamiento trae su test
- **Qué**: todo cambio de comportamiento o bug corregido incluye un test que falla sin el cambio.
- **Por qué**: Google eng-practices "Tests" (<https://google.github.io/eng-practices/review/reviewer/looking-for.html#tests>).
- **Comprobación**: LLM (la cobertura de diff con `vitest --coverage` / `pytest-cov` + `diff-cover` sería DET, pero añade dependencias).
- **Severidad**: BLOQUEANTE para lógica nueva en `lib/`, Server Actions, rutas o validadores; SUGERENCIA para cambios puramente visuales.

---

## Python 3.14, FastAPI, Pydantic v2, SQLite y pytest (API)

Fuentes base: PEP 8 <https://peps.python.org/pep-0008/>, PEP 20 <https://peps.python.org/pep-0020/>,
PEP 257 <https://peps.python.org/pep-0257/>, Google Python Style <https://google.github.io/styleguide/pyguide.html>,
reglas de ruff <https://docs.astral.sh/ruff/rules/>, novedades de 3.14 <https://docs.python.org/3.14/whatsnew/3.14.html>.

### Python

#### PY-01 · Legible antes que ingenioso (PEP 20)
- **Qué**: "lo explícito es mejor que lo implícito", "plano es mejor que anidado", "si la implementación es difícil de explicar, es mala idea".
- **Malo**: comprensión con tres `for` y dos `if`. **Bueno**: bucle con nombres intermedios.
- **Comprobación**: LLM; DET parcial: `C901`, `PLR1702`, `SIM` (simplificaciones), `C4` (comprensiones).
- **Severidad**: SUGERENCIA.

#### PY-02 · Anotaciones de tipo en todo el código de producción
- **Qué**: funciones de `estudio_api/` con parámetros y retorno anotados (ya es así); en tests no se exige. Usar sintaxis moderna (`X | None`, `list[str]`, `collections.abc`). En 3.14 las anotaciones son diferidas (PEP 649/749): no hace falta `from __future__ import annotations`.
- **Por qué**: PEP 484 <https://peps.python.org/pep-0484/>, PEP 604, PEP 649 <https://peps.python.org/pep-0649/>.
- **Malo**: `def leer(config, curso):`. **Bueno**: `def leer(config: Config, curso: str) -> Curso | None:`.
- **Comprobación**: DET: ruff `ANN001`, `ANN201`, `ANN202` solo en `estudio_api/**`; `UP006`, `UP007`, `UP035`, `FA` no aplica. Comprobador de tipos (mypy o pyright) **no está en CI**: proponerlo como determinista (dependencia nueva).
- **Severidad**: BLOQUEANTE (anotaciones en producción); el comprobador de tipos, SUGERENCIA hasta tener línea base.
- **Choque**: `UP040` (alias con `type X = …`) no conviene en los alias `Annotated[...]` que usa FastAPI como parámetros (`TareaId`, `TipoId`); no forzarla ahí.

#### PY-03 · Docstrings donde aportan, en español
- **Qué**: docstring en módulos y en funciones públicas cuyo contrato no es obvio (efectos en disco, excepciones, invariantes); formato PEP 257 (resumen de una línea, cuerpo opcional). No en cada función trivial.
- **Por qué**: PEP 257; Google Python Style §3.8.
- **Comprobación**: LLM. **No activar ruff `D` en bloque** (choca con el repo); como mucho `D200`–`D210`/`D300` para el formato de los que existen.
- **Severidad**: SUGERENCIA.

#### PY-04 · Rutas con `pathlib` y siempre dentro de una raíz permitida
- **Qué**: `Path` en vez de `os.path`; toda ruta abierta se resuelve y se comprueba dentro de `CURSOS_DIR`/`ESTUDIO_DIR` (sin `..`, absolutas ni symlinks que salgan).
- **Por qué**: `AGENTS.md`; <https://docs.python.org/3/library/pathlib.html#pathlib.PurePath.is_relative_to>.
- **Comprobación**: DET: ruff `PTH` (uso de `os.path`); la contención es LLM.
- **Severidad**: BLOQUEANTE (contención); SUGERENCIA (`PTH`).

#### PY-05 · Procesos con lista cerrada, nunca `shell=True`
- **Comprobación**: DET: ruff `S602`, `S604`, `S605`, `S607`; `S603` revisado por LLM.
- **Severidad**: BLOQUEANTE.

#### PY-06 · Excepciones concretas y encadenadas
- **Qué**: capturar la excepción concreta; `raise … from error`; `except Exception` solo con `# noqa: BLE001 - motivo` (convención del repo). En 3.14, `return`/`break`/`continue` dentro de `finally` emiten `SyntaxWarning` (PEP 765): no usarlos.
- **Por qué**: PEP 765 <https://peps.python.org/pep-0765/>; Google Python Style §2.4.
- **Comprobación**: DET: `BLE001`, `B904`, `S110`, `S112`, `TRY002`, `TRY300`, `TRY400`, `B012` (return en finally).
- **Severidad**: BLOQUEANTE.

#### PY-07 · Evitar argumentos por defecto mutables y estado global
- **Malo**: `def f(lista=[])`. **Bueno**: `def f(lista: list[str] | None = None)`.
- **Comprobación**: DET: ruff `B006`, `B008` (ojo: B008 da falsos positivos con FastAPI `Depends`; usar `lint.flake8-bugbear.extend-immutable-calls`), `PLW0603` (global).
- **Severidad**: BLOQUEANTE.

#### PY-08 · Modernizar con pyupgrade y simplificar
- **Comprobación**: DET: ruff `UP` (con `target-version = "py314"`), `SIM`, `C4`, `RET`, `PIE`, `PERF` (subconjunto).
- **Severidad**: SUGERENCIA (autocorregible).

#### PY-09 · Nombres que no sombrean builtins… salvo la convención `id`
- **Qué**: no sombrear `list`, `type`, `input`, etc.; el parámetro `id` en rutas y repositorios está aceptado por convención (coincide con el nombre de la ruta `/tareas/{id}`).
- **Comprobación**: DET: ruff `A001`/`A002` con `per-file-ignores` para `A002` en `rutas_*.py` y `tareas.py`, o `lint.flake8-builtins.ignorelist = ["id"]` (<https://docs.astral.sh/ruff/settings/#lint_flake8-builtins_ignorelist>).
- **Severidad**: SUGERENCIA.

#### PY-10 · `assert` no es validación
- **Qué**: no usar `assert` para validar entrada ni para invariantes cuya rotura deba dar un error controlado (con `python -O` desaparecen). El repo lo usa para estrechar tipos tras una operación que no puede devolver `None` (`assert tarea is not None`): aceptable, pero mejor un `if … : raise RuntimeError(...)` como en `crear_tarea`.
- **Por qué**: <https://docs.python.org/3/reference/simple_stmts.html#the-assert-statement>; Google Python Style §2.4.4.
- **Comprobación**: DET: ruff `S101` (solo en `estudio_api/**`; nunca en tests).
- **Severidad**: SUGERENCIA para el estrechamiento; BLOQUEANTE si valida entrada externa.

### FastAPI

Fuentes: <https://fastapi.tiangolo.com/async/>, <https://fastapi.tiangolo.com/tutorial/dependencies/>,
<https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/>,
<https://fastapi.tiangolo.com/tutorial/bigger-applications/>, <https://fastapi.tiangolo.com/tutorial/response-model/>,
<https://fastapi.tiangolo.com/tutorial/handling-errors/>,
<https://fastapi.tiangolo.com/tutorial/path-params-numeric-validations/>, reglas ruff FAST
<https://docs.astral.sh/ruff/rules/#fastapi-fast>.

#### FA-01 · `def` para trabajo bloqueante, `async def` solo con `await` real
- **Qué**: handlers que usan `sqlite3`, disco o `subprocess` son `def` (FastAPI los lleva al threadpool). Un `async def` que hace E/S bloqueante bloquea el bucle de eventos entero.
- **Malo**: `async def listar(): return tareas_entre(bd, …)`. **Bueno**: `def listar(): …` (como el repo).
- **Comprobación**: DET parcial: ruff `ASYNC` (`ASYNC230` open bloqueante, `ASYNC221`/`ASYNC220` subprocess, `ASYNC251` `time.sleep`); el resto LLM.
- **Severidad**: BLOQUEANTE.

#### FA-02 · Handlers finos: la lógica vive en módulos de dominio
- **Qué**: `rutas_*.py` solo traduce HTTP ↔ dominio (validar, llamar a `tareas.py`/`publicacion.py`, mapear errores a `HTTPException`); nada de SQL ni lógica de negocio en el handler.
- **Por qué**: "Bigger applications" de FastAPI; separación de responsabilidades.
- **Comprobación**: LLM (DET parcial: prohibir `bd.execute` en `rutas_*.py` con un grep; hoy hay `BEGIN IMMEDIATE` en algunos `rutas_*`, que es control de transacción y se tolera).
- **Severidad**: SUGERENCIA (BLOQUEANTE para SQL nuevo en un handler).

#### FA-03 · Inyección de dependencias (choque suave con el repo)
- **Qué**: FastAPI recomienda `Depends` con `yield` para recursos por petición (conexión a BD) y `Annotated[...]` para declararlos. El repo usa `config_peticion(request)` + `with closing(abrir_bd(...))` en cada handler, que es explícito y correcto. **No exigir migrar**; sí pedir que un recurso nuevo siga el mismo patrón y que, si se adopta `Depends`, se haga con `Annotated` (FAST002) en todo el router a la vez.
- **Comprobación**: DET: ruff `FAST002` (solo actúa si se usa `Depends`), `FAST003` (parámetro de ruta no declarado). LLM para coherencia.
- **Severidad**: SUGERENCIA.

#### FA-04 · Contratos de respuesta explícitos
- **Qué**: cada ruta declara el modelo de respuesta (anotación de retorno; el repo añade `response_model=`, redundante pero aceptado), `status_code` correcto (201 en altas, 204 sin cuerpo) y nunca devuelve un `dict` sin modelo salvo casos triviales (`/api/salud`).
- **Comprobación**: DET: anotación de retorno con `ANN201`; ruff `FAST001` **desactivada** (choca con el estilo del repo). Códigos de estado: LLM.
- **Severidad**: BLOQUEANTE si falta el modelo (fuga de campos).

#### FA-05 · Errores HTTP coherentes y en español
- **Qué**: 404 para "no existe", 409 para conflictos (`IntegrityError`), 422 para validación; `detail` en español, sin rutas ni trazas internas.
- **Comprobación**: LLM.
- **Severidad**: BLOQUEANTE si filtra detalles internos; SUGERENCIA en el resto.

#### FA-06 · Validar parámetros en la firma
- **Qué**: rangos y patrones en `Path`/`Query` con `Annotated` (`TareaId = Annotated[int, Path(ge=1, le=2**63 - 1)]`); los ids de curso cumplen `^[a-z0-9-]{1,40}$` y las lecciones 1–999.
- **Comprobación**: LLM.
- **Severidad**: BLOQUEANTE.

#### FA-07 · Seguridad local intacta
- **Qué**: no tocar `SeguridadLocalMiddleware`, CORS (`allow_methods=["GET"]`), ni reactivar `/docs`, `/redoc`, `/openapi.json` sin revisión de seguridad.
- **Comprobación**: LLM + agentes `security-*` del repo.
- **Severidad**: BLOQUEANTE.

### Pydantic v2

Fuentes: <https://docs.pydantic.dev/latest/concepts/models/>, <https://docs.pydantic.dev/latest/concepts/validators/>,
<https://docs.pydantic.dev/latest/concepts/strict_mode/>, <https://docs.pydantic.dev/latest/concepts/config/>,
<https://docs.pydantic.dev/latest/concepts/fields/>.

#### PD-01 · Modelos de entrada estrictos
- **Qué**: modelos que reciben datos del cliente heredan de un base con `ConfigDict(extra="forbid")`; booleanos `StrictBool`, enteros con `strict=True` y rangos; enumeraciones con `Literal`.
- **Malo**: `class Cambio(BaseModel): hecha: bool` (acepta `"yes"`). **Bueno**: `hecha: StrictBool` + `extra="forbid"`.
- **Comprobación**: LLM.
- **Severidad**: BLOQUEANTE.

#### PD-02 · Restricciones declarativas antes que validadores a mano
- **Qué**: preferir `Field(min_length=…, max_length=…, pattern=…, ge=…, le=…)` o `Annotated[str, StringConstraints(...)]`; validadores (`field_validator`, `model_validator(mode="after")`) para reglas entre campos o normalización (`strip`). Validadores con `@classmethod`, que devuelven el valor y lanzan `ValueError` con mensaje en español.
- **Malo**: `field_validator` que solo comprueba `len(v) <= 40`. **Bueno**: `Field(max_length=40)`; validador solo para "una sola línea" o jerarquía `pieza` → `numero`.
- **Comprobación**: LLM (DET: ruff `N805` para el primer argumento de validadores).
- **Severidad**: SUGERENCIA.
- **Nota**: el repo valida longitudes tras `strip()` dentro de validadores; es legítimo porque `Field` mediría antes de recortar.

#### PD-03 · API v2, no v1
- **Qué**: `model_validate`, `model_dump`, `model_config`, `field_validator`; nada de `parse_obj`, `.dict()`, `class Config`, `@validator`.
- **Por qué**: guía de migración <https://docs.pydantic.dev/latest/migration/>.
- **Comprobación**: DET: grep en CI (`\.dict\(|parse_obj|@validator|class Config:`); los avisos de deprecación de Pydantic en pytest con `-W error::pydantic.PydanticDeprecatedSince20`.
- **Severidad**: BLOQUEANTE.

#### PD-04 · Separar modelos de entrada, de dominio y de vista
- **Qué**: `TareaNueva` (entrada) / `Tarea` (persistida) / `TareaVista` (respuesta) como en el repo; no reutilizar el modelo de entrada como respuesta si añade campos internos.
- **Comprobación**: LLM.
- **Severidad**: SUGERENCIA.

### SQL en SQLite (`sqlite3`)

Fuentes: <https://docs.python.org/3/library/sqlite3.html#sqlite3-placeholders>,
<https://docs.python.org/3/library/sqlite3.html#sqlite3-howto-row-factory>,
<https://docs.python.org/3/library/sqlite3.html#sqlite3-transaction-control>,
<https://www.sqlite.org/foreignkeys.html>, <https://www.sqlite.org/pragma.html#pragma_user_version>,
<https://www.sqlite.org/stricttables.html>, <https://www.sqlite.org/lang_transaction.html>.

#### SQ-01 · Siempre parámetros, nunca SQL construido con datos
- **Malo**: `bd.execute(f"DELETE FROM tarea WHERE id = {id}")`. **Bueno**: `bd.execute("DELETE FROM tarea WHERE id = ?", (id,))`.
- **Comprobación**: DET: ruff `S608` (hardcoded-sql-expression). El `PRAGMA user_version = {VERSION_BD}` con constante es aceptable (los PRAGMA no admiten parámetros) con `# noqa: S608 - constante` si salta.
- **Severidad**: BLOQUEANTE.

#### SQ-02 · Transacciones explícitas y cortas
- **Qué**: escrituras dentro de `with bd:`; las compuestas de lectura-y-escritura con `BEGIN IMMEDIATE` (patrón del repo) para evitar carreras; nada de E/S lenta (render, subprocess) con la transacción abierta.
- **Comprobación**: LLM.
- **Severidad**: BLOQUEANTE.

#### SQ-03 · Conexiones siempre cerradas
- **Qué**: `with closing(abrir_bd(...)) as bd:` (en `sqlite3`, `with bd:` **no** cierra la conexión, solo hace commit/rollback).
- **Comprobación**: DET parcial: ruff `SIM115` no cubre `sqlite3.connect`; LLM.
- **Severidad**: BLOQUEANTE.

#### SQ-04 · Migraciones versionadas, idempotentes y con copia
- **Qué**: cada cambio de esquema sube `VERSION_BD`, añade su paso en `abrir_bd`, mantiene la copia previa y lleva test de migración desde la versión anterior. `PRAGMA foreign_keys = ON` en cada conexión.
- **Comprobación**: LLM (DET parcial: test que abre una BD de cada versión anterior).
- **Severidad**: BLOQUEANTE.

#### SQ-05 · Filas por nombre, no por posición
- **Qué**: en código nuevo, `bd.row_factory = sqlite3.Row` (o columnas nombradas) en lugar de `fila[9]`, que se rompe al añadir columnas.
- **Malo**: `hecha=fila[9]`. **Bueno**: `hecha=fila["hecha"]`.
- **Comprobación**: LLM.
- **Severidad**: SUGERENCIA (choca con el código existente de `tareas.py`; no exigir migrarlo en PR ajenos).

#### SQ-06 · Tipos e integridad en el esquema
- **Qué**: `NOT NULL`, `REFERENCES`, `CHECK` cuando la regla sea simple; valorar tablas `STRICT` en tablas nuevas; índices para las columnas filtradas (`idx_tarea_fecha`).
- **Comprobación**: LLM.
- **Severidad**: SUGERENCIA.

### Tests con pytest

Fuentes: <https://docs.pytest.org/en/stable/explanation/goodpractices.html>,
<https://docs.pytest.org/en/stable/how-to/fixtures.html>, <https://docs.pytest.org/en/stable/how-to/parametrize.html>,
<https://docs.pytest.org/en/stable/how-to/tmp_path.html>, <https://docs.pytest.org/en/stable/how-to/monkeypatch.html>,
<https://fastapi.tiangolo.com/tutorial/testing/>, reglas ruff PT <https://docs.astral.sh/ruff/rules/#flake8-pytest-style-pt>.

#### PT-01 · Datos siempre en `tmp_path`, nunca en `datos/`
- **Qué**: fixtures (`cfg`, `cliente`) que crean estructura falsa en `tmp_path`; respetar las guardas `_datos_reales_intactos` y `_sin_abrir_datos_reales`.
- **Comprobación**: DET (las guardas del propio `conftest.py` hacen fallar la batería).
- **Severidad**: BLOQUEANTE.

#### PT-02 · `parametrize` en vez de copiar tests
- **Malo**: cinco tests iguales que cambian el id inválido. **Bueno**: `@pytest.mark.parametrize("curso", ["", "A", "a" * 41, "../x"])`.
- **Comprobación**: DET parcial: `jscpd` sobre `tests/`; ruff `PT006`/`PT007` para el formato.
- **Severidad**: SUGERENCIA.

#### PT-03 · `pytest.raises` preciso
- **Qué**: con `match=` y una sola sentencia dentro.
- **Comprobación**: DET: ruff `PT011`, `PT012`, `PT017`, `PT018` (aserciones compuestas).
- **Severidad**: SUGERENCIA.

#### PT-04 · Nada de esperas reales
- **Qué**: no `time.sleep` para sincronizar; sondear con plazo máximo o inyectar el reloj.
- **Comprobación**: DET: grep de `time.sleep` en `tests/` (ruff no tiene regla directa para tests síncronos).
- **Severidad**: SUGERENCIA (BLOQUEANTE si el test es intermitente).

#### PT-05 · Un comportamiento por test, nombre en español
- **Qué**: `test_get_tareas_limita_el_rango_a_las_fechas_inclusivas`: Arrange/Act/Assert claros.
- **Comprobación**: LLM.
- **Severidad**: SUGERENCIA.

#### PT-06 · Avisos como errores
- **Qué**: los `DeprecationWarning` propios fallan (`filterwarnings = ["error", …]` con excepciones justificadas como la de `httpx`).
- **Comprobación**: DET (configuración de pytest).
- **Severidad**: SUGERENCIA (cambio de configuración, decide el autor).

---

## Checklist del agente revisor

Formato de cada comentario: `[BLOQUEANTE]` o `[SUGERENCIA]` (o `Nit:`), norma (`RE-03`), archivo:línea, motivo en una
frase y propuesta concreta. No repetir lo que ya marca el lint de CI. No pedir cambios que contradigan las convenciones del repo.

**Bloqueantes**
1. Server Action nueva o cambiada sin validar cada argumento `unknown` o sin devolver `ResultadoAccion` (NX-01).
2. Secretos o llamadas de escritura alcanzables desde un componente cliente; módulo con secreto sin `"server-only"` (NX-02, NX-03).
3. Escritura sin refresco/revalidación de la vista afectada; `"use cache"` con APIs de petición dentro (NX-04, NX-06).
4. `params`/`searchParams` o parámetros de ruta FastAPI sin validar contra los patrones del proyecto (NX-05, FA-06).
5. Efecto que deriva estado o sincroniza estado interno (RE-03); supresión de `exhaustive-deps` sin motivo válido (RE-02, GEN-09).
6. Estado duplicado que puede desincronizarse (RE-06).
7. Modelo Pydantic de entrada sin `extra="forbid"` o con tipos laxos (PD-01); API v1 de Pydantic (PD-03).
8. `async def` con E/S bloqueante (FA-01); SQL nuevo en un handler (FA-02).
9. SQL sin parámetros, transacción compuesta sin `BEGIN IMMEDIATE`, conexión sin `closing`, cambio de esquema sin migración versionada ni test (SQ-01 a SQ-04).
10. Ruta de disco sin contención en la raíz permitida; proceso con `shell=True` o argumentos externos (PY-04, PY-05).
11. Excepciones tragadas o sin causa (GEN-10, PY-06).
12. Límite o patrón compartido cambiado en un solo repo (GEN-05).
13. Comportamiento nuevo o bug corregido sin test que lo cubra (GEN-11); test que toca `datos/` o usa datos reales (PT-01, VT-05).
14. Tests asíncronos sin `await`/`findBy` o mocks que filtran estado (VT-02, VT-04).
15. Clases Tailwind interpoladas o colores fuera de los tokens propios en código nuevo (TW-01, TW-03).
16. Comentario que queda falso tras el cambio (GEN-08); nombre engañoso (GEN-02).

**Sugerencias**
1. Función que hace varias cosas o mezcla niveles de abstracción, aunque pase el umbral (GEN-03, GEN-04).
2. Componente largo o con muchos `useState` relacionados → hook propio o `useReducer` (RE-06, RE-10).
3. Supresiones `exhaustive-deps` existentes → `useEffectEvent` (RE-02).
4. `useMemo`/`useCallback` sin motivo, o falta de ellos donde una identidad estable sí importa (RE-08).
5. Valores arbitrarios repetidos en Tailwind → token; listas de clases repetidas → constante o componente (TW-02, TW-04).
6. Restricción que podría ser `Field(...)` en vez de validador (PD-02); modelos de entrada/vista mezclados (PD-04).
7. Filas por posición en código nuevo → `sqlite3.Row` (SQ-05); restricciones `CHECK`/`STRICT` en tablas nuevas (SQ-06).
8. Tests copiados → `parametrize` o fábricas (PT-02, VT-05); `time.sleep` en tests (PT-04); consultas por rol (VT-01).
9. Docstring que falta en una función pública con contrato no obvio (PY-03).
10. `assert` usado para estrechar → `if … raise` (PY-10).
11. PR que mezcla cambios no relacionados (GEN-01).
12. Exports o archivos sin uso (GEN-07).

## Fuentes principales

- Google eng-practices (revisión): <https://google.github.io/eng-practices/review/>
- React: reglas <https://react.dev/reference/rules>, hooks <https://react.dev/reference/rules/rules-of-hooks>,
  efectos <https://react.dev/learn/you-might-not-need-an-effect>, `useEffectEvent`
  <https://react.dev/reference/react/useEffectEvent>, plugin <https://react.dev/reference/eslint-plugin-react-hooks>
- Next.js 16: <https://nextjs.org/docs/app/guides/server-actions>, <https://nextjs.org/docs/app/guides/data-security>,
  <https://nextjs.org/docs/app/getting-started/cache-components>, <https://nextjs.org/docs/app/api-reference/config/eslint>
- TypeScript: <https://www.typescriptlang.org/tsconfig/>, Google TS Style <https://google.github.io/styleguide/tsguide.html>,
  typescript-eslint <https://typescript-eslint.io/rules/>
- ESLint core: <https://eslint.org/docs/latest/rules/>; SonarJS <https://github.com/SonarSource/SonarJS/blob/master/packages/jsts/src/rules/README.md>;
  complejidad cognitiva <https://www.sonarsource.com/docs/CognitiveComplexity.pdf>
- Tailwind 4: <https://tailwindcss.com/docs/theme>, <https://tailwindcss.com/docs/styling-with-utility-classes>
- Testing Library / Vitest: <https://testing-library.com/docs/guiding-principles>, <https://vitest.dev/guide/mocking>
- Python: PEP 8, 20, 257, 484, 649, 765 (<https://peps.python.org/>), Google Python Style
  <https://google.github.io/styleguide/pyguide.html>, ruff <https://docs.astral.sh/ruff/rules/>
- FastAPI <https://fastapi.tiangolo.com/>, Pydantic <https://docs.pydantic.dev/latest/>, `sqlite3`
  <https://docs.python.org/3/library/sqlite3.html>, SQLite <https://www.sqlite.org/docs.html>, pytest <https://docs.pytest.org/en/stable/>
- *Refactoring* (Fowler) <https://refactoring.com/catalog/>; olores de código <https://refactoring.guru/refactoring/smells>;
  *Clean Code* (Martin, 2008), adaptado: sus límites de longitud ("funciones de pocas líneas") y su postura sobre
  comentarios no se adoptan literalmente.
- Herramientas: jscpd <https://github.com/kucherenko/jscpd>, knip <https://knip.dev>, vulture
  <https://github.com/jendrikseipp/vulture>, radon <https://radon.readthedocs.io/>, xenon <https://github.com/rubik/xenon>

Verificado en esta sesión: versiones instaladas (Next 16.4.6, React 19.3.0, ESLint 9.39.5, TS 5.9.3,
eslint-plugin-react-hooks 7.1.1 con las reglas del compilador en `recommended`), configuración de `eslint-config-next`
y las guías locales de Next en `node_modules/next/dist/docs/`. Las URL de documentación son las canónicas conocidas;
no se han abierto una a una por el cambio de alcance (conviene validar enlaces antes de publicar el documento).
