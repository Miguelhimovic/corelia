---
name: project-empty-search-handoff-unreachable
description: RESUELTO 2026-08-14 -- la rama PROPERTY_SEARCH -> HANDOFF tras 2 busquedas vacias consecutivas ya es alcanzable end-to-end via handle_message(); ver fix e historial de deteccion abajo
metadata:
  type: project
---

Detectado en la revision de Fase 3 (tools + `handle_message()`), 2026-08-14. Rechazado explicitamente
por este motivo -- ver tambien [[feedback-ambiguedades-resueltas-en-codigo-no-vuelven-a-spec]].

**Causa raiz:** `_EMPTY_SEARCH_RESET_EVENTS` en `app/agent_engine/state_machine.py` (Fase 2, ya
aprobado en su momento) resetea `ConversationState.empty_search_count` a 0 en CUALQUIER evento
`ENOUGH_DATA`, sin comprobar si el usuario realmente cambio algun criterio de busqueda (SPEC.md
seccion 1 exige el reset solo "en cuanto el usuario cambia cualquiera de los 4 criterios de
busqueda"). En la practica, cuando `PROPERTY_SEARCH -> DISCOVERING` deja los 4 slots todavia
completos (el usuario no corrigio nada, o el sistema simplemente vuelve a preguntar), el turno
siguiente dispara `ENOUGH_DATA` de nuevo -> reset a 0 -> nunca se acumulan 2 `results_empty`
seguidos. Confirmado leyendo `state_machine.py` + `orchestrator._resolve_turn()` +
`orchestrator._run_property_search()` juntos, no solo uno.

**Evidencia de que el equipo ya lo sabia:** `tests/agent_engine/test_handle_message.py` tiene una
clase `TestUnreachableSecondEmptySearchBranch` que ejercita `_run_property_search()` llamandola
DIRECTAMENTE con el contador manipulado a mano, con un docstring que admite explicitamente que la
rama "es HOY inalcanzable desde una conversacion real via handle_message()". No hay ningun golden
conversation end-to-end (2 turnos reales) que la cubra.

**Por que bloquea (no es deuda tecnica aceptable):** viola SPEC.md seccion 2 (transicion
documentada e inejecutable), seccion 9 (exige golden conversations reales por rama, no solo tests
unitarios de una funcion privada) y seccion 11 ("hace handoff" -- este camino especifico nunca se
dispara). Ademas el propio docstring de `handle_message()`/`_run_property_search()` afirma haber
implementado este caso end-to-end ("Incluye el caso... disparando handoff_human() en ese mismo
turno") -- afirmacion falsa en la practica.

**Fix recomendado (para cuando se re-abra esta tarea):** `empty_search_count` no deberia resetear
en cualquier `ENOUGH_DATA`, sino solo cuando `merged_entities` realmente cambio respecto al ultimo
intento de busqueda -- requiere pasarle al state machine o al orquestador los criterios de la
busqueda anterior para comparar, y necesariamente reemplazar el test de Fase 2
`test_t2_enough_data_resets_empty_search_count` (que codifico el comportamiento incorrecto como si
fuera correcto). Cuando esto se corrija, agregar un golden conversation real de 2 turnos que
ejercite la rama completa antes de volver a pedir aprobacion.

**Estado:** ABIERTO al cierre de esta revision (2026-08-14, Fase 3, RECHAZADO parcial). Verificar en
la proxima revision si sigue abierto -- si aparece un tercer ciclo sin resolverse, escalarlo como
bloqueo de sprint, no solo de una fase.

**RESUELTO 2026-08-14 (segunda pasada QA, mismo dia).** El fix aplicado es exactamente el
recomendado arriba: `_EMPTY_SEARCH_RESET_EVENTS` en `state_machine.py` ya solo contiene
`RESULTS_FOUND` (quitado `ENOUGH_DATA`), y `orchestrator.py` gano `_lead_search_slots()` +
`criteria_changed` (comparacion de los 4 slots del `Lead` ANTES de que `update_lead()` los
sobreescriba este turno, capturados en `handle_message()` y pasados a `_run_property_search()`).
Verificado empiricamente, no solo leido:
- `tests/agent_engine/test_handle_message.py::TestSecondConsecutiveEmptySearchReachesHandoff` hace
  DOS llamadas reales a `handle_message()` con los mismos 4 criterios y confirma
  `HumanHandoff` real en DB (`reason="empty_search_2x"`) + `Lead.stage=HANDOFF` +
  `ConversationState.current_state=HANDOFF` -- ya no llama la funcion privada directamente.
- `TestCriteriaChangeResetsEmptySearchCounter` confirma el reset legitimo (cambio de 1 de los 4
  criterios) sigue funcionando y NO dispara handoff.
- Golden conversation nueva "Rama 2b" en `tests/agent_engine/test_golden_conversations_tools.py`
  cubre la misma rama con 2 turnos reales.
- Caso borde de "primer intento de la conversacion, sin criterio anterior" tratado correctamente:
  `_lead_search_slots(lead)` sobre un Lead recien creado devuelve todo `None`, que compara distinto
  de `merged_entities` con datos -> `criteria_changed=True` -> arranca en 0 (ademas el default del
  parametro tambien es `True` como cinturon de seguridad).
- `pytest tests/ -q` re-corrido desde cero: 279 passed (coincide exactamente con lo reportado:
  277 previos - 1 reemplazado + 3 nuevos). `ruff check .` limpio.

Cerrado. Si en una fase futura (Calendar/WhatsApp) aparece un contador o "reset por cambio de
criterio" similar, revisar con el mismo rigor: la funcion pura de state machine NO debe decidir
resets que dependan de comparar datos de negocio entre turnos -- eso vive en el orquestador con
visibilidad de la fila persistida anterior.
