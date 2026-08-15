---
name: feedback-doc-drift-en-cambios-infra
description: Patrón de rechazo — cambios de infraestructura (puertos, credenciales, servicios) bien documentados en el archivo que se toca pero no propagados a CLAUDE.md/SPEC.md
metadata:
  type: feedback
---

Cuando un cambio de infraestructura (ej. puerto de Postgres) se implementa, el código y los comentarios inline suelen quedar excelentemente documentados (docker-compose.yml, .env.example, .env con comentarios claros explicando el "por qué"), pero **CLAUDE.md no se actualiza en el mismo commit/sesión**, dejando la sección "Comandos" con información obsoleta (ej. seguía diciendo puerto 5433 cuando el real ya era 5544, y seguía describiendo un bloqueo de Docker Desktop ya resuelto).

**Por qué importa:** SPEC.md sección 10 (Definition of Done), ítem 8, exige explícitamente "Actualización de este archivo [SPEC.md] o de CLAUDE.md si cambia un contrato". El puerto documentado en CLAUDE.md es justamente el tipo de dato operativo que, si queda desactualizado, reproduce el mismo bug de horas perdidas por confusión de puertos que originó el cambio.

**Cómo aplicar:** al revisar cualquier cambio de infraestructura/entorno local, buscar explícitamente referencias cruzadas en CLAUDE.md (sección "Comandos" y notas de "Día N") y BITACORA.md antes de aprobar. Si el código está bien pero la documentación operativa no se tocó, es motivo de RECHAZO parcial de esa pieza específica, no del resto del trabajo. Ver caso concreto en [[project-port-conflict]].

Primera vez detectado: revisión Día 1-2, 2026-08-14 (cambio de puerto 5433→5544 en docker-compose.yml/.env.example sin actualizar CLAUDE.md ni app/config.py default).

**Tercera vez detectado (patrón ya recurrente — señalar explícitamente en próximas revisiones): revisión Fase 3 (tools + handle_message), 2026-08-14.** `engineer` documentó correctamente en su propia memoria de agente (`.claude/agent-memory/engineer/gotcha_pytest_drops_dev_db_tables.md`) que `pytest tests/ -q` ejecuta `Base.metadata.drop_all()` contra la MISMA `DATABASE_URL` de desarrollo local (`tests/conftest.py`, fixture `engine`), borrando el tenant fijo y cualquier seed (catálogo demo de `scripts/seed_properties.py`) al terminar la sesión de tests. Esa nota nunca se propagó a `CLAUDE.md` sección "Comandos" > Tests, que sigue sin advertir del `drop_all` — mismo patrón exacto que el caso original de puertos: la memoria interna de un agente no sustituye la documentación operativa compartida. No bloqueante por sí solo (comportamiento pre-existente de Fase 1, no introducido en esta fase), pero exigir la línea en CLAUDE.md antes de aprobar del todo, para que nadie pierda el catálogo de demo la noche antes de una demo comercial.

**RESUELTO 2026-08-14 (segunda pasada QA, mismo día).** `CLAUDE.md` sección "Comandos" > línea de
Tests ahora incluye la advertencia completa (drop_all/create_all contra la DB de desarrollo +
instrucciones de recuperación `alembic stamp base && alembic upgrade head` + `python
scripts/seed_properties.py`). Verificado leyendo el texto exacto en `CLAUDE.md` línea 63. Tercera
instancia del patrón, tercera vez que se corrige por completo cuando se señala con precisión — seguir
exigiendo esa precisión en cada rechazo futuro.
