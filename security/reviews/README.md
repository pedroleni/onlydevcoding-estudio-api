# Historial de revisiones de seguridad

Guarda aquí cada auditoría completa, no los chequeos puntuales de una tarea.

## Convención

- Nombre: `YYYY-MM-DD-<tema-corto>.md`.
- Incluye resumen ejecutivo, risk score, hallazgos por severidad, prioridad de
  remediación y una sección final **Estado**.
- Cada hallazgo pendiente empieza con `- [ ]`; al resolverlo se marca con
  `- [x]` y la referencia al commit o PR.
- No reescribas el resultado histórico. Documenta después los falsos positivos
  o cambios de estado.
- Añade una fila al índice por cada auditoría.

## Índice

| Fecha | Archivo | Alcance | Resultado |
|---|---|---|---|
| 2026-11-16 | [2026-11-16-fase-1.md](2026-11-16-fase-1.md) | Rama `feat/fase-1` completa (`6d3421d..HEAD`), ocho dominios | MEDIO, score 13: 0 CRITICAL, 0 HIGH, 3 MEDIUM, 4 LOW, 3 INFO |
| 2026-11-17 | [2026-11-17-tarea-4-publicar.md](2026-11-17-tarea-4-publicar.md) | Cambios de la Tarea 4 de fase 2, ocho dominios | Sin hallazgos, score 0 |
