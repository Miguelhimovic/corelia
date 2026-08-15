---
name: project-fase3-handoff-human
description: handoff_human() en app/tools/handoff_human.py (Fase 3, Tarea 5) — unica tool que puede tocar Lead.stage directamente, log de exito a nivel WARNING como notificacion MVP
metadata:
  type: project
---

Implementado en `app/tools/handoff_human.py`, `app/tools/schemas.py`
(`HandoffHumanInput`, `extra="forbid"`), `app/tools/__init__.py` (export).
Contrato: SPEC.md seccion 4 (handoff_human) + seccion 7 (flujo de Human
Handoff). Reusa `LeadNotFoundError`/`LeadPersistenceError` de
[[project-fase3-tools-create-update-lead]].

**Decisiones no obvias:**
- Es la UNICA tool con permiso explicito de escribir `Lead.stage`
  directamente — excepcion deliberada a la regla de `update_lead()`
  (`extra="forbid"` rechaza `stage`/`score`). `handoff_human()` ES la
  implementacion de las transiciones `* -> HANDOFF` de SPEC.md seccion 2, no
  un atajo alrededor de ellas.
- El log de exito se emite en `logger.warning(...)`, no `.info(...)` como el
  resto de tools — porque en MVP ese log ES la "notificacion" de SPEC.md
  seccion 7 (no hay email/Slack real todavia), no solo un registro de
  auditoria.
- El log de exito NO incluye `summary` (solo `reason`, que debe ser texto
  corto categorico tipo `"human_request"`/`"calendar_error"`): `summary`
  puede traer datos personales del lead, y SPEC.md seccion 8 prohibe
  informacion sensible en logs ("usar IDs"). `summary` solo se persiste en
  la columna `HumanHandoff.summary`.
- La funcion NO compone el `summary` rico que describe SPEC.md seccion 7
  (historial, propiedades vistas, etc.) — recibe `summary` ya armado de
  quien la llama (el orquestador, Tarea 6, que tiene visibilidad del turno
  completo). Mismo principio que create_lead/update_lead: la tool no va a
  buscar contexto por su cuenta.
- Retorna `UUID` (`handoff.id`) plano, no un dataclass ampliado como
  `CreateLeadResult` — a diferencia de `create_lead()`, no hay necesidad
  identificada de que el llamador necesite mas que el `handoff_id` en este
  punto del sprint.
- Se agrego `conversation_id: UUID | None = None` como kwarg opcional (solo
  logging, no se persiste) para que el orquestador pueda enriquecer los logs
  cuando lo llame — mismo patron que `request_id` en el resto de tools.

Smoke test manual en el scratchpad de la sesion (no commiteado, mismo patron
que Tarea 3): caso exitoso verifica `HumanHandoff.status=open`,
`assigned_to=None`, `Lead.stage=HANDOFF`; caso `lead_id` inexistente verifica
`LeadNotFoundError`. Ambos con `db.rollback()` despues para no dejar basura
en la DB local. `pytest tests/ -q` corrido ANTES del smoke test (201 passed)
por [[gotcha-pytest-drops-dev-db-tables]] — se recompuso el schema con
`alembic stamp base && alembic upgrade head` y se resembro
`scripts/seed_properties.py` despues, como documenta esa memoria.
