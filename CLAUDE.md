# CLAUDE.md

Las instrucciones del proyecto viven en [AGENTS.md](AGENTS.md). Léelas y
aplícalas también desde Claude Code.

## Auditoría de seguridad

Usa `/security-review` para una auditoría completa de los ocho dominios:
entorno del agente, secretos, vulnerabilidades de código, cadena de suministro,
inyección, API local, infraestructura y prompt injection.

Todos los agentes leen primero `security/security-review-instructions.md`.
Para un área concreta, indica el alcance, por ejemplo
`/security-review solo API local` o `/security-review solo secretos`.

