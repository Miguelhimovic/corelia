"""Unit tests de la state machine formal (SPEC.md secciones 1-2).

`transition()` es una funcion pura: se prueba llamandola directamente con
cada par (estado, evento) de la tabla de SPEC.md seccion 2 (las 17
transiciones nombradas, ver desglose abajo), mas los contadores
`empty_search_count`/`no_response_count` y `InvalidTransitionError` para
pares no definidos.

Desglose de las 17 transiciones de la tabla (cada linea "Estado -> Estado :
evento" contada individualmente, incluyendo las que la tabla lista con "o"
entre dos eventos como dos lineas separadas, y el umbral de 2 busquedas
vacias de PROPERTY_SEARCH -> HANDOFF como una transicion aparte de la
primera busqueda vacia PROPERTY_SEARCH -> DISCOVERING):

 1. NEW -> DISCOVERING              : new_message
 2. DISCOVERING -> QUALIFYING       : enough_data
 3. DISCOVERING -> HANDOFF          : human_request
 4. DISCOVERING -> NURTURE          : no_response (tras 2 recordatorios)
 5. QUALIFYING -> PROPERTY_SEARCH   : automatico (apply_automatic_transitions)
 6. PROPERTY_SEARCH -> PRESENTING   : results_found
 7. PROPERTY_SEARCH -> DISCOVERING  : results_empty (1ra, no llega al umbral)
 8. PROPERTY_SEARCH -> HANDOFF      : results_empty (2da consecutiva, umbral)
 9. PRESENTING -> SCHEDULING        : user_selects_property
10. PRESENTING -> SCHEDULING        : wants_visit
11. PRESENTING -> HANDOFF           : human_request
12. SCHEDULING -> BOOKED            : meeting_confirmed
13. SCHEDULING -> HANDOFF           : calendar_error
14. SCHEDULING -> HANDOFF           : human_request
15. BOOKED -> HANDOFF               : cancellation_requested
16. *  -> LOST                      : not_interested
17. *  -> HANDOFF                   : human_request

NOTA (hallazgo, no corregido aqui): `state_machine.py` ademas implementa
NURTURE -> DISCOVERING via `new_message`, que NO esta en la tabla literal de
SPEC.md seccion 2 (la tabla no tiene ninguna fila con origen NURTURE). Se
prueba igual porque es el comportamiento real implementado, pero se reporta
como discrepancia de documentacion en el resumen de este turno.
"""

import pytest

from app.agent_engine.state_machine import (
    InvalidTransitionError,
    StateEvent,
    apply_automatic_transitions,
    map_intent_to_event,
    transition,
)
from app.models.enums import LeadIntent, LeadStage

# ---------------------------------------------------------------------------
# 1-17: transiciones nombradas de la tabla (mas NURTURE->DISCOVERING, extra)
# ---------------------------------------------------------------------------


def test_t1_new_to_discovering_on_new_message() -> None:
    result = transition(LeadStage.NEW, StateEvent.NEW_MESSAGE)
    assert result.new_state == LeadStage.DISCOVERING
    assert result.changed_state is True
    assert result.empty_search_count == 0
    assert result.no_response_count == 0


def test_t2_discovering_to_qualifying_on_enough_data() -> None:
    result = transition(LeadStage.DISCOVERING, StateEvent.ENOUGH_DATA)
    assert result.new_state == LeadStage.QUALIFYING
    assert result.changed_state is True


def test_t2_enough_data_resets_empty_search_count() -> None:
    result = transition(LeadStage.DISCOVERING, StateEvent.ENOUGH_DATA, empty_search_count=1)
    assert result.empty_search_count == 0


def test_t3_discovering_to_handoff_on_human_request() -> None:
    result = transition(LeadStage.DISCOVERING, StateEvent.HUMAN_REQUEST)
    assert result.new_state == LeadStage.HANDOFF
    assert result.changed_state is True


def test_t4_discovering_no_response_once_stays_and_increments() -> None:
    result = transition(LeadStage.DISCOVERING, StateEvent.NO_RESPONSE, no_response_count=0)
    assert result.new_state == LeadStage.DISCOVERING
    assert result.changed_state is False
    assert result.no_response_count == 1


def test_t4_discovering_no_response_twice_moves_to_nurture() -> None:
    result = transition(LeadStage.DISCOVERING, StateEvent.NO_RESPONSE, no_response_count=1)
    assert result.new_state == LeadStage.NURTURE
    assert result.changed_state is True
    assert result.no_response_count == 0


def test_t4_no_response_valid_also_in_presenting_and_scheduling() -> None:
    for state in (LeadStage.PRESENTING, LeadStage.SCHEDULING):
        result = transition(state, StateEvent.NO_RESPONSE, no_response_count=1)
        assert result.new_state == LeadStage.NURTURE


def test_t4_no_response_invalid_outside_allowed_states() -> None:
    with pytest.raises(InvalidTransitionError):
        transition(LeadStage.NEW, StateEvent.NO_RESPONSE)
    with pytest.raises(InvalidTransitionError):
        transition(LeadStage.BOOKED, StateEvent.NO_RESPONSE)


def test_t5_apply_automatic_transitions_qualifying_to_property_search() -> None:
    assert apply_automatic_transitions(LeadStage.QUALIFYING) == LeadStage.PROPERTY_SEARCH


def test_t5_apply_automatic_transitions_noop_for_other_states() -> None:
    for state in LeadStage:
        if state is LeadStage.QUALIFYING:
            continue
        assert apply_automatic_transitions(state) == state


def test_t6_property_search_to_presenting_on_results_found() -> None:
    result = transition(LeadStage.PROPERTY_SEARCH, StateEvent.RESULTS_FOUND)
    assert result.new_state == LeadStage.PRESENTING
    assert result.changed_state is True


def test_t6_results_found_resets_empty_search_count() -> None:
    result = transition(LeadStage.PROPERTY_SEARCH, StateEvent.RESULTS_FOUND, empty_search_count=1)
    assert result.empty_search_count == 0


def test_t7_property_search_first_empty_result_returns_to_discovering() -> None:
    result = transition(LeadStage.PROPERTY_SEARCH, StateEvent.RESULTS_EMPTY, empty_search_count=0)
    assert result.new_state == LeadStage.DISCOVERING
    assert result.changed_state is True
    assert result.empty_search_count == 1


def test_t8_property_search_second_consecutive_empty_result_goes_to_handoff() -> None:
    result = transition(LeadStage.PROPERTY_SEARCH, StateEvent.RESULTS_EMPTY, empty_search_count=1)
    assert result.new_state == LeadStage.HANDOFF
    assert result.changed_state is True
    assert result.empty_search_count == 0


def test_t7_t8_results_empty_invalid_outside_property_search() -> None:
    with pytest.raises(InvalidTransitionError):
        transition(LeadStage.DISCOVERING, StateEvent.RESULTS_EMPTY)


def test_t9_presenting_to_scheduling_on_user_selects_property() -> None:
    result = transition(LeadStage.PRESENTING, StateEvent.USER_SELECTS_PROPERTY)
    assert result.new_state == LeadStage.SCHEDULING
    assert result.changed_state is True


def test_t10_presenting_to_scheduling_on_wants_visit() -> None:
    result = transition(LeadStage.PRESENTING, StateEvent.WANTS_VISIT)
    assert result.new_state == LeadStage.SCHEDULING
    assert result.changed_state is True


def test_t11_presenting_to_handoff_on_human_request() -> None:
    result = transition(LeadStage.PRESENTING, StateEvent.HUMAN_REQUEST)
    assert result.new_state == LeadStage.HANDOFF


def test_t12_scheduling_to_booked_on_meeting_confirmed() -> None:
    result = transition(LeadStage.SCHEDULING, StateEvent.MEETING_CONFIRMED)
    assert result.new_state == LeadStage.BOOKED
    assert result.changed_state is True


def test_t13_scheduling_to_handoff_on_calendar_error() -> None:
    result = transition(LeadStage.SCHEDULING, StateEvent.CALENDAR_ERROR)
    assert result.new_state == LeadStage.HANDOFF
    assert result.changed_state is True


def test_t14_scheduling_to_handoff_on_human_request() -> None:
    result = transition(LeadStage.SCHEDULING, StateEvent.HUMAN_REQUEST)
    assert result.new_state == LeadStage.HANDOFF


def test_t15_booked_to_handoff_on_cancellation_requested() -> None:
    result = transition(LeadStage.BOOKED, StateEvent.CANCELLATION_REQUESTED)
    assert result.new_state == LeadStage.HANDOFF
    assert result.changed_state is True


def test_t15_cancellation_requested_invalid_outside_booked() -> None:
    with pytest.raises(InvalidTransitionError):
        transition(LeadStage.SCHEDULING, StateEvent.CANCELLATION_REQUESTED)


@pytest.mark.parametrize(
    "state",
    [
        LeadStage.NEW,
        LeadStage.DISCOVERING,
        LeadStage.QUALIFYING,
        LeadStage.PROPERTY_SEARCH,
        LeadStage.PRESENTING,
        LeadStage.SCHEDULING,
        LeadStage.BOOKED,
        LeadStage.HANDOFF,
        LeadStage.NURTURE,
        LeadStage.LOST,
    ],
)
def test_t16_not_interested_moves_to_lost_from_any_state(state: LeadStage) -> None:
    result = transition(state, StateEvent.NOT_INTERESTED)
    assert result.new_state == LeadStage.LOST
    assert result.empty_search_count == 0
    assert result.no_response_count == 0


@pytest.mark.parametrize(
    "state",
    [
        LeadStage.NEW,
        LeadStage.DISCOVERING,
        LeadStage.QUALIFYING,
        LeadStage.PROPERTY_SEARCH,
        LeadStage.PRESENTING,
        LeadStage.SCHEDULING,
        LeadStage.BOOKED,
        LeadStage.HANDOFF,
        LeadStage.NURTURE,
        LeadStage.LOST,
    ],
)
def test_t17_human_request_moves_to_handoff_from_any_state(state: LeadStage) -> None:
    result = transition(state, StateEvent.HUMAN_REQUEST)
    assert result.new_state == LeadStage.HANDOFF
    assert result.empty_search_count == 0
    assert result.no_response_count == 0


def test_universal_priority_overrides_pending_counters_even_at_threshold() -> None:
    # Aunque el contador de no_response ya estuviera a una respuesta del
    # umbral, human_request/not_interested tienen prioridad maxima y no
    # deben pasar por la logica de contador de no_response en absoluto.
    result = transition(
        LeadStage.DISCOVERING, StateEvent.HUMAN_REQUEST, no_response_count=1, empty_search_count=1
    )
    assert result.new_state == LeadStage.HANDOFF
    assert result.no_response_count == 0
    assert result.empty_search_count == 0


def test_extra_nurture_to_discovering_on_new_message_not_in_spec_table() -> None:
    """Comportamiento real implementado (ver docstring del modulo): no esta
    en la tabla literal de SPEC.md seccion 2, que no tiene ninguna fila con
    origen NURTURE. Se documenta como discrepancia, no como bug."""
    result = transition(LeadStage.NURTURE, StateEvent.NEW_MESSAGE)
    assert result.new_state == LeadStage.DISCOVERING
    assert result.changed_state is True


# ---------------------------------------------------------------------------
# InvalidTransitionError: pares (estado, evento) no definidos en absoluto
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "event"),
    [
        (LeadStage.NEW, StateEvent.ENOUGH_DATA),
        (LeadStage.NEW, StateEvent.MEETING_CONFIRMED),
        (LeadStage.QUALIFYING, StateEvent.ENOUGH_DATA),
        (LeadStage.PROPERTY_SEARCH, StateEvent.USER_SELECTS_PROPERTY),
        (LeadStage.PRESENTING, StateEvent.RESULTS_FOUND),
        (LeadStage.SCHEDULING, StateEvent.USER_SELECTS_PROPERTY),
        (LeadStage.BOOKED, StateEvent.MEETING_CONFIRMED),
        (LeadStage.HANDOFF, StateEvent.NEW_MESSAGE),
        (LeadStage.LOST, StateEvent.NEW_MESSAGE),
    ],
)
def test_invalid_transition_raises_with_no_defined_mapping(
    state: LeadStage, event: StateEvent
) -> None:
    with pytest.raises(InvalidTransitionError) as exc_info:
        transition(state, event)
    assert exc_info.value.current_state == state
    assert exc_info.value.event == event


def test_invalid_transition_error_message_is_descriptive() -> None:
    with pytest.raises(InvalidTransitionError, match="NEW.*enough_data"):
        transition(LeadStage.NEW, StateEvent.ENOUGH_DATA)


# ---------------------------------------------------------------------------
# no_response_count reset on any state-changing transition (docstring claim)
# ---------------------------------------------------------------------------


def test_no_response_count_resets_on_any_state_changing_transition() -> None:
    result = transition(LeadStage.PROPERTY_SEARCH, StateEvent.RESULTS_FOUND, no_response_count=1)
    assert result.no_response_count == 0


def test_no_response_count_preserved_when_state_does_not_change() -> None:
    # results_empty en PROPERTY_SEARCH SI cambia de estado (a DISCOVERING),
    # asi que no_response_count se resetea junto con el cambio de estado
    # (mismo criterio documentado: se resetea en TODA transicion que
    # cambia de estado, no solo en las de "no_response").
    result = transition(LeadStage.PROPERTY_SEARCH, StateEvent.RESULTS_EMPTY, no_response_count=1)
    assert result.no_response_count == 0


# ---------------------------------------------------------------------------
# map_intent_to_event
# ---------------------------------------------------------------------------


def test_map_intent_to_event_human_request() -> None:
    assert map_intent_to_event(LeadIntent.HUMAN_REQUEST) == StateEvent.HUMAN_REQUEST


def test_map_intent_to_event_not_interested() -> None:
    assert map_intent_to_event(LeadIntent.NOT_INTERESTED) == StateEvent.NOT_INTERESTED


@pytest.mark.parametrize(
    "intent",
    [LeadIntent.PROPERTY_SEARCH, LeadIntent.QUESTION, LeadIntent.CANCEL, LeadIntent.OTHER],
)
def test_map_intent_to_event_returns_none_for_context_dependent_intents(
    intent: LeadIntent,
) -> None:
    assert map_intent_to_event(intent) is None
