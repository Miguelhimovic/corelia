---
name: project-fase3-tools-create-update-lead
description: create_lead()/update_lead() en app/tools/ (Fase 3, Tarea 3) — contrato ampliado de create_lead, dominio de campos de update_lead via Pydantic extra=forbid
metadata:
  type: project
---

Implementado en `app/tools/create_lead.py`, `app/tools/update_lead.py`,
`app/tools/schemas.py` (Pydantic input/output), `app/tools/errors.py`
(`ToolError`, `LeadNotFoundError`, `LeadPersistenceError`). Contrato base:
SPEC.md seccion 4 (Tool Contracts) + precisiones cerradas en seccion 5.

**Decisiones no obvias:**
- `create_lead()` devuelve `CreateLeadResult` (dataclass: `lead_id`,
  `conversation_id`, `message_id`), no solo `LeadID` como dice el literal de
  SPEC.md seccion 4 — porque la Tarea 3 exige crear `Conversation` + primer
  `Message` en la misma llamada. Se documenta como ampliacion del contrato
  (no un incumplimiento), motivada porque quien la conecte al orquestador
  (Fase 3, Tarea 6 pendiente) va a necesitar `conversation_id` para llamar
  `process_incoming_message()` sin tener que volver a consultar la DB.
- `update_lead()` valida `fields` con `UpdateLeadFields` (Pydantic,
  `extra="forbid"`): `stage`/`score` quedan fuera del modelo a proposito, asi
  que Pydantic los rechaza con `ValidationError` igual que cualquier otro
  campo desconocido — sin necesidad de una lista aparte de campos
  prohibidos. Decision explicita del enunciado de la tarea: "rechazar con
  error de validacion es mas seguro que ignorar en silencio".
- `UpdateLeadFields` SI incluye `bedrooms`/`purpose` aunque el enunciado de
  la Tarea 3 los omitio de su lista en prosa (esa lista copia el field-list
  original de CLAUDE.md "Modelo de datos (Fase 1)", previo a que
  `bedrooms`/`purpose` se agregaran al modelo `Lead` en SPEC.md seccion 1).
  El propio contrato dice en la misma frase "entities del LLM pasan por el
  contrato de la seccion 3 antes de llegar aqui" — esas entities son
  exactamente `location/budget_max/bedrooms/purpose`, y
  `orchestrator.TurnResult.merged_entities` (Fase 2, Tarea 5) ya expone los 4
  para que el llamador se los pase a `update_lead()`. Sin esto, 2 de los 4
  slots nunca podrian persistirse via esta tool.
- Actualizacion parcial real: `UpdateLeadFields.model_dump(exclude_unset=True)`
  — Pydantic v2 distingue "clave ausente en `fields`" de "clave presente con
  valor `None`" segun si vino en el input, no segun el default del modelo.
- `create_lead()` NO crea `ConversationState`: el orquestador
  (`_get_or_create_conversation_state`, Fase 2 Tarea 5) ya la crea
  perezosamente con sus defaults la primera vez que procesa un turno de esa
  `Conversation` — el propio comentario de esa funcion ya anticipaba este
  caso, asi que duplicar la creacion aqui arriesgaria divergencia de
  defaults entre los dos lugares.
- Validacion de `phone`: regex E.164-ish (`^\+?[0-9]{7,15}$`), sin libreria
  nueva — SPEC.md solo exige que un telefono invalido levante error de
  validacion, no un formato exacto.

Ver tambien [[gotcha-pytest-drops-dev-db-tables]] (se aplico el flujo de
recuperacion documentado ahi: reinsertar tenant fijo + `scripts/seed_properties.py`
despues de correr pytest y el smoke test manual). Smoke test propio (no
formal) se corrio en un script temporal en el scratchpad de la sesion, no
quedo commiteado — los tests formales son responsabilidad de test-writer en
un turno separado.
