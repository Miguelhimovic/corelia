---
name: project-fase3-empty-search-criteria-reset-fix
description: Fix post-QA de empty_search_count -- transition() ya no resetea en ENOUGH_DATA, el orquestador decide el reset comparando Lead pre-update vs merged_entities
metadata:
  type: project
---

**Bug corregido (2026-08-14):** `state_machine.transition()` (funcion pura,
`app/agent_engine/state_machine.py`) reseteaba `empty_search_count` a 0 en
CUALQUIER evento `ENOUGH_DATA`, sin importar si el usuario habia cambiado
alguno de los 4 criterios de busqueda (location/budget_max/bedrooms/
purpose). Como cada reintento de busqueda pasa siempre por
`DISCOVERING -> QUALIFYING` via `ENOUGH_DATA` (los 4 slots vuelven a estar
completos aunque sean identicos a los anteriores), esto dejaba la rama
`PROPERTY_SEARCH -> HANDOFF : results_empty (2da consecutiva)` (SPEC.md
seccion 2) inalcanzable desde una conversacion real via `handle_message()`
-- solo se podia ejercitar llamando `_run_property_search()` directamente
con el contador manipulado a mano (asi lo dejo documentado test-writer en su
turno anterior, en `TestUnreachableSecondEmptySearchBranch`).

**Fix:** `_EMPTY_SEARCH_RESET_EVENTS` en `state_machine.py` ya SOLO contiene
`StateEvent.RESULTS_FOUND` (una busqueda exitosa si cierra el intento sin
ambiguedad). `transition()` (funcion pura, sin acceso a los slots
anteriores) ya NO decide el reset por cambio de criterio -- esa decision se
movio al orquestador (`app/agent_engine/orchestrator.py`,
`_run_property_search(criteria_changed: bool = True)`), que compara los 4
slots via `ExtractedEntities.__eq__` (Pydantic, comparacion field-wise
gratis) contra lo que el `Lead` tenia persistido ANTES de que `update_lead()`
lo sobreescribiera ese turno. `handle_message()` es el UNICO punto que lee
`_lead_search_slots(lead)` pre-update (variable `previous_search_slots`) y
pasa `criteria_changed` explicitamente a traves de `_dispatch_action()` ->
`_run_property_search()`. Si `criteria_changed=True`, el intento arranca con
`empty_search_count=0` como argumento de ENTRADA a `transition()` (no se
persiste 0 directo en `ConversationState`, se le pasa como parametro --
`transition()` sigue siendo pura).

**Gotcha para la proxima vez que se toque esta zona:** no confundir
`state_machine.py` (funcion pura, nunca debe necesitar saber "cual era el
criterio anterior") con `orchestrator.py` (unico lugar con acceso al `Lead`
persistido). Si aparece otra logica de "resetear un contador segun si algo
cambio respecto al turno anterior", el patron correcto es capturar el valor
previo ANTES de la escritura del tool correspondiente (aqui, antes de
`tool_update_lead()`) y pasarlo como parametro explicito hacia abajo, nunca
intentar que la funcion pura de la state machine lo infiera.

Ver tambien [[gotcha-pytest-drops-dev-db-tables]] (bloqueo no relacionado
que aparecio corriendo pytest en este mismo ciclo) y
[[project-fase3-handle-message-connector]] (arquitectura general de
`handle_message()`/`_dispatch_action()`/`_run_property_search()`).
