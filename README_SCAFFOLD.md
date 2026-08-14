# Scaffold de flujo multi-agente (Spec-Driven Development)

Copiar esta carpeta completa a la raíz del repo el Día 1, junto a `BITACORA.md`, `CLAUDE.md`, `SPEC.md` y `MARCA.md`.

## Qué incluye

- `.claude/agents/` — 5 subagentes con roles separados: `spec-guardian` (verifica contrato), `engineer` (implementa), `test-writer` (escribe tests, agente distinto del que implementó), `qa-reviewer` (aprueba o rechaza contra SPEC.md), `deployer` (despliega solo si QA aprobó).
- `.claude/skills/spec-task/SKILL.md` — el flujo que encadena los 5 subagentes en orden. Se activa solo o con `/spec-task`.
- `.claude/settings.json` + `scripts/test_on_change.sh` — hook que corre pytest automáticamente cada vez que se edita `agent_engine`, `rag` o `tools`, y le devuelve los fallos a Claude para que los corrija antes de reportar algo como terminado.
- `.github/workflows/test.yml` — CI mínimo: corre los tests en cada push. Esto es la versión barata de "CI/CD formal" que se había pospuesto en `CLAUDE.md` — vale la pena tenerla desde ya porque cuesta casi nada y es exactamente lo que reduce bugs llegando a producción; la versión pesada (deploy automatizado, observabilidad) sigue pospuesta.

## Cómo se usa en la práctica

En vez de pedirle a Claude Code "implementa el state machine de Real Estate" directamente, pide:

```
Usa el flujo spec-task para implementar el state machine de Real Estate (SPEC.md sección 2)
```

Eso dispara: verificación de contrato → descomposición en tareas → implementación → tests → QA. Si QA rechaza, vuelve a implementación con la lista exacta de lo que falta, en vez de que tú tengas que notar el problema en producción.

## Nota sobre costos

`scripts/test_on_change.sh` requiere `jq` instalado (`apt install jq` / `brew install jq`) y que `pytest` corra desde la raíz del repo — ajustar el path si la estructura final difiere.

Los 5 subagentes corren en la misma sesión, sin costo adicional de "equipo" — no es lo mismo que Agent Teams (que sí multiplica el consumo de tokens). Si más adelante quieres paralelismo real entre agentes que se envían mensajes entre sí, esa es la puerta a Agent Teams — pero es una decisión aparte, no la base de este flujo.
