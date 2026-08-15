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
