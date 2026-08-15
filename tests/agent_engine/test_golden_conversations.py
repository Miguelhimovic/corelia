"""Golden conversations del agent engine (SPEC.md seccion 9).

Formato: SPEC.md seccion 9 define un YAML-like `input` -> `expected`
(intent/entities/state_after). Este repo no tiene PyYAML como dependencia
declarada (`requirements-dev.txt`) y ningun test existente usa YAML —
agregar una dependencia nueva solo para el formato de golden conversations
violaria CLAUDE.md ("sin dependencias nuevas sin justificarlas"). Se adapta
el mismo shape (input/expected, con `state_after`) a listas de dicts en
Python puro, corridas via `pytest.mark.parametrize`, que es el patron ya
establecido en `tests/` (pytest + fixtures, sin YAML).

"Una rama" = cada transicion nombrada individualmente en la tabla de SPEC.md
seccion 2 (ver desglose completo en el docstring de
`tests/agent_engine/test_state_machine.py`), no cada camino end-to-end.

Dos grupos de golden conversations, por una limitacion real y esperada de
esta fase (Fase 2 del sprint, Fase 3 -- tools de Calendar/catalogo -- no
implementada todavia):

1. `ORCHESTRATOR_GOLDEN_CONVERSATIONS`: ramas que el orquestador SI puede
   producir a partir de un mensaje de texto real (`process_incoming_message`
   contra DB real + LLM mockeado) -- human_request, not_interested,
   enough_data, requires_clarification, cancel (con/sin cita), question/
   other sin FAQ, fallo de LLM, reactivacion desde NURTURE.
2. `STATE_MACHINE_GOLDEN_SCENARIOS`: ramas que dependen de resultados de
   tools que no existen todavia (Calendar: meeting_confirmed/calendar_error;
   catalogo: results_found/results_empty; seleccion de propiedad:
   user_selects_property/wants_visit; recordatorios sin respuesta:
   no_response) -- el orquestador no tiene ningun code path que las dispare
   desde un mensaje de usuario en esta fase, asi que se prueban invocando
   `state_machine.transition()` directamente, con el evento de sistema que
   Fase 3 disparara mas adelante. Se documentan igual como golden
   conversations (con su `input` conceptual: el evento de sistema, no un
   mensaje de chat) para no dejar esas ramas sin al menos un caso cubierto.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.agent_engine.orchestrator import OrchestratorAction, process_incoming_message
from app.agent_engine.state_machine import StateEvent, transition
from app.models.enums import LeadIntent, LeadStage
from tests.agent_engine.conftest import LeadConversationFactory
from tests.agent_engine.llm_test_doubles import (
    FakeAsyncAnthropic,
    make_no_tool_use_response,
    make_tool_use_response,
)


@dataclass(frozen=True)
class GoldenConversation:
    id: str
    branch: str
    initial_state: LeadStage
    message: str
    expected_intent: LeadIntent
    expected_state_after: LeadStage
    llm_response: dict[str, Any] | None = None
    expected_action: OrchestratorAction | None = None
    expected_handoff_reason: str | None = None
    expected_entities: dict[str, Any] = field(default_factory=dict)


def _property_search_payload(
    *,
    location: str | None,
    budget_max: float | None,
    bedrooms: int | None,
    purpose: str | None,
    confidence: float,
    requires_clarification: bool = False,
    intent: str = "property_search",
) -> dict[str, Any]:
    return {
        "intent": intent,
        "entities": {
            "location": location,
            "budget_max": budget_max,
            "bedrooms": bedrooms,
            "purpose": purpose,
        },
        "confidence": confidence,
        "requires_clarification": requires_clarification,
    }


# ---------------------------------------------------------------------------
# Grupo 1: ramas disparables por un mensaje de chat real via el orquestador
# ---------------------------------------------------------------------------

ORCHESTRATOR_GOLDEN_CONVERSATIONS: list[GoldenConversation] = [
    # --- * -> HANDOFF : human_request (maxima prioridad, 5 casos) ---------
    GoldenConversation(
        id="human_request_from_new",
        branch="* -> HANDOFF (human_request)",
        initial_state=LeadStage.NEW,
        message="Quiero hablar con una persona",
        expected_intent=LeadIntent.HUMAN_REQUEST,
        expected_state_after=LeadStage.HANDOFF,
        expected_action=OrchestratorAction.OFFER_HANDOFF,
        expected_handoff_reason="human_request_explicit",
    ),
    GoldenConversation(
        id="human_request_from_discovering",
        branch="* -> HANDOFF (human_request)",
        initial_state=LeadStage.DISCOVERING,
        message="Necesito hablar con un asesor",
        expected_intent=LeadIntent.HUMAN_REQUEST,
        expected_state_after=LeadStage.HANDOFF,
        expected_action=OrchestratorAction.OFFER_HANDOFF,
        expected_handoff_reason="human_request_explicit",
    ),
    GoldenConversation(
        id="human_request_from_presenting",
        branch="* -> HANDOFF (human_request)",
        initial_state=LeadStage.PRESENTING,
        message="¿Puedo hablar con alguien?",
        expected_intent=LeadIntent.HUMAN_REQUEST,
        expected_state_after=LeadStage.HANDOFF,
        expected_action=OrchestratorAction.OFFER_HANDOFF,
        expected_handoff_reason="human_request_explicit",
    ),
    GoldenConversation(
        id="human_request_from_scheduling",
        branch="* -> HANDOFF (human_request)",
        initial_state=LeadStage.SCHEDULING,
        message="Pásame con un agente humano",
        expected_intent=LeadIntent.HUMAN_REQUEST,
        expected_state_after=LeadStage.HANDOFF,
        expected_action=OrchestratorAction.OFFER_HANDOFF,
        expected_handoff_reason="human_request_explicit",
    ),
    GoldenConversation(
        id="human_request_from_booked",
        branch="* -> HANDOFF (human_request)",
        initial_state=LeadStage.BOOKED,
        message="quiero un asesor",
        expected_intent=LeadIntent.HUMAN_REQUEST,
        expected_state_after=LeadStage.HANDOFF,
        expected_action=OrchestratorAction.OFFER_HANDOFF,
        expected_handoff_reason="human_request_explicit",
    ),
    # --- * -> LOST : not_interested (maxima prioridad, 5 casos) -----------
    GoldenConversation(
        id="not_interested_from_discovering",
        branch="* -> LOST (not_interested)",
        initial_state=LeadStage.DISCOVERING,
        message="Ya no me interesa",
        expected_intent=LeadIntent.NOT_INTERESTED,
        expected_state_after=LeadStage.LOST,
        expected_action=OrchestratorAction.MARK_LOST,
    ),
    GoldenConversation(
        id="not_interested_from_presenting",
        branch="* -> LOST (not_interested)",
        initial_state=LeadStage.PRESENTING,
        message="No, gracias",
        expected_intent=LeadIntent.NOT_INTERESTED,
        expected_state_after=LeadStage.LOST,
        expected_action=OrchestratorAction.MARK_LOST,
    ),
    GoldenConversation(
        id="not_interested_from_scheduling",
        branch="* -> LOST (not_interested)",
        initial_state=LeadStage.SCHEDULING,
        message="No quiero continuar",
        expected_intent=LeadIntent.NOT_INTERESTED,
        expected_state_after=LeadStage.LOST,
        expected_action=OrchestratorAction.MARK_LOST,
    ),
    GoldenConversation(
        id="not_interested_from_property_search",
        branch="* -> LOST (not_interested)",
        initial_state=LeadStage.PROPERTY_SEARCH,
        message="Dejalo asi",
        expected_intent=LeadIntent.NOT_INTERESTED,
        expected_state_after=LeadStage.LOST,
        expected_action=OrchestratorAction.MARK_LOST,
    ),
    GoldenConversation(
        id="not_interested_from_booked",
        branch="* -> LOST (not_interested)",
        initial_state=LeadStage.BOOKED,
        message="Ya no quiero",
        expected_intent=LeadIntent.NOT_INTERESTED,
        expected_state_after=LeadStage.LOST,
        expected_action=OrchestratorAction.MARK_LOST,
    ),
    # --- DISCOVERING -> QUALIFYING -> PROPERTY_SEARCH : enough_data (5) ---
    GoldenConversation(
        id="enough_data_single_message_from_discovering",
        branch="DISCOVERING -> QUALIFYING : enough_data",
        initial_state=LeadStage.DISCOVERING,
        message="Busco apartamento en Pinares, maximo 450 millones, 3 habitaciones, para vivir",
        llm_response=_property_search_payload(
            location="Pinares",
            budget_max=450_000_000,
            bedrooms=3,
            purpose="residential",
            confidence=0.92,
        ),
        expected_intent=LeadIntent.PROPERTY_SEARCH,
        expected_state_after=LeadStage.PROPERTY_SEARCH,
        expected_action=OrchestratorAction.SEARCH_PROPERTIES,
        expected_entities={
            "location": "Pinares",
            "budget_max": 450_000_000,
            "bedrooms": 3,
        },
    ),
    GoldenConversation(
        id="enough_data_first_message_from_new_bootstraps_in_one_turn",
        branch="DISCOVERING -> QUALIFYING : enough_data",
        initial_state=LeadStage.NEW,
        message="Busco apartamento en Laureles, 300 millones, 2 habitaciones, para invertir",
        llm_response=_property_search_payload(
            location="Laureles",
            budget_max=300_000_000,
            bedrooms=2,
            purpose="investment",
            confidence=0.9,
        ),
        expected_intent=LeadIntent.PROPERTY_SEARCH,
        expected_state_after=LeadStage.PROPERTY_SEARCH,
        expected_action=OrchestratorAction.SEARCH_PROPERTIES,
    ),
    GoldenConversation(
        id="enough_data_confidence_exactly_at_threshold_qualifies",
        branch="DISCOVERING -> QUALIFYING : enough_data",
        initial_state=LeadStage.DISCOVERING,
        message="Apartamento en Envigado, 380 millones, 3 habitaciones, para vivir",
        llm_response=_property_search_payload(
            location="Envigado",
            budget_max=380_000_000,
            bedrooms=3,
            purpose="residential",
            confidence=0.7,
        ),
        expected_intent=LeadIntent.PROPERTY_SEARCH,
        expected_state_after=LeadStage.PROPERTY_SEARCH,
        expected_action=OrchestratorAction.SEARCH_PROPERTIES,
    ),
    GoldenConversation(
        id="enough_data_confidence_just_below_threshold_does_not_qualify",
        branch="DISCOVERING -> QUALIFYING : enough_data",
        initial_state=LeadStage.DISCOVERING,
        message="Creo que en Envigado, como 380 millones, 3 habitaciones, para vivir",
        llm_response=_property_search_payload(
            location="Envigado",
            budget_max=380_000_000,
            bedrooms=3,
            purpose="residential",
            confidence=0.69,
        ),
        expected_intent=LeadIntent.PROPERTY_SEARCH,
        expected_state_after=LeadStage.DISCOVERING,
        expected_action=OrchestratorAction.REQUEST_MORE_INFO,
    ),
    GoldenConversation(
        id="enough_data_missing_one_slot_does_not_qualify",
        branch="DISCOVERING -> QUALIFYING : enough_data",
        initial_state=LeadStage.DISCOVERING,
        message="Busco en Sabaneta, 300 millones, para vivir",
        llm_response=_property_search_payload(
            location="Sabaneta",
            budget_max=300_000_000,
            bedrooms=None,
            purpose="residential",
            confidence=0.85,
        ),
        expected_intent=LeadIntent.PROPERTY_SEARCH,
        expected_state_after=LeadStage.DISCOVERING,
        expected_action=OrchestratorAction.REQUEST_MORE_INFO,
    ),
    # --- requires_clarification bloquea el avance (4 casos) ----------------
    GoldenConversation(
        id="clarification_forced_by_low_confidence",
        branch="requires_clarification bloquea avance",
        initial_state=LeadStage.DISCOVERING,
        message="mmm no se, algo por ahi",
        llm_response=_property_search_payload(
            location=None,
            budget_max=None,
            bedrooms=None,
            purpose=None,
            confidence=0.2,
        ),
        expected_intent=LeadIntent.PROPERTY_SEARCH,
        expected_state_after=LeadStage.DISCOVERING,
        expected_action=OrchestratorAction.ASK_CLARIFICATION,
        expected_handoff_reason=None,
    ),
    GoldenConversation(
        id="clarification_explicit_true_overrides_complete_slots",
        branch="requires_clarification bloquea avance",
        initial_state=LeadStage.DISCOVERING,
        message="en pinares creo, no me acuerdo el resto",
        llm_response=_property_search_payload(
            location="Pinares",
            budget_max=450_000_000,
            bedrooms=3,
            purpose="residential",
            confidence=0.45,
            requires_clarification=True,
        ),
        expected_intent=LeadIntent.PROPERTY_SEARCH,
        expected_state_after=LeadStage.DISCOVERING,
        expected_action=OrchestratorAction.ASK_CLARIFICATION,
    ),
    GoldenConversation(
        id="clarification_from_new_still_bootstraps_but_does_not_advance_further",
        branch="requires_clarification bloquea avance",
        initial_state=LeadStage.NEW,
        message="hola",
        llm_response=_property_search_payload(
            location=None,
            budget_max=None,
            bedrooms=None,
            purpose=None,
            confidence=0.3,
            intent="other",
        ),
        expected_intent=LeadIntent.OTHER,
        expected_state_after=LeadStage.DISCOVERING,
        expected_action=OrchestratorAction.ASK_CLARIFICATION,
    ),
    GoldenConversation(
        id="clarification_precedes_question_handoff_when_confidence_low",
        branch="requires_clarification bloquea avance",
        initial_state=LeadStage.DISCOVERING,
        message="no se bien que pregunta hacer",
        llm_response=_property_search_payload(
            location=None,
            budget_max=None,
            bedrooms=None,
            purpose=None,
            confidence=0.3,
            intent="question",
        ),
        expected_intent=LeadIntent.QUESTION,
        expected_state_after=LeadStage.DISCOVERING,
        expected_action=OrchestratorAction.ASK_CLARIFICATION,
        expected_handoff_reason=None,
    ),
    # --- BOOKED -> HANDOFF : cancellation_requested (cancel con cita, 3) --
    GoldenConversation(
        id="cancel_with_booked_meeting",
        branch="BOOKED -> HANDOFF : cancellation_requested",
        initial_state=LeadStage.BOOKED,
        message="Necesito cancelar mi cita",
        expected_intent=LeadIntent.CANCEL,
        expected_state_after=LeadStage.HANDOFF,
        expected_action=OrchestratorAction.OFFER_HANDOFF,
        expected_handoff_reason="cancellation_with_meeting_booked",
    ),
    GoldenConversation(
        id="cancel_with_booked_meeting_reschedule_wording",
        branch="BOOKED -> HANDOFF : cancellation_requested",
        initial_state=LeadStage.BOOKED,
        message="Quiero reagendar",
        expected_intent=LeadIntent.CANCEL,
        expected_state_after=LeadStage.HANDOFF,
        expected_action=OrchestratorAction.OFFER_HANDOFF,
        expected_handoff_reason="cancellation_with_meeting_booked",
    ),
    GoldenConversation(
        id="cancel_with_booked_meeting_cannot_attend_wording",
        branch="BOOKED -> HANDOFF : cancellation_requested",
        initial_state=LeadStage.BOOKED,
        message="No puedo asistir a la cita",
        expected_intent=LeadIntent.CANCEL,
        expected_state_after=LeadStage.HANDOFF,
        expected_action=OrchestratorAction.OFFER_HANDOFF,
        expected_handoff_reason="cancellation_with_meeting_booked",
    ),
    # --- cancel sin cita agendada -> HANDOFF (reutiliza human_request, 3) --
    GoldenConversation(
        id="cancel_without_booked_meeting_from_discovering",
        branch="cancel sin cita -> HANDOFF (human_request reutilizado)",
        initial_state=LeadStage.DISCOVERING,
        message="Quiero cancelar mi cita",
        expected_intent=LeadIntent.CANCEL,
        expected_state_after=LeadStage.HANDOFF,
        expected_action=OrchestratorAction.OFFER_HANDOFF,
        expected_handoff_reason="cancel_without_scheduled_meeting",
    ),
    GoldenConversation(
        id="cancel_without_booked_meeting_from_presenting",
        branch="cancel sin cita -> HANDOFF (human_request reutilizado)",
        initial_state=LeadStage.PRESENTING,
        message="Necesito cancelar la reunion",
        expected_intent=LeadIntent.CANCEL,
        expected_state_after=LeadStage.HANDOFF,
        expected_action=OrchestratorAction.OFFER_HANDOFF,
        expected_handoff_reason="cancel_without_scheduled_meeting",
    ),
    GoldenConversation(
        id="cancel_without_booked_meeting_from_new",
        branch="cancel sin cita -> HANDOFF (human_request reutilizado)",
        initial_state=LeadStage.NEW,
        message="Quiero cambiar mi cita",
        expected_intent=LeadIntent.CANCEL,
        expected_state_after=LeadStage.HANDOFF,
        expected_action=OrchestratorAction.OFFER_HANDOFF,
        expected_handoff_reason="cancel_without_scheduled_meeting",
    ),
    # --- question/other sin FAQ -> HANDOFF (4 casos) ------------------------
    GoldenConversation(
        id="question_no_faq_financing",
        branch="question/other -> HANDOFF (sin FAQ)",
        initial_state=LeadStage.DISCOVERING,
        message="¿Manejan financiacion con el banco?",
        llm_response=_property_search_payload(
            location=None,
            budget_max=None,
            bedrooms=None,
            purpose=None,
            confidence=0.85,
            intent="question",
        ),
        expected_intent=LeadIntent.QUESTION,
        expected_state_after=LeadStage.HANDOFF,
        expected_action=OrchestratorAction.OFFER_HANDOFF,
        expected_handoff_reason="unanswered_question_no_faq",
    ),
    GoldenConversation(
        id="question_no_faq_warranty",
        branch="question/other -> HANDOFF (sin FAQ)",
        initial_state=LeadStage.DISCOVERING,
        message="¿La propiedad tiene garantia de construccion?",
        llm_response=_property_search_payload(
            location=None,
            budget_max=None,
            bedrooms=None,
            purpose=None,
            confidence=0.8,
            intent="question",
        ),
        expected_intent=LeadIntent.QUESTION,
        expected_state_after=LeadStage.HANDOFF,
        expected_action=OrchestratorAction.OFFER_HANDOFF,
        expected_handoff_reason="unanswered_question_no_faq",
    ),
    GoldenConversation(
        id="other_intent_no_faq",
        branch="question/other -> HANDOFF (sin FAQ)",
        initial_state=LeadStage.PRESENTING,
        message="jajaja que buena esa",
        llm_response=_property_search_payload(
            location=None,
            budget_max=None,
            bedrooms=None,
            purpose=None,
            confidence=0.75,
            intent="other",
        ),
        expected_intent=LeadIntent.OTHER,
        expected_state_after=LeadStage.HANDOFF,
        expected_action=OrchestratorAction.OFFER_HANDOFF,
        expected_handoff_reason="unanswered_question_no_faq",
    ),
    GoldenConversation(
        id="question_no_faq_from_scheduling",
        branch="question/other -> HANDOFF (sin FAQ)",
        initial_state=LeadStage.SCHEDULING,
        message="¿La visita incluye al administrador del edificio?",
        llm_response=_property_search_payload(
            location=None,
            budget_max=None,
            bedrooms=None,
            purpose=None,
            confidence=0.8,
            intent="question",
        ),
        expected_intent=LeadIntent.QUESTION,
        expected_state_after=LeadStage.HANDOFF,
        expected_action=OrchestratorAction.OFFER_HANDOFF,
        expected_handoff_reason="unanswered_question_no_faq",
    ),
    # --- NURTURE -> DISCOVERING : reactivacion. Documentada en SPEC.md
    #     seccion 1 ("Salida de NURTURE": "Si el usuario envia cualquier
    #     mensaje nuevo estando en NURTURE, la transicion es NURTURE ->
    #     DISCOVERING") -- no aparece en la tabla de transiciones de la
    #     seccion 2, pero si es un comportamiento especificado, 3 casos.
    GoldenConversation(
        id="nurture_reactivation_partial_info",
        branch="NURTURE -> DISCOVERING (SPEC.md seccion 1, 'Salida de NURTURE')",
        initial_state=LeadStage.NURTURE,
        message="Hola, sigo buscando en Envigado",
        llm_response=_property_search_payload(
            location="Envigado",
            budget_max=None,
            bedrooms=None,
            purpose=None,
            confidence=0.8,
        ),
        expected_intent=LeadIntent.PROPERTY_SEARCH,
        expected_state_after=LeadStage.DISCOVERING,
        expected_action=OrchestratorAction.REQUEST_MORE_INFO,
    ),
    GoldenConversation(
        id="nurture_reactivation_full_info_advances_in_one_turn",
        branch="NURTURE -> DISCOVERING (SPEC.md seccion 1, 'Salida de NURTURE')",
        initial_state=LeadStage.NURTURE,
        message="Sigo interesado: Sabaneta, 300 millones, 2 habitaciones, para invertir",
        llm_response=_property_search_payload(
            location="Sabaneta",
            budget_max=300_000_000,
            bedrooms=2,
            purpose="investment",
            confidence=0.9,
        ),
        expected_intent=LeadIntent.PROPERTY_SEARCH,
        expected_state_after=LeadStage.PROPERTY_SEARCH,
        expected_action=OrchestratorAction.SEARCH_PROPERTIES,
    ),
    GoldenConversation(
        id="nurture_reactivation_question",
        branch="NURTURE -> DISCOVERING (SPEC.md seccion 1, 'Salida de NURTURE')",
        initial_state=LeadStage.NURTURE,
        message="¿Siguen disponibles?",
        llm_response=_property_search_payload(
            location=None,
            budget_max=None,
            bedrooms=None,
            purpose=None,
            confidence=0.8,
            intent="question",
        ),
        expected_intent=LeadIntent.QUESTION,
        # "question" no es universal -> bootstrap NURTURE->DISCOVERING
        # primero, y LUEGO se resuelve como sin-FAQ -> HANDOFF.
        expected_state_after=LeadStage.HANDOFF,
        expected_action=OrchestratorAction.OFFER_HANDOFF,
        expected_handoff_reason="unanswered_question_no_faq",
    ),
    # --- fallo de LLM -> HANDOFF (SPEC.md seccion 7, 3 casos) --------------
    GoldenConversation(
        id="llm_extraction_failed_from_discovering",
        branch="fallo de LLM -> HANDOFF (seccion 7)",
        initial_state=LeadStage.DISCOVERING,
        message="algo que el LLM no logra procesar",
        llm_response=None,  # se ignora: este caso arma su propio cliente fake
        expected_intent=LeadIntent.OTHER,
        expected_state_after=LeadStage.HANDOFF,
        expected_action=OrchestratorAction.OFFER_HANDOFF,
        expected_handoff_reason="llm_extraction_failed",
    ),
    GoldenConversation(
        id="llm_extraction_failed_from_new",
        branch="fallo de LLM -> HANDOFF (seccion 7)",
        initial_state=LeadStage.NEW,
        message="mensaje raro que rompe la extraccion",
        llm_response=None,
        expected_intent=LeadIntent.OTHER,
        expected_state_after=LeadStage.HANDOFF,
        expected_action=OrchestratorAction.OFFER_HANDOFF,
        expected_handoff_reason="llm_extraction_failed",
    ),
    GoldenConversation(
        id="llm_extraction_failed_from_presenting",
        branch="fallo de LLM -> HANDOFF (seccion 7)",
        initial_state=LeadStage.PRESENTING,
        message="mensaje que tampoco se puede clasificar",
        llm_response=None,
        expected_intent=LeadIntent.OTHER,
        expected_state_after=LeadStage.HANDOFF,
        expected_action=OrchestratorAction.OFFER_HANDOFF,
        expected_handoff_reason="llm_extraction_failed",
    ),
]

# IDs que representan el escenario "fallo de LLM": construyen su propio
# cliente fake (dos respuestas sin tool_use -> LLMExtractionFailed) en vez de
# usar `llm_response`, porque ese campo modela una UNICA respuesta valida.
_LLM_FAILURE_IDS = {
    "llm_extraction_failed_from_discovering",
    "llm_extraction_failed_from_new",
    "llm_extraction_failed_from_presenting",
}


@pytest.mark.parametrize("case", ORCHESTRATOR_GOLDEN_CONVERSATIONS, ids=lambda c: c.id)
def test_orchestrator_golden_conversation(
    case: GoldenConversation,
    db_session: Session,
    make_lead_conversation: LeadConversationFactory,
) -> None:
    lead, conversation, _state = make_lead_conversation(current_state=case.initial_state)

    if case.id in _LLM_FAILURE_IDS:
        client = FakeAsyncAnthropic([make_no_tool_use_response(), make_no_tool_use_response()])
    elif case.llm_response is not None:
        client = FakeAsyncAnthropic([make_tool_use_response(case.llm_response)])
    else:
        client = None  # cubierto por el classifier determinista

    result = asyncio.run(
        process_incoming_message(
            db_session,
            conversation_id=conversation.id,
            lead_id=lead.id,
            message=case.message,
            llm_client=client,
        )
    )

    assert result.extraction.intent == case.expected_intent, case.branch
    assert result.new_state == case.expected_state_after, case.branch
    if case.expected_action is not None:
        assert result.action == case.expected_action, case.branch
    assert result.handoff_reason == case.expected_handoff_reason, case.branch
    for field_name, expected_value in case.expected_entities.items():
        assert getattr(result.merged_entities, field_name) == expected_value, case.branch


# ---------------------------------------------------------------------------
# Grupo 2: ramas que dependen de resultados de tools (Fase 3, no implementada
# todavia) -- probadas a nivel de state machine pura, ver docstring del modulo
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StateMachineScenario:
    id: str
    branch: str
    current_state: LeadStage
    event: StateEvent
    expected_state_after: LeadStage
    empty_search_count: int = 0
    no_response_count: int = 0
    expected_changed_state: bool = True


STATE_MACHINE_GOLDEN_SCENARIOS: list[StateMachineScenario] = [
    # --- PROPERTY_SEARCH -> PRESENTING : results_found (3) -----------------
    StateMachineScenario(
        id="results_found_from_property_search",
        branch="PROPERTY_SEARCH -> PRESENTING : results_found",
        current_state=LeadStage.PROPERTY_SEARCH,
        event=StateEvent.RESULTS_FOUND,
        expected_state_after=LeadStage.PRESENTING,
    ),
    StateMachineScenario(
        id="results_found_resets_prior_empty_search_streak",
        branch="PROPERTY_SEARCH -> PRESENTING : results_found",
        current_state=LeadStage.PROPERTY_SEARCH,
        event=StateEvent.RESULTS_FOUND,
        expected_state_after=LeadStage.PRESENTING,
        empty_search_count=1,
    ),
    StateMachineScenario(
        id="results_found_from_property_search_no_prior_no_response",
        branch="PROPERTY_SEARCH -> PRESENTING : results_found",
        current_state=LeadStage.PROPERTY_SEARCH,
        event=StateEvent.RESULTS_FOUND,
        expected_state_after=LeadStage.PRESENTING,
        no_response_count=1,
    ),
    # --- PROPERTY_SEARCH -> DISCOVERING / HANDOFF : results_empty (3) -----
    StateMachineScenario(
        id="results_empty_first_time_returns_to_discovering",
        branch="PROPERTY_SEARCH -> DISCOVERING/HANDOFF : results_empty",
        current_state=LeadStage.PROPERTY_SEARCH,
        event=StateEvent.RESULTS_EMPTY,
        expected_state_after=LeadStage.DISCOVERING,
        empty_search_count=0,
    ),
    StateMachineScenario(
        id="results_empty_second_consecutive_escalates_to_handoff",
        branch="PROPERTY_SEARCH -> DISCOVERING/HANDOFF : results_empty",
        current_state=LeadStage.PROPERTY_SEARCH,
        event=StateEvent.RESULTS_EMPTY,
        expected_state_after=LeadStage.HANDOFF,
        empty_search_count=1,
    ),
    StateMachineScenario(
        id="results_empty_third_call_after_reset_starts_streak_over",
        branch="PROPERTY_SEARCH -> DISCOVERING/HANDOFF : results_empty",
        current_state=LeadStage.PROPERTY_SEARCH,
        event=StateEvent.RESULTS_EMPTY,
        expected_state_after=LeadStage.DISCOVERING,
        empty_search_count=0,  # simula que el criterio cambio (reset previo)
    ),
    # --- PRESENTING -> SCHEDULING : user_selects_property / wants_visit (3)
    StateMachineScenario(
        id="user_selects_property_from_presenting",
        branch="PRESENTING -> SCHEDULING : user_selects_property",
        current_state=LeadStage.PRESENTING,
        event=StateEvent.USER_SELECTS_PROPERTY,
        expected_state_after=LeadStage.SCHEDULING,
    ),
    StateMachineScenario(
        id="wants_visit_from_presenting",
        branch="PRESENTING -> SCHEDULING : wants_visit",
        current_state=LeadStage.PRESENTING,
        event=StateEvent.WANTS_VISIT,
        expected_state_after=LeadStage.SCHEDULING,
    ),
    StateMachineScenario(
        id="wants_visit_from_presenting_after_no_response_reminder",
        branch="PRESENTING -> SCHEDULING : wants_visit",
        current_state=LeadStage.PRESENTING,
        event=StateEvent.WANTS_VISIT,
        expected_state_after=LeadStage.SCHEDULING,
        no_response_count=1,
    ),
    # --- SCHEDULING -> BOOKED : meeting_confirmed (3) -----------------------
    StateMachineScenario(
        id="meeting_confirmed_from_scheduling",
        branch="SCHEDULING -> BOOKED : meeting_confirmed",
        current_state=LeadStage.SCHEDULING,
        event=StateEvent.MEETING_CONFIRMED,
        expected_state_after=LeadStage.BOOKED,
    ),
    StateMachineScenario(
        id="meeting_confirmed_resets_no_response_streak",
        branch="SCHEDULING -> BOOKED : meeting_confirmed",
        current_state=LeadStage.SCHEDULING,
        event=StateEvent.MEETING_CONFIRMED,
        expected_state_after=LeadStage.BOOKED,
        no_response_count=1,
    ),
    StateMachineScenario(
        id="meeting_confirmed_from_scheduling_clean_counters",
        branch="SCHEDULING -> BOOKED : meeting_confirmed",
        current_state=LeadStage.SCHEDULING,
        event=StateEvent.MEETING_CONFIRMED,
        expected_state_after=LeadStage.BOOKED,
    ),
    # --- SCHEDULING -> HANDOFF : calendar_error (3) -------------------------
    StateMachineScenario(
        id="calendar_error_from_scheduling",
        branch="SCHEDULING -> HANDOFF : calendar_error",
        current_state=LeadStage.SCHEDULING,
        event=StateEvent.CALENDAR_ERROR,
        expected_state_after=LeadStage.HANDOFF,
    ),
    StateMachineScenario(
        id="calendar_error_from_scheduling_after_reminder",
        branch="SCHEDULING -> HANDOFF : calendar_error",
        current_state=LeadStage.SCHEDULING,
        event=StateEvent.CALENDAR_ERROR,
        expected_state_after=LeadStage.HANDOFF,
        no_response_count=1,
    ),
    StateMachineScenario(
        id="calendar_error_from_scheduling_clean_counters",
        branch="SCHEDULING -> HANDOFF : calendar_error",
        current_state=LeadStage.SCHEDULING,
        event=StateEvent.CALENDAR_ERROR,
        expected_state_after=LeadStage.HANDOFF,
    ),
    # --- DISCOVERING -> NURTURE : no_response tras 2 recordatorios (3) -----
    StateMachineScenario(
        id="no_response_first_reminder_stays_in_discovering",
        branch="DISCOVERING -> NURTURE : no_response (umbral 2)",
        current_state=LeadStage.DISCOVERING,
        event=StateEvent.NO_RESPONSE,
        expected_state_after=LeadStage.DISCOVERING,
        no_response_count=0,
        expected_changed_state=False,
    ),
    StateMachineScenario(
        id="no_response_second_reminder_moves_to_nurture",
        branch="DISCOVERING -> NURTURE : no_response (umbral 2)",
        current_state=LeadStage.DISCOVERING,
        event=StateEvent.NO_RESPONSE,
        expected_state_after=LeadStage.NURTURE,
        no_response_count=1,
    ),
    StateMachineScenario(
        id="no_response_second_reminder_from_scheduling_moves_to_nurture",
        branch="DISCOVERING -> NURTURE : no_response (umbral 2)",
        current_state=LeadStage.SCHEDULING,
        event=StateEvent.NO_RESPONSE,
        expected_state_after=LeadStage.NURTURE,
        no_response_count=1,
    ),
]


@pytest.mark.parametrize("scenario", STATE_MACHINE_GOLDEN_SCENARIOS, ids=lambda s: s.id)
def test_state_machine_golden_scenario(scenario: StateMachineScenario) -> None:
    result = transition(
        scenario.current_state,
        scenario.event,
        empty_search_count=scenario.empty_search_count,
        no_response_count=scenario.no_response_count,
    )
    assert result.new_state == scenario.expected_state_after, scenario.branch
    assert result.changed_state == scenario.expected_changed_state, scenario.branch
