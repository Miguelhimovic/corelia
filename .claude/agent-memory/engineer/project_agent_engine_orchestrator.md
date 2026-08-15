---
name: project-agent-engine-orchestrator
description: Diseno del orquestador del turno (Tarea 5, Fase 2) — como resuelve el mapeo intent->evento pendiente de la Tarea 4, que senala como "requires handoff"/"requires clarification", y que le falta a Fase 3
metadata:
  type: project
---

Fase 2, Tarea 5 (orquestador del turno, ultima de la fase) implementada en
`app/agent_engine/orchestrator.py`. Re-exportada desde `app/agent_engine/__init__.py`
junto con [[project-agent-engine-classifier]], [[project-agent-engine-llm-extraction]]
y [[project-agent-engine-state-machine]].

**Entry point:** `async def process_incoming_message(db: Session, *, conversation_id,
lead_id, message, llm_client=None) -> TurnResult`. Asume Lead/Conversation ya existen
(create_lead es Fase 3) — valida su existencia y lanza `ConversationNotFoundError` /
`LeadNotFoundError` / `LeadConversationMismatchError` en vez de asumir en silencio.

**Diseno clave:**
- Es `async` porque `extract_with_llm` lo es, pero usa `Session` SYNC de SQLAlchemy
  (mismo patron que `app/database.get_db` — no hay engine async en el proyecto todavia).
  No hace `db.commit()`, solo `db.flush()` — la transaccion es responsabilidad del
  llamador (no hay un patron de commit establecido en el resto del codebase todavia,
  ver `app/api/health.py`).
- `LLMExtractionFailed` se captura y se trata EXACTAMENTE como si el intent hubiera sido
  `human_request` (evento universal `StateEvent.HUMAN_REQUEST`, valido desde cualquier
  estado) con `handoff_reason="llm_extraction_failed"` — no hay un evento de state machine
  separado para "la API de Claude fallo", se reutiliza el mismo mecanismo de HANDOFF.
- Mapeo intent->evento pendiente de la Tarea 4 (`_resolve_turn`), resuelto asi:
  - `property_search`: solo dispara `ENOUGH_DATA` si `current_state == DISCOVERING` y los
    4 slots FUSIONADOS (ver abajo) estan completos con `confidence >= 0.7`. Si intent es
    `property_search` en un estado posterior a DISCOVERING (PROPERTY_SEARCH, PRESENTING,
    SCHEDULING, BOOKED, HANDOFF, LOST) — SPEC.md no define transicion ahi — se trata como
    no-op (`ACKNOWLEDGE`, sin transicion), decision de diseno de esta tarea.
  - `cancel`: `CANCELLATION_REQUESTED` solo si `current_state == BOOKED`; si no,
    se trata igual que `question`/`other` (ver abajo) — instruccion literal del prompt de
    la tarea, no la lectura mas obvia de SPEC.md seccion 1 (que sugeria LOST/"ya no me
    interesa" para cancel sin cita — se descarto a favor de la instruccion explicita).
  - `question`/`other` (sin FAQ en MVP) y `cancel` sin cita agendada: TODOS reutilizan el
    evento universal `StateEvent.HUMAN_REQUEST` (valido desde cualquier estado, sin riesgo
    de `InvalidTransitionError`) en vez de inventar un `StateEvent` nuevo que SPEC.md
    seccion 2 no define. El campo `handoff_reason` (string libre, no enum) es lo que
    diferencia el motivo real: `"unanswered_question_no_faq"`, `"cancel_without_scheduled_meeting"`,
    `"human_request_explicit"`, `"cancellation_with_meeting_booked"`, `"llm_extraction_failed"`.
  - `requires_clarification=True` (del contrato seccion 3): NO dispara ningun evento —
    accion `ASK_CLARIFICATION`, la state machine no avanza ese turno. Se evalua DESPUES de
    human_request/not_interested (esos tienen prioridad maxima sin importar clarification).
- **Bootstrap NEW_MESSAGE:** si `current_state` es NEW o NURTURE y el intent NO es
  universal (human_request/not_interested), se aplica primero `transition(state, NEW_MESSAGE)`
  ANTES de resolver el evento sustantivo — asi un primer mensaje con los 4 slots completos
  avanza NEW->DISCOVERING->QUALIFYING->(auto)PROPERTY_SEARCH en UN SOLO turno (confirmado con
  smoke test manual, coincide con el golden conversation de SPEC.md seccion 9 que espera
  `state_after: QUALIFYING` en un solo input). Si el intent SI es universal, se salta el
  bootstrap y va directo a HANDOFF/LOST desde NEW (prioridad maxima, "antes que cualquier
  otra logica", literal de SPEC.md seccion 1).
- **Fusion de entities:** `_merge_entities(lead, new_entities)` NO escribe en el `Lead` —
  el orquestador NO llama `update_lead` (es tool de Fase 3). Solo lee `lead.location/
  budget_max/bedrooms/purpose` ya guardados y los fusiona con los del mensaje actual (sin
  pisar con null un campo ya conocido) para decidir `ENOUGH_DATA` este turno. El resultado
  fusionado se expone en `TurnResult.merged_entities` para que el llamador (Fase 3) se lo
  pase a `update_lead` despues. Verificado con smoke test de dos turnos: turno 1 solo trae
  `location`, `merged_entities.location="Pinares"` con el resto null -> accion
  `REQUEST_MORE_INFO`, estado se queda en DISCOVERING; simulando que Fase 3 ya persistio
  ese location en el Lead, turno 2 solo trae budget/bedrooms/purpose -> merge recupera
  location del Lead -> `ENOUGH_DATA` -> PROPERTY_SEARCH.
- `TurnResult.action` (`OrchestratorAction` enum: `ASK_CLARIFICATION`, `REQUEST_MORE_INFO`,
  `SEARCH_PROPERTIES`, `OFFER_HANDOFF`, `MARK_LOST`, `ACKNOWLEDGE`) se deriva, cuando SI hubo
  evento, del `new_state` final post-transicion (tabla `_ACTION_BY_STATE`), NO de que evento
  se disparo — evita duplicar/desalinear la logica de mapeo evento->accion.
- Nunca captura `InvalidTransitionError` de `state_machine.transition()`: por diseno,
  `_resolve_turn` solo devuelve eventos que son validos para el `current_state` en el que
  se evaluan (ENOUGH_DATA solo si DISCOVERING, CANCELLATION_REQUESTED solo si BOOKED, el
  resto son universales) — si esa excepcion llegara a levantarse seria un bug real del
  orquestador, no un caso de negocio a atrapar (mismo criterio que el docstring de
  `InvalidTransitionError` en state_machine.py).

**Why:** SPEC.md seccion 7 exige fail-safe explicito (nunca inventar transiciones ni
tragarse errores en silencio) y seccion 1 exige que TODA pregunta fuera de flujo ofrezca
handoff. Reutilizar `StateEvent.HUMAN_REQUEST` para los casos "sin FAQ"/"cancel sin cita"/
"LLM fallo" evita inventar StateEvents no definidos en SPEC.md seccion 2 mientras se
preserva la distincion semantica via `handoff_reason` (string), que es justo el shape que
pide `handoff_human(lead_id, reason, summary)` en SPEC.md seccion 4.

**How to apply (Fase 3, tools):** el llamador de `process_incoming_message` debe:
1. Si `action == SEARCH_PROPERTIES`: llamar `search_database(**turn_result.merged_entities)`.
2. Si `action == OFFER_HANDOFF`: llamar `handoff_human(lead_id, reason=turn_result.handoff_reason, summary=...)`.
3. Si `action in (ASK_CLARIFICATION, REQUEST_MORE_INFO)`: generar el mensaje de vuelta pidiendo
   el/los slot(s) faltantes (esto NO esta implementado — no hay generacion de texto en Fase 2).
4. En cualquier caso donde `merged_entities` tenga datos nuevos, llamar `update_lead(lead_id, fields=...)`
   con los valores de `turn_result.merged_entities` (el orquestador NO lo hizo).
Tests de este modulo (golden conversations completas, `LLMExtractionFailed`->handoff,
merge entre turnos, InvalidTransitionError realmente inalcanzable) son responsabilidad de
un turno separado de test-writer — no se escribieron en esta tarea. Verificado manualmente
con `db_session` real contra Postgres local (puerto 5544) + `AsyncAnthropic` mockeado: 5
golden-conversation-like scenarios (full info primer mensaje -> PROPERTY_SEARCH en un
turno, human_request -> HANDOFF, question sin FAQ -> HANDOFF, slots incompletos en dos
turnos -> PROPERTY_SEARCH, LLM extraction failure -> HANDOFF) + caso `requires_clarification`
(NEW->DISCOVERING bootstrap ocurre igual, pero sin avanzar mas) + `ruff check`/`ruff format --check`
limpios en `orchestrator.py` + `pytest tests/ -q` en verde (4 tests preexistentes, ninguno
cubre este modulo todavia — nota: `state_machine.py` (Tarea 4, no tocado en esta tarea)
SI tiene 2 lineas que `ruff format` marcaria, preexistente, no corregido aqui por no ser
parte del alcance).

**Bug encontrado por test-writer + fix (turno posterior a la implementacion inicial):**
el `try/except SQLAlchemyError` original SOLO envolvia el `db.flush()` final. Las lecturas
previas en la misma funcion (`db.get(Conversation, ...)`, `db.get(Lead, ...)`, y el
`db.execute(select(ConversationState)...)` dentro de `_get_or_create_conversation_state`)
NO estaban cubiertas, y el autoflush de SQLAlchemy puede disparar un flush durante
cualquiera de esas lecturas tambien — un fallo de Postgres ahi se propagaba como
`SQLAlchemyError` crudo en vez de `OrchestratorPersistenceError`, violando SPEC.md
seccion 7. Fix: un UNICO bloque `try/except SQLAlchemyError` (no varios) que envuelve
TODA la logica del turno, desde `db.get(Conversation, ...)` hasta el `db.flush()` final
— incluye de paso la logica de negocio pura que queda en medio (extraccion, `_resolve_turn`,
`transition()`), que nunca dispara ese except pero no vale la pena partir en dos bloques
solo para excluirla. El test `TestPersistenceFailure` en
`tests/agent_engine/test_orchestrator.py` tenia un workaround documentado
(`db_session.autoflush = False`) para poder ejercitar el path del flush final sin
tropezar con el autoflush temprano no cubierto — **resuelto en el ciclo de fixes de QA
(ver [[gotcha-qa-rechazo-dod-fase2]])**: se quito esa linea y se corrigio el comentario,
el test sigue verificando lo mismo (`SQLAlchemyError` en cualquier punto del turno ->
`OrchestratorPersistenceError` + rollback) pero ahora ejercita el path real sin workaround.

**Fixes de cierre QA (ver [[gotcha-qa-rechazo-dod-fase2]] para el detalle completo de los 5):**
`request_id` (UUID por turno, generado aqui mismo, pasado a `extract_with_llm`) agregado a
todos los `logger.*` de este modulo y de `llm_extraction.py`; el caso "`cancel` sin cita
agendada -> HANDOFF" (no LOST) quedo reflejado en SPEC.md seccion 1 (bullet nuevo) y en el
docstring de `map_intent_to_event()` en `state_machine.py`, que antes decia lo contrario.
