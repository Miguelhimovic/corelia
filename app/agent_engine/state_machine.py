"""State machine formal del flujo Real Estate (SPEC.md secciones 1 y 2).

Modulo puro: sin I/O, sin llamadas a DB ni a Claude. Traduce eventos de
negocio ya resueltos (ver `StateEvent`) a transiciones de `LeadStage`
(`app/models/enums.py`), incluyendo la logica de los dos contadores que
persiste `ConversationState` (`empty_search_count`, `no_response_count`,
ver `app/models/conversation_state.py`).

`StateEvent` es un concepto DISTINTO de `LeadIntent` (`app/models/enums.py`):
`LeadIntent` es lo que devuelve el classifier/LLM sobre un mensaje aislado
(SPEC.md seccion 3); `StateEvent` es lo que efectivamente consume la state
machine, que depende tambien del estado actual y de resultados de tools
(Calendar, catalogo) que todavia no existen en esta tarea (Fase 3). El
orquestador de la Tarea 5 es quien decide, con ese contexto adicional, que
`StateEvent` dispara cada turno antes de llamar a `transition()`. Este
modulo expone `map_intent_to_event()` como ayuda para el unico mapeo
intent->evento que es 1-a-1 sin importar el estado (`human_request`,
`not_interested`) — el resto de intents requiere contexto que no vive aqui
y se documenta explicitamente en esa funcion.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from app.models.enums import LeadIntent, LeadStage

# SPEC.md seccion 1: "2 recordatorios sin respuesta" / "2 busquedas vacias
# seguidas" son los umbrales que disparan NURTURE/HANDOFF respectivamente.
_MAX_NO_RESPONSE = 2
_MAX_EMPTY_SEARCHES = 2


class StateEvent(enum.StrEnum):
    """Eventos de entrada a la state machine (SPEC.md seccion 2).

    Ver el docstring del modulo para la distincion evento vs. intent.
    """

    NEW_MESSAGE = "new_message"
    HUMAN_REQUEST = "human_request"
    NOT_INTERESTED = "not_interested"
    ENOUGH_DATA = "enough_data"
    NO_RESPONSE = "no_response"
    RESULTS_FOUND = "results_found"
    RESULTS_EMPTY = "results_empty"
    USER_SELECTS_PROPERTY = "user_selects_property"
    WANTS_VISIT = "wants_visit"
    MEETING_CONFIRMED = "meeting_confirmed"
    CALENDAR_ERROR = "calendar_error"
    CANCELLATION_REQUESTED = "cancellation_requested"


class InvalidTransitionError(Exception):
    """SPEC.md seccion 2 no define ninguna transicion para (estado, evento).

    Fail-safe (CLAUDE.md, SPEC.md seccion 7): nunca se cae a un estado por
    default en silencio. Esto senala un bug de logica del orquestador (le
    llego un evento que no aplica a ese estado), no un caso de negocio a
    resolver con handoff.
    """

    def __init__(self, current_state: LeadStage, event: StateEvent) -> None:
        self.current_state = current_state
        self.event = event
        super().__init__(
            "Transicion no definida en SPEC.md seccion 2: "
            f"estado={current_state.value!r}, evento={event.value!r}"
        )


@dataclass(frozen=True)
class TransitionResult:
    """Resultado de aplicar un evento: nuevo estado + contadores actualizados.

    `no_response_count` se resetea a 0 en TODA transicion que cambia de
    estado (SPEC.md seccion 1); si el evento no produce cambio de estado
    (un `no_response` que todavia no llega al umbral) el contador queda
    incrementado. `empty_search_count` sigue la misma logica para
    `results_empty`, y ademas se resetea al recibir `enough_data` o
    `results_found` — se interpreta como el fin de un intento de busqueda
    (SPEC.md seccion 1: "resetea a 0 cuando el usuario cambia cualquiera
    de los 4 criterios de busqueda"; el punto en que la state machine
    puede observar eso, sin conocer las entities, es cuando el
    orquestador confirma que los 4 slots vuelven a estar completos).

    `changed_state`: True si `new_state != current_state` recibido por
    `transition()` — util para que el orquestador sepa si debe persistir
    un nuevo `last_transition_at`.
    """

    new_state: LeadStage
    empty_search_count: int
    no_response_count: int
    changed_state: bool


# Maxima prioridad (SPEC.md seccion 1): se evaluan antes que cualquier otra
# logica, desde cualquier estado ("*" en la tabla de la seccion 2).
_UNIVERSAL_TRANSITIONS: dict[StateEvent, LeadStage] = {
    StateEvent.HUMAN_REQUEST: LeadStage.HANDOFF,
    StateEvent.NOT_INTERESTED: LeadStage.LOST,
}

# Transiciones simples (sin logica de contador) de SPEC.md seccion 2.
# QUALIFYING no aparece como origen: su unica salida (-> PROPERTY_SEARCH) es
# automatica, ver `apply_automatic_transitions()`. RESULTS_EMPTY tampoco
# aparece aqui (solo aplica a PROPERTY_SEARCH) porque su logica de contador
# se resuelve aparte en `_apply_results_empty()`.
_SIMPLE_TRANSITIONS: dict[LeadStage, dict[StateEvent, LeadStage]] = {
    LeadStage.NEW: {
        StateEvent.NEW_MESSAGE: LeadStage.DISCOVERING,
    },
    LeadStage.DISCOVERING: {
        StateEvent.ENOUGH_DATA: LeadStage.QUALIFYING,
    },
    LeadStage.PROPERTY_SEARCH: {
        StateEvent.RESULTS_FOUND: LeadStage.PRESENTING,
    },
    LeadStage.PRESENTING: {
        StateEvent.USER_SELECTS_PROPERTY: LeadStage.SCHEDULING,
        StateEvent.WANTS_VISIT: LeadStage.SCHEDULING,
    },
    LeadStage.SCHEDULING: {
        StateEvent.MEETING_CONFIRMED: LeadStage.BOOKED,
        StateEvent.CALENDAR_ERROR: LeadStage.HANDOFF,
    },
    LeadStage.BOOKED: {
        StateEvent.CANCELLATION_REQUESTED: LeadStage.HANDOFF,
    },
    LeadStage.NURTURE: {
        StateEvent.NEW_MESSAGE: LeadStage.DISCOVERING,
    },
}

# Estados donde `no_response` cuenta recordatorios (SPEC.md seccion 1).
_NO_RESPONSE_STATES = frozenset(
    {LeadStage.DISCOVERING, LeadStage.PRESENTING, LeadStage.SCHEDULING}
)

# Eventos que cierran (con exito) un intento de busqueda y por lo tanto
# rompen la racha de `empty_search_count` (ver docstring de TransitionResult).
_EMPTY_SEARCH_RESET_EVENTS = frozenset({StateEvent.ENOUGH_DATA, StateEvent.RESULTS_FOUND})


def transition(
    current_state: LeadStage,
    event: StateEvent,
    *,
    empty_search_count: int = 0,
    no_response_count: int = 0,
) -> TransitionResult:
    """Aplica un evento al estado actual segun SPEC.md seccion 2.

    Funcion pura: no hace I/O, no consulta DB ni Claude. Los contadores
    `empty_search_count`/`no_response_count` se reciben y devuelven como
    datos explicitos (viven en `ConversationState`, SPEC.md seccion 5) —
    leerlos/persistirlos es responsabilidad del orquestador (Tarea 5).

    Prioridad (SPEC.md seccion 1): `human_request` y `not_interested` se
    evaluan ANTES que cualquier otra logica, sin importar `current_state`.

    Raises:
        InvalidTransitionError: si SPEC.md seccion 2 no define ninguna
            transicion para `(current_state, event)`.
    """
    if event in _UNIVERSAL_TRANSITIONS:
        new_state = _UNIVERSAL_TRANSITIONS[event]
        return TransitionResult(
            new_state=new_state,
            empty_search_count=0,
            no_response_count=0,
            changed_state=new_state != current_state,
        )

    if event is StateEvent.NO_RESPONSE:
        return _apply_no_response(current_state, no_response_count, empty_search_count)

    if event is StateEvent.RESULTS_EMPTY:
        return _apply_results_empty(current_state, empty_search_count)

    next_state = _SIMPLE_TRANSITIONS.get(current_state, {}).get(event)
    if next_state is None:
        raise InvalidTransitionError(current_state, event)

    return TransitionResult(
        new_state=next_state,
        empty_search_count=(
            0 if event in _EMPTY_SEARCH_RESET_EVENTS else empty_search_count
        ),
        no_response_count=0,
        changed_state=next_state != current_state,
    )


def _apply_no_response(
    current_state: LeadStage, no_response_count: int, empty_search_count: int
) -> TransitionResult:
    """`no_response` (SPEC.md seccion 1): solo valido en DISCOVERING,
    PRESENTING o SCHEDULING; 2 recordatorios sin respuesta -> NURTURE."""
    if current_state not in _NO_RESPONSE_STATES:
        raise InvalidTransitionError(current_state, StateEvent.NO_RESPONSE)

    updated_count = no_response_count + 1
    if updated_count >= _MAX_NO_RESPONSE:
        return TransitionResult(
            new_state=LeadStage.NURTURE,
            empty_search_count=0,
            no_response_count=0,
            changed_state=True,
        )
    return TransitionResult(
        new_state=current_state,
        empty_search_count=empty_search_count,
        no_response_count=updated_count,
        changed_state=False,
    )


def _apply_results_empty(current_state: LeadStage, empty_search_count: int) -> TransitionResult:
    """`results_empty` (SPEC.md seccion 2): solo valido en PROPERTY_SEARCH;
    una vuelta a DISCOVERING para ajustar criterio, 2 seguidas -> HANDOFF."""
    if current_state is not LeadStage.PROPERTY_SEARCH:
        raise InvalidTransitionError(current_state, StateEvent.RESULTS_EMPTY)

    updated_count = empty_search_count + 1
    if updated_count >= _MAX_EMPTY_SEARCHES:
        return TransitionResult(
            new_state=LeadStage.HANDOFF,
            empty_search_count=0,
            no_response_count=0,
            changed_state=True,
        )
    return TransitionResult(
        new_state=LeadStage.DISCOVERING,
        empty_search_count=updated_count,
        no_response_count=0,
        changed_state=True,
    )


def apply_automatic_transitions(state: LeadStage) -> LeadStage:
    """Aplica las transiciones que el sistema dispara solo, sin evento de
    usuario (SPEC.md seccion 2).

    `QUALIFYING -> PROPERTY_SEARCH` es la unica transicion automatica de la
    tabla: ocurre "al entrar al estado", no como respuesta a un mensaje. Se
    modela deliberadamente aparte de `transition()` (que solo consume
    eventos externos) para no disfrazarla de evento inventado. El
    orquestador (Tarea 5) debe llamar esta funcion inmediatamente despues
    de cualquier `transition()` cuyo `new_state` sea `QUALIFYING`, antes de
    persistir el estado final del turno.
    """
    if state is LeadStage.QUALIFYING:
        return LeadStage.PROPERTY_SEARCH
    return state


# Unico mapeo intent->evento que no depende de contexto adicional (SPEC.md
# seccion 1: maxima prioridad "en cualquier punto").
_DIRECT_INTENT_EVENT_MAP: dict[LeadIntent, StateEvent] = {
    LeadIntent.HUMAN_REQUEST: StateEvent.HUMAN_REQUEST,
    LeadIntent.NOT_INTERESTED: StateEvent.NOT_INTERESTED,
}


def map_intent_to_event(intent: LeadIntent) -> StateEvent | None:
    """Mapeo 1-a-1 de los unicos `LeadIntent` que siempre disparan el mismo
    `StateEvent` sin importar el estado actual ni datos externos.

    `human_request` y `not_interested` son los dos casos "* -> HANDOFF" / "*
    -> LOST" de SPEC.md seccion 1 (maxima prioridad, en cualquier punto) —
    no requieren mas contexto que el intent mismo.

    El resto de intents NO tiene un evento fijo y este helper devuelve
    `None` para que el orquestador (Tarea 5) lo resuelva con el contexto
    que le falta a este modulo puro:
    - `property_search`: solo dispara `ENOUGH_DATA` si los 4 slots
      (location, budget_max, bedrooms, purpose) estan completos con
      `confidence >= 0.7` (SPEC.md seccion 1) — esa validacion vive en el
      orquestador, no aqui.
    - `cancel`: dispara `CANCELLATION_REQUESTED` solo si el lead tiene una
      cita agendada; si no, SPEC.md seccion 1 lo trata como una pregunta
      fuera de flujo (cancelar algo que no existe sugiere confusion, no
      necesariamente opt-out) y el orquestador la resuelve como
      `HUMAN_REQUEST`/HANDOFF, no como `not_interested`/LOST — ver el bullet
      correspondiente en SPEC.md seccion 1 y el docstring de `_resolve_turn`
      en `orchestrator.py` (Fase 2, Tarea 5) para el detalle.
    - `question` / `other`: no tienen un `StateEvent` de state machine
      definido en la seccion 2 — el orquestador decide la respuesta
      (p.ej. handoff por falta de FAQ) fuera de esta maquina.
    """
    return _DIRECT_INTENT_EVENT_MAP.get(intent)
