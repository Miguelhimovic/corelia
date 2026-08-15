"""Golden conversations de Fase 3 (SPEC.md seccion 9) -- ramas del state
machine que ahora SI ejecutan tools reales de `app/tools` a traves de
`handle_message()` (a diferencia de `tests/agent_engine/test_golden_conversations.py`,
que cubre Fase 2 con `process_incoming_message()` puro, sin tools).

Mismo formato que el resto del repo (ver docstring de
`test_golden_conversations.py` para por que se usan dataclasses de Python en
vez de YAML real: sin PyYAML como dependencia declarada). Cada
`ToolGoldenConversation.id` documenta el YAML conceptual equivalente al
formato de SPEC.md seccion 9 en su docstring de clase.

4 ramas cubiertas aqui, 3-5 casos cada una:
1. `QUALIFYING -> PROPERTY_SEARCH -> PRESENTING : results_found` (con
   `search_database()` real contra propiedades sembradas -- nunca inventadas).
2. `PROPERTY_SEARCH -> DISCOVERING : results_empty` (con `search_database()`
   real que no encuentra coincidencias).
3. `* -> HANDOFF : human_request` con `handoff_human()` REAL (crea
   `HumanHandoff` en la DB, no solo `TurnResult.action`).
4. `* -> LOST : not_interested` (sin tool de handoff, `Lead.stage=LOST` directo).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent_engine.orchestrator import ExecutedTurnResult, OrchestratorAction, handle_message
from app.models import HumanHandoff, Tenant
from app.models.enums import LeadStage
from tests.agent_engine.conftest import LeadConversationFactory
from tests.agent_engine.llm_test_doubles import FakeAsyncAnthropic, make_tool_use_response
from tests.conftest import PropertyFactory


def _run(coro):
    return asyncio.run(coro)


def _property_search_payload(
    *, location: str, budget_max: float, bedrooms: int, purpose: str, confidence: float
) -> dict[str, Any]:
    return {
        "intent": "property_search",
        "entities": {
            "location": location,
            "budget_max": budget_max,
            "bedrooms": bedrooms,
            "purpose": purpose,
        },
        "confidence": confidence,
        "requires_clarification": False,
    }


# ---------------------------------------------------------------------------
# Rama 1: QUALIFYING -> PROPERTY_SEARCH -> PRESENTING : results_found
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResultsFoundCase:
    id: str
    message: str
    location: str
    budget_max: float
    bedrooms: int
    purpose: str
    confidence: float
    property_kwargs: dict[str, Any] = field(default_factory=dict)


RESULTS_FOUND_CASES: list[ResultsFoundCase] = [
    # input: "Busco apartamento en Pinares, maximo 450 millones, 3 habitaciones, para vivir"
    # expected: {intent: property_search, state_after: PRESENTING, properties: [<real>]}
    ResultsFoundCase(
        id="results_found_pinares_residential",
        message="Busco apartamento en Pinares, maximo 450 millones, 3 habitaciones, para vivir",
        location="Pinares",
        budget_max=450_000_000,
        bedrooms=3,
        purpose="residential",
        confidence=0.92,
        property_kwargs={
            "city": "Pereira",
            "neighborhood": "Pinares",
            "price": Decimal("400000000"),
            "bedrooms": 3,
        },
    ),
    # input: "Apartamento en Laureles, 300 millones, 2 habitaciones, para invertir"
    # expected: {intent: property_search, state_after: PRESENTING, properties: [<real>]}
    ResultsFoundCase(
        id="results_found_laureles_investment",
        message="Apartamento en Laureles, 300 millones, 2 habitaciones, para invertir",
        location="Laureles",
        budget_max=300_000_000,
        bedrooms=2,
        purpose="investment",
        confidence=0.9,
        property_kwargs={
            "city": "Medellin",
            "neighborhood": "Laureles",
            "price": Decimal("280000000"),
            "bedrooms": 2,
            "purpose": "investment",
        },
    ),
    # input: "Casa en Envigado, 600 millones, 4 habitaciones, para vivir"
    # expected: {intent: property_search, state_after: PRESENTING, properties: [<real>]}
    ResultsFoundCase(
        id="results_found_envigado_more_bedrooms_than_requested",
        message="Casa en Envigado, 600 millones, 4 habitaciones, para vivir",
        location="Envigado",
        budget_max=600_000_000,
        bedrooms=4,
        purpose="residential",
        confidence=0.95,
        # 5 habitaciones (mas de las 4 pedidas) sigue siendo un match valido.
        property_kwargs={
            "city": "Medellin",
            "neighborhood": "Envigado",
            "price": Decimal("550000000"),
            "bedrooms": 5,
        },
    ),
]


@pytest.mark.parametrize("case", RESULTS_FOUND_CASES, ids=lambda c: c.id)
def test_results_found_golden_conversation(
    case: ResultsFoundCase,
    db_session: Session,
    default_tenant: Tenant,
    make_lead_conversation: LeadConversationFactory,
    make_property: PropertyFactory,
) -> None:
    matching = make_property(**case.property_kwargs)
    lead, conversation, _state = make_lead_conversation(current_state=LeadStage.DISCOVERING)

    client = FakeAsyncAnthropic(
        [
            make_tool_use_response(
                _property_search_payload(
                    location=case.location,
                    budget_max=case.budget_max,
                    bedrooms=case.bedrooms,
                    purpose=case.purpose,
                    confidence=case.confidence,
                )
            )
        ]
    )
    result: ExecutedTurnResult = _run(
        handle_message(
            db_session,
            message=case.message,
            conversation_id=conversation.id,
            lead_id=lead.id,
            llm_client=client,
        )
    )

    assert result.turn.action == OrchestratorAction.SEARCH_PROPERTIES
    assert result.final_state == LeadStage.PRESENTING
    assert result.properties is not None
    assert len(result.properties) >= 1
    assert matching.id in {p.id for p in result.properties}


# ---------------------------------------------------------------------------
# Rama 2: PROPERTY_SEARCH -> DISCOVERING : results_empty
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResultsEmptyCase:
    id: str
    message: str
    location: str
    budget_max: float
    bedrooms: int
    purpose: str
    confidence: float


RESULTS_EMPTY_CASES: list[ResultsEmptyCase] = [
    # input: "Busco en Marte, 100 millones, 1 habitacion, para vivir"
    # expected: {intent: property_search, state_after: DISCOVERING, properties: []}
    ResultsEmptyCase(
        id="results_empty_nonexistent_location",
        message="Busco en Marte, 100 millones, 1 habitacion, para vivir",
        location="Marte",
        budget_max=100_000_000,
        bedrooms=1,
        purpose="residential",
        confidence=0.9,
    ),
    # input: "Apartamento en Pinares, 50 millones, 1 habitacion, para vivir"
    # expected: {intent: property_search, state_after: DISCOVERING, properties: []}
    # (presupuesto demasiado bajo para cualquier propiedad real del catalogo demo)
    ResultsEmptyCase(
        id="results_empty_budget_too_low",
        message="Apartamento en Pinares, 50 millones, 1 habitacion, para vivir",
        location="Pinares",
        budget_max=50_000_000,
        bedrooms=1,
        purpose="residential",
        confidence=0.9,
    ),
    # input: "Apartamento en Pinares, 450 millones, 20 habitaciones, para vivir"
    # expected: {intent: property_search, state_after: DISCOVERING, properties: []}
    # (numero de habitaciones no realista, ninguna propiedad demo lo cumple)
    ResultsEmptyCase(
        id="results_empty_too_many_bedrooms",
        message="Apartamento en Pinares, 450 millones, 20 habitaciones, para vivir",
        location="Pinares",
        budget_max=450_000_000,
        bedrooms=20,
        purpose="residential",
        confidence=0.9,
    ),
]


@pytest.mark.parametrize("case", RESULTS_EMPTY_CASES, ids=lambda c: c.id)
def test_results_empty_golden_conversation(
    case: ResultsEmptyCase,
    db_session: Session,
    default_tenant: Tenant,
    make_lead_conversation: LeadConversationFactory,
    make_property: PropertyFactory,
) -> None:
    # Sembrado deliberadamente NO coincidente con ningun caso de arriba.
    make_property(city="Pereira", neighborhood="Pinares", price=Decimal("400000000"), bedrooms=3)

    lead, conversation, _state = make_lead_conversation(current_state=LeadStage.DISCOVERING)
    client = FakeAsyncAnthropic(
        [
            make_tool_use_response(
                _property_search_payload(
                    location=case.location,
                    budget_max=case.budget_max,
                    bedrooms=case.bedrooms,
                    purpose=case.purpose,
                    confidence=case.confidence,
                )
            )
        ]
    )
    result: ExecutedTurnResult = _run(
        handle_message(
            db_session,
            message=case.message,
            conversation_id=conversation.id,
            lead_id=lead.id,
            llm_client=client,
        )
    )

    assert result.turn.action == OrchestratorAction.SEARCH_PROPERTIES
    assert result.final_state == LeadStage.DISCOVERING
    assert result.properties == []


# ---------------------------------------------------------------------------
# Rama 2b: PROPERTY_SEARCH -> HANDOFF : results_empty (2da consecutiva)
#
# Corregido tras QA (SPEC.md seccion 1): el contador `empty_search_count`
# solo se resetea cuando el usuario CAMBIA alguno de los 4 criterios de
# busqueda entre intentos -- repetir los mismos criterios dos veces seguidas
# sin resultados si dispara HANDOFF. Antes del fix, esta rama era
# inalcanzable desde una conversacion real (ver docstring de
# `tests/agent_engine/test_handle_message.py`, clase
# `TestSecondConsecutiveEmptySearchReachesHandoff`, para el detalle).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConsecutiveEmptySearchCase:
    id: str
    message: str
    location: str
    budget_max: float
    bedrooms: int
    purpose: str
    confidence: float


CONSECUTIVE_EMPTY_SEARCH_CASES: list[ConsecutiveEmptySearchCase] = [
    # input turno 1 y turno 2 (identicos): "Busco en Marte, 100 millones, 1
    # habitacion, para vivir"
    # expected turno 1: {state_after: DISCOVERING, properties: []}
    # expected turno 2: {state_after: HANDOFF, properties: [], handoff: real}
    ConsecutiveEmptySearchCase(
        id="same_criteria_twice_nonexistent_location",
        message="Busco en Marte, 100 millones, 1 habitacion, para vivir",
        location="Marte",
        budget_max=100_000_000,
        bedrooms=1,
        purpose="residential",
        confidence=0.9,
    ),
]


@pytest.mark.parametrize("case", CONSECUTIVE_EMPTY_SEARCH_CASES, ids=lambda c: c.id)
def test_second_consecutive_empty_search_same_criteria_golden_conversation(
    case: ConsecutiveEmptySearchCase,
    db_session: Session,
    default_tenant: Tenant,
    make_lead_conversation: LeadConversationFactory,
    make_property: PropertyFactory,
) -> None:
    # Sembrado deliberadamente NO coincidente con el caso de arriba.
    make_property(city="Pereira", neighborhood="Pinares", price=Decimal("400000000"), bedrooms=3)

    lead, conversation, _state = make_lead_conversation(current_state=LeadStage.DISCOVERING)
    payload = _property_search_payload(
        location=case.location,
        budget_max=case.budget_max,
        bedrooms=case.bedrooms,
        purpose=case.purpose,
        confidence=case.confidence,
    )
    # Misma respuesta del LLM en ambos turnos: el usuario repite exactamente
    # los mismos 4 criterios.
    client = FakeAsyncAnthropic([make_tool_use_response(payload), make_tool_use_response(payload)])

    first: ExecutedTurnResult = _run(
        handle_message(
            db_session,
            message=case.message,
            conversation_id=conversation.id,
            lead_id=lead.id,
            llm_client=client,
        )
    )
    assert first.final_state == LeadStage.DISCOVERING
    assert first.properties == []

    second: ExecutedTurnResult = _run(
        handle_message(
            db_session,
            message=case.message,
            conversation_id=conversation.id,
            lead_id=lead.id,
            llm_client=client,
        )
    )

    assert second.turn.action == OrchestratorAction.SEARCH_PROPERTIES
    assert second.final_state == LeadStage.HANDOFF
    assert second.properties == []
    assert second.handoff_id is not None

    handoff = db_session.get(HumanHandoff, second.handoff_id)
    assert handoff is not None
    assert handoff.lead_id == lead.id
    assert handoff.reason == "empty_search_2x"

    db_session.refresh(lead)
    assert lead.stage == LeadStage.HANDOFF


# ---------------------------------------------------------------------------
# Rama 3: * -> HANDOFF : human_request, con handoff_human() REAL
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RealHandoffCase:
    id: str
    message: str
    initial_state: LeadStage


REAL_HANDOFF_CASES: list[RealHandoffCase] = [
    # input: "Quiero hablar con una persona"
    # expected: {intent: human_request, state_after: HANDOFF, tool: handoff_human (real)}
    RealHandoffCase(
        id="human_request_real_handoff_from_discovering",
        message="Quiero hablar con una persona",
        initial_state=LeadStage.DISCOVERING,
    ),
    # input: "Necesito hablar con un asesor humano"
    # expected: {intent: human_request, state_after: HANDOFF, tool: handoff_human (real)}
    RealHandoffCase(
        id="human_request_real_handoff_from_new",
        message="Necesito hablar con un asesor humano",
        initial_state=LeadStage.NEW,
    ),
    # input: "¿Puedo hablar con alguien?"
    # expected: {intent: human_request, state_after: HANDOFF, tool: handoff_human (real)}
    RealHandoffCase(
        id="human_request_real_handoff_from_presenting",
        message="¿Puedo hablar con alguien?",
        initial_state=LeadStage.PRESENTING,
    ),
    # input: "Pasame con un agente humano"
    # expected: {intent: human_request, state_after: HANDOFF, tool: handoff_human (real)}
    RealHandoffCase(
        id="human_request_real_handoff_from_scheduling",
        message="Pasame con un agente humano",
        initial_state=LeadStage.SCHEDULING,
    ),
]


@pytest.mark.parametrize("case", REAL_HANDOFF_CASES, ids=lambda c: c.id)
def test_human_request_real_handoff_golden_conversation(
    case: RealHandoffCase,
    db_session: Session,
    make_lead_conversation: LeadConversationFactory,
) -> None:
    lead, conversation, _state = make_lead_conversation(current_state=case.initial_state)

    result: ExecutedTurnResult = _run(
        handle_message(
            db_session,
            message=case.message,
            conversation_id=conversation.id,
            lead_id=lead.id,
        )
    )

    assert result.turn.action == OrchestratorAction.OFFER_HANDOFF
    assert result.final_state == LeadStage.HANDOFF
    assert result.handoff_id is not None

    # Verificacion de que el tool REAL se ejecuto -- no solo la senal de
    # `TurnResult.action` (esa parte ya la cubre Fase 2).
    handoff = db_session.get(HumanHandoff, result.handoff_id)
    assert handoff is not None
    assert handoff.lead_id == lead.id
    assert handoff.status.value == "open"
    assert handoff.assigned_to is None

    db_session.refresh(lead)
    assert lead.stage == LeadStage.HANDOFF


# ---------------------------------------------------------------------------
# Rama 4: * -> LOST : not_interested (sin tool de handoff)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LostCase:
    id: str
    message: str
    initial_state: LeadStage


LOST_CASES: list[LostCase] = [
    # input: "Ya no me interesa"
    # expected: {intent: not_interested, state_after: LOST}
    LostCase(
        id="not_interested_lost_from_discovering",
        message="Ya no me interesa",
        initial_state=LeadStage.DISCOVERING,
    ),
    # input: "No, gracias"
    # expected: {intent: not_interested, state_after: LOST}
    LostCase(
        id="not_interested_lost_from_presenting",
        message="No, gracias",
        initial_state=LeadStage.PRESENTING,
    ),
    # input: "No quiero continuar"
    # expected: {intent: not_interested, state_after: LOST}
    LostCase(
        id="not_interested_lost_from_scheduling",
        message="No quiero continuar",
        initial_state=LeadStage.SCHEDULING,
    ),
    # input: "Dejalo asi"
    # expected: {intent: not_interested, state_after: LOST}
    LostCase(
        id="not_interested_lost_from_property_search",
        message="Dejalo asi",
        initial_state=LeadStage.PROPERTY_SEARCH,
    ),
]


@pytest.mark.parametrize("case", LOST_CASES, ids=lambda c: c.id)
def test_not_interested_lost_golden_conversation(
    case: LostCase,
    db_session: Session,
    make_lead_conversation: LeadConversationFactory,
) -> None:
    lead, conversation, _state = make_lead_conversation(current_state=case.initial_state)

    result: ExecutedTurnResult = _run(
        handle_message(
            db_session,
            message=case.message,
            conversation_id=conversation.id,
            lead_id=lead.id,
        )
    )

    assert result.turn.action == OrchestratorAction.MARK_LOST
    assert result.handoff_id is None

    db_session.refresh(lead)
    assert lead.stage == LeadStage.LOST

    handoffs = db_session.execute(
        select(HumanHandoff).where(HumanHandoff.lead_id == lead.id)
    ).scalars().all()
    assert handoffs == []
