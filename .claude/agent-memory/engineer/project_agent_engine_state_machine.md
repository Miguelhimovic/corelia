---
name: project-agent-engine-state-machine
description: Diseno de la state machine formal (Tarea 4, SPEC.md sec 2) — StateEvent vs LeadIntent, funcion pura transition(), automatic transitions, y que le falta resolver a Tarea 5
metadata:
  type: project
---

Fase 2, Tarea 4 (state machine formal, SPEC.md secciones 1-2) implementada en
`app/agent_engine/state_machine.py`. Re-exportada desde `app/agent_engine/__init__.py`
junto con [[project-agent-engine-classifier]] y [[project-agent-engine-llm-extraction]].

**Diseno clave:**
- `StateEvent` (StrEnum) es DISTINTO de `LeadIntent`: `LeadIntent` es lo que devuelve
  el classifier/LLM sobre un mensaje aislado; `StateEvent` es lo que consume la state
  machine, resuelto por el orquestador con contexto adicional (estado actual, resultado
  de tools de Calendar/catalogo que aun no existen — Fase 3).
- `transition(current_state, event, *, empty_search_count=0, no_response_count=0) -> TransitionResult`
  — funcion pura, sin I/O/DB/Claude. Devuelve `TransitionResult` (dataclass frozen) con
  `new_state`, ambos contadores actualizados, y `changed_state: bool`.
- Prioridad universal (`human_request` -> HANDOFF, `not_interested` -> LOST) se evalua
  ANTES que cualquier logica de estado, desde cualquier `current_state`, incluyendo
  estados terminales como HANDOFF/LOST/BOOKED — se aplico literal ("en cualquier punto").
- `QUALIFYING -> PROPERTY_SEARCH` es la UNICA transicion automatica: se modela aparte,
  en `apply_automatic_transitions(state) -> LeadStage`, no como un evento mas. El
  orquestador debe llamarla inmediatamente despues de cualquier `transition()` cuyo
  `new_state` sea QUALIFYING, antes de persistir.
- Decision de diseno para `empty_search_count` (no estaba 100% literal en SPEC.md):
  la regla dice "resetea cuando el usuario cambia cualquiera de los 4 criterios de
  busqueda", pero la state machine pura no conoce entities. Se interpreto que el punto
  observable equivalente es el evento `ENOUGH_DATA` (los 4 slots vuelven a estar
  completos) y tambien `RESULTS_FOUND` (una busqueda exitosa rompe la racha de vacias):
  ambos resetean `empty_search_count` a 0. Si esto se revisa/objeta en spec-guardian o
  QA, el fix es puntual en `_EMPTY_SEARCH_RESET_EVENTS` de `state_machine.py`.
- `no_response_count` se resetea a 0 en TODA transicion que cambia de estado; si el
  evento no alcanza el umbral (2), queda incrementado y el estado no cambia
  (`changed_state=False`).
- `map_intent_to_event(intent) -> StateEvent | None` SOLO cubre el mapeo 1-a-1 sin
  ambiguedad (`human_request`, `not_interested`). Devuelve `None` para `property_search`
  (requiere validar los 4 slots + confidence>=0.7, fuera de este modulo puro), `cancel`
  (requiere saber si hay cita agendada — CANCELLATION_REQUESTED vs NOT_INTERESTED,
  SPEC.md seccion 1), y `question`/`other` (sin evento de state machine definido).
- `InvalidTransitionError(current_state, event)` se lanza para cualquier par
  `(estado, evento)` no definido en la tabla — fail-safe explicito, nunca cae a un
  estado por default en silencio.

**Why:** SPEC.md seccion 2 exige que las transiciones automaticas y las prioritarias
("*") no se confundan con transiciones normales disparadas por evento de usuario, y que
ninguna transicion no definida pase desapercibida (CLAUDE.md fail-safe). Separar
`StateEvent` de `LeadIntent` evita que la logica de negocio (cuando SI hay `enough_data`,
o si `cancel` implica cita agendada) se filtre dentro del modulo puro de la state machine.

**How to apply (Tarea 5, orquestador):** flujo esperado por turno:
1. `classify_deterministic(msg)` -> si None, `await extract_with_llm(msg)` (capturar
   `LLMExtractionFailed` -> handoff, ver [[project-agent-engine-llm-extraction]]).
2. Resolver `StateEvent` a partir del `ExtractionResult` + estado actual + contexto de
   tools: usar `map_intent_to_event()` para el caso simple; resolver a mano
   `enough_data` (los 4 slots completos con confidence>=0.7), `cancel` ambiguo, y los
   eventos que dependen de tools (`results_found/empty`, `meeting_confirmed`,
   `calendar_error`, `user_selects_property`, `wants_visit`, `cancellation_requested`).
3. Llamar `transition(current_state, event, empty_search_count=..., no_response_count=...)`
   leyendo los contadores de `ConversationState`.
4. Si `result.new_state == QUALIFYING`, llamar `apply_automatic_transitions()` antes de
   persistir el estado final del turno.
5. Persistir `ConversationState` con el estado final + contadores devueltos +
   `last_transition_at` actualizado si `changed_state=True`.

Tests de este modulo (todas las transiciones de la tabla, contadores, prioridad
universal, `InvalidTransitionError`) son responsabilidad de un turno separado de
test-writer — no se escribieron en esta tarea. Verificado manualmente (happy path
completo, 2 busquedas vacias -> HANDOFF, 2 no-respuestas -> NURTURE, prioridad
universal, transiciones invalidas) + `ruff check` limpio + `pytest tests/ -q` en verde
(4 tests preexistentes, ninguno cubre este modulo todavia).
