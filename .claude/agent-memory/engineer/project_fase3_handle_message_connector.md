---
name: project-fase3-handle-message-connector
description: Fase 3 Tarea 6 (ultima) — handle_message() en orchestrator.py conecta las 4 tools a process_incoming_message; ExecutedTurnResult.final_state; gap de reachability del state machine descubierto
metadata:
  type: project
---

Implementado TODO en `app/agent_engine/orchestrator.py` (sin archivo nuevo,
por instruccion explicita de la tarea) + re-exports en
`app/agent_engine/__init__.py`. Contrato: SPEC.md secciones 1, 2, 4, 7.
Conecta [[project-fase3-tools-create-update-lead]],
[[project-fase3-search-database]] y [[project-fase3-handoff-human]] a
[[project-agent-engine-orchestrator]] (Fase 2, Tarea 5) sin modificar su
logica de negocio.

**Diseno clave:**
- `process_incoming_message()` (Fase 2) quedo INTACTA salvo un kwarg nuevo
  opcional `message_id: UUID | None = None` (default `None` = comportamiento
  identico): si se provee, reutiliza un `Message` ya persistido (por
  `create_lead()`) en vez de insertar uno duplicado. Retrocompatible al
  100% — los 201 tests de Fase 2 pasan sin tocarlos.
- Nueva funcion publica `handle_message()` (async) es el entrypoint completo
  que usaria un adaptador de canal (Fase 6, todavia no construido): si
  `conversation_id`/`lead_id` son `None`, llama `create_lead()` primero;
  siempre llama `process_incoming_message()`; si hubo entities nuevas este
  turno llama `update_lead()`; despacha la tool que corresponda segun
  `TurnResult.action` (`SEARCH_PROPERTIES`->`search_database()` + resuelve
  `results_found`/`results_empty` EN EL MISMO turno (es continuacion
  automatica del sistema, no espera nuevo mensaje) incluyendo el caso
  `empty_search_2x`->`handoff_human()`; `OFFER_HANDOFF`->`handoff_human()`;
  `MARK_LOST`->escribe `Lead.stage=LOST` directo, SIN tool porque SPEC.md
  seccion 4 no define una para esta transicion).
- `ExecutedTurnResult` (nuevo dataclass) envuelve `TurnResult` + efectos de
  tools. Campo importante: `final_state: LeadStage` — DISTINTO de
  `turn.new_state`. `turn.new_state` es el resultado de
  `process_incoming_message` ANTES de que esta capa ejecute
  `search_database()`; cuando la accion es `SEARCH_PROPERTIES`,
  `turn.new_state` siempre queda en `PROPERTY_SEARCH` (transitorio) y
  `final_state` es el real (`PRESENTING`/`DISCOVERING`/`HANDOFF`). Cualquier
  consumidor futuro (Fase 6/7) DEBE leer `final_state`, no `turn.new_state`.
- Fail-safe (SPEC.md seccion 7): `PropertySearchError`/`LeadPersistenceError`
  de cualquier tool -> `_fail_safe_handoff()` (mensaje fijo
  `"estoy teniendo problemas técnicos, un asesor te contacta"` +
  `handoff_human()`). Ese helper tambien sincroniza
  `ConversationState.current_state = HANDOFF` ademas de `Lead.stage`
  (que `handoff_human()` ya escribe) — sin esto quedaban divergentes (un
  bug real que el smoke test detecto y se corrigio en la misma tarea).
  Si `handoff_human()` mismo falla -> `ToolExecutionError` (log CRITICAL,
  no hay mas fallback). Excepcion: si `create_lead()` falla con
  `LeadPersistenceError` ANTES de que exista `lead_id`, no hay a quien
  escalar (FK obligatoria de `HumanHandoff`) — se relanza tal cual, log
  CRITICAL, decision explicita documentada en el docstring.

**Hallazgo importante para spec-guardian/QA, NO corregido en esta tarea
(fuera de alcance — tocaria state_machine.py de la Tarea 4, ya aprobada, y
sus tests):** la regla SPEC.md seccion 2 "2 busquedas vacias seguidas ->
HANDOFF" es, con el `state_machine.py` actual, PRACTICAMENTE INALCANZABLE
via conversacion real. `_EMPTY_SEARCH_RESET_EVENTS` (Tarea 4) resetea
`empty_search_count` a 0 en CADA `ENOUGH_DATA` — y la UNICA forma de que
`TurnResult.action == SEARCH_PROPERTIES` ocurra es que `ENOUGH_DATA` haya
disparado ESE MISMO turno (unico camino a `PROPERTY_SEARCH`). Consecuencia:
`_run_property_search()` (esta tarea) SIEMPRE lee `empty_search_count == 0`
de la DB en el mundo real, nunca `1` — la rama `empty_search_2x` esta
implementada correctamente (verificada con smoke test llamando
`_run_property_search()` directo con un `ConversationState` manipulado a
mano, bypaseando el gap) pero es codigo muerto en la practica. Recomendacion
para revision: `_EMPTY_SEARCH_RESET_EVENTS` en `state_machine.py` quizas
deberia excluir `ENOUGH_DATA` (dejar solo `RESULTS_FOUND` como reset), pero
esto rompe `test_t2_enough_data_resets_empty_search_count`
(`tests/agent_engine/test_state_machine.py`) que ya esta aprobado — requiere
decision explicita de spec-guardian/QA, no un fix silencioso de engineer.

**Otras decisiones:**
- Import de las tools con alias (`tool_create_lead`, `tool_update_lead`,
  `tool_search_database`, `tool_handoff_human`) para dejar explicito en cada
  call site que es una tool real de Fase 3 (aunque no habia colision de
  nombres con el modulo `orchestrator.py`).
- `update_lead()` se llama SOLO si `turn.extraction.entities` (las NUEVAS de
  este mensaje, no las fusionadas) tiene al menos un campo no-null — evita
  un write sin cambios en mensajes tipo "quiero hablar con un asesor" que no
  traen slots.
- `_compose_handoff_summary()`: resumen simple (ultimo mensaje + intent +
  confidence + slots conocidos + transicion de estado), sin reconstruir
  historial completo — instruccion explicita del enunciado de la tarea
  ("un resumen simple y honesto es aceptable en MVP").
- No se implementaron `get_availability`/`book_meeting`/`cancel_meeting`
  (Fase 5) — los estados SCHEDULING/BOOKED siguen sin `OrchestratorAction`
  propio (`ACKNOWLEDGE` por default), sin cambios.

**Verificacion:** `pytest tests/ -q` 201 passed (sin tests nuevos — Fase 3
Tareas 3-6 de tools/orquestador NO tienen tests formales todavia, son
responsabilidad de test-writer en un turno separado, ver
`tests/tools/` inexistente al cierre de esta tarea). `ruff check` limpio en
`orchestrator.py`/`__init__.py`/`app/tools/`. Smoke test manual (scratchpad,
no commiteado) con 6 escenarios contra Postgres real (puerto 5544): full
slots con resultados -> PRESENTING; 1ra busqueda vacia -> DISCOVERING sin
handoff; 2da busqueda vacia (simulada, ver hallazgo arriba) -> HANDOFF +
`ConversationState`/`Lead.stage` sincronizados; human_request -> OFFER_HANDOFF;
not_interested -> MARK_LOST; primer mensaje no se duplica
(`create_lead()` + `process_incoming_message(message_id=...)` = 1 sola fila
en `messages`). Aplico otra vez [[gotcha-pytest-drops-dev-db-tables]]:
`alembic stamp base && alembic upgrade head` + `scripts/seed_properties.py`
despues de cada corrida de pytest.
