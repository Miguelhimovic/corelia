"""Unit tests de `handle_message()` (Fase 3, Tarea 6) -- el entrypoint que
conecta `process_incoming_message()` (Fase 2) con las tools reales de
`app/tools` (`create_lead`, `update_lead`, `search_database`,
`handoff_human`).

Usa `db_session` (rollback por test) contra Postgres real, `default_tenant`/
`make_property` (`tests/conftest.py`, tenant fijo `DEFAULT_TENANT_ID`) para
las tools que dependen de ese FK, y `make_lead_conversation`
(`tests/agent_engine/conftest.py`) para simular una conversacion ya
existente sin pasar por `create_lead()`.

**Fix post-QA documentado** (ver clases `TestSecondConsecutiveEmptySearchReachesHandoff`
y `TestCriteriaChangeResetsEmptySearchCounter` mas abajo): la rama de
SPEC.md seccion 2 "2 busquedas vacias seguidas -> HANDOFF"
(`PROPERTY_SEARCH -> HANDOFF`) era antes de este fix inalcanzable desde una
conversacion real de usuario -- `_EMPTY_SEARCH_RESET_EVENTS` en
`state_machine.py` reseteaba `empty_search_count` a 0 en cada evento
`ENOUGH_DATA` sin importar si el usuario habia cambiado algun criterio, y
`SEARCH_PROPERTIES` siempre se dispara justo despues de `ENOUGH_DATA`. Se
corrigio quitando `ENOUGH_DATA` de `_EMPTY_SEARCH_RESET_EVENTS` (la funcion
pura `transition()` ya no decide el reset por si sola) y moviendo esa
decision al orquestador (`orchestrator.py`, `_run_property_search`/
`criteria_changed`), que compara los 4 slots contra los que el `Lead` tenia
persistidos antes de `update_lead()` este turno. Ambas ramas (HANDOFF cuando
los criterios se repiten, DISCOVERING con contador reseteado cuando cambian)
se ejercitan aqui end-to-end via `handle_message()`, sin llamar funciones
privadas directamente con el contador manipulado a mano.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.agent_engine.orchestrator as orchestrator_module
from app.agent_engine.orchestrator import (
    _TECHNICAL_ERROR_MESSAGE,
    OrchestratorAction,
    ToolExecutionError,
    handle_message,
)
from app.models import Conversation, ConversationState, HumanHandoff, Lead, Message, Tenant
from app.models.enums import LeadPurpose, LeadStage, MessageRole
from app.tools.errors import LeadPersistenceError, PropertySearchError
from tests.agent_engine.conftest import LeadConversationFactory
from tests.agent_engine.llm_test_doubles import FakeAsyncAnthropic, make_tool_use_response
from tests.conftest import PropertyFactory


def _run(coro):
    return asyncio.run(coro)


class TestHandleMessageCreatesLead:
    def test_first_message_creates_lead_conversation_and_message(
        self, db_session: Session, default_tenant: Tenant
    ) -> None:
        payload = {
            "intent": "other",
            "entities": {
                "location": None,
                "budget_max": None,
                "bedrooms": None,
                "purpose": None,
            },
            "confidence": 0.9,
            "requires_clarification": False,
        }
        client = FakeAsyncAnthropic([make_tool_use_response(payload)])
        result = _run(
            handle_message(
                db_session,
                message="Hola, quiero informacion",
                channel="web",
                source="landing_real_estate",
                llm_client=client,
            )
        )
        lead = db_session.get(Lead, result.turn.lead_id)
        conversation = db_session.get(Conversation, result.turn.conversation_id)
        message = db_session.get(Message, result.turn.message_id)

        assert lead is not None
        assert lead.tenant_id == default_tenant.id
        assert conversation is not None
        assert conversation.lead_id == lead.id
        assert message is not None
        assert message.role == MessageRole.USER
        assert message.content == "Hola, quiero informacion"

    def test_missing_channel_raises_value_error(
        self, db_session: Session, default_tenant: Tenant
    ) -> None:
        with pytest.raises(ValueError, match="channel"):
            _run(handle_message(db_session, message="hola", source="landing_real_estate"))

    def test_missing_source_raises_value_error(
        self, db_session: Session, default_tenant: Tenant
    ) -> None:
        with pytest.raises(ValueError, match="channel"):
            _run(handle_message(db_session, message="hola", channel="web"))

    def test_partial_conversation_and_lead_ids_raises_value_error(
        self, db_session: Session, default_tenant: Tenant
    ) -> None:
        with pytest.raises(ValueError):
            _run(
                handle_message(
                    db_session, message="hola", conversation_id=uuid.uuid4(), lead_id=None
                )
            )

    def test_create_lead_persistence_error_reraises_without_handoff(
        self,
        db_session: Session,
        default_tenant: Tenant,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _raise_lead_persistence_error(*args: object, **kwargs: object) -> None:
            raise LeadPersistenceError("simulated PostgreSQL failure")

        monkeypatch.setattr(orchestrator_module, "tool_create_lead", _raise_lead_persistence_error)

        # No hay lead_id todavia (FK obligatoria de HumanHandoff) -- se
        # relanza tal cual, no se envuelve en ToolExecutionError.
        with pytest.raises(LeadPersistenceError):
            _run(
                handle_message(
                    db_session,
                    message="hola",
                    channel="web",
                    source="landing_real_estate",
                )
            )


class TestHandleMessageUpdateLead:
    def test_new_entities_from_llm_are_persisted_via_update_lead(
        self, db_session: Session, make_lead_conversation: LeadConversationFactory
    ) -> None:
        lead, conversation, _state = make_lead_conversation(current_state=LeadStage.DISCOVERING)
        payload = {
            "intent": "property_search",
            "entities": {
                "location": "Pinares",
                "budget_max": None,
                "bedrooms": None,
                "purpose": None,
            },
            "confidence": 0.8,
            "requires_clarification": False,
        }
        client = FakeAsyncAnthropic([make_tool_use_response(payload)])
        _run(
            handle_message(
                db_session,
                message="Busco en Pinares",
                conversation_id=conversation.id,
                lead_id=lead.id,
                llm_client=client,
            )
        )
        db_session.refresh(lead)
        assert lead.location == "Pinares"

    def test_no_new_entities_does_not_call_update_lead(
        self,
        db_session: Session,
        make_lead_conversation: LeadConversationFactory,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        lead, conversation, _state = make_lead_conversation(current_state=LeadStage.DISCOVERING)

        def _fail_if_called(*args: object, **kwargs: object) -> None:
            raise AssertionError("update_lead no deberia llamarse sin entities nuevas")

        monkeypatch.setattr(orchestrator_module, "tool_update_lead", _fail_if_called)

        result = _run(
            handle_message(
                db_session,
                message="Quiero hablar con un asesor",  # human_request, sin entities
                conversation_id=conversation.id,
                lead_id=lead.id,
            )
        )
        assert result.turn.action == OrchestratorAction.OFFER_HANDOFF

    def test_lead_update_persistence_error_triggers_fail_safe_handoff(
        self,
        db_session: Session,
        make_lead_conversation: LeadConversationFactory,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        lead, conversation, _state = make_lead_conversation(current_state=LeadStage.DISCOVERING)
        payload = {
            "intent": "property_search",
            "entities": {
                "location": "Pinares",
                "budget_max": None,
                "bedrooms": None,
                "purpose": None,
            },
            "confidence": 0.8,
            "requires_clarification": False,
        }
        client = FakeAsyncAnthropic([make_tool_use_response(payload)])

        def _raise_lead_persistence_error(*args: object, **kwargs: object) -> None:
            raise LeadPersistenceError("simulated PostgreSQL failure")

        monkeypatch.setattr(orchestrator_module, "tool_update_lead", _raise_lead_persistence_error)

        result = _run(
            handle_message(
                db_session,
                message="Busco en Pinares",
                conversation_id=conversation.id,
                lead_id=lead.id,
                llm_client=client,
            )
        )
        assert result.technical_error is True
        assert result.technical_error_message == _TECHNICAL_ERROR_MESSAGE
        assert result.final_state == LeadStage.HANDOFF
        assert result.handoff_id is not None


class TestHandleMessagePropertySearch:
    def test_search_with_results_transitions_to_presenting_with_real_properties(
        self,
        db_session: Session,
        default_tenant: Tenant,
        make_lead_conversation: LeadConversationFactory,
        make_property: PropertyFactory,
    ) -> None:
        matching = make_property(
            city="Pereira",
            neighborhood="Pinares",
            price=Decimal("400000000"),
            bedrooms=3,
            purpose=LeadPurpose.RESIDENTIAL,
        )
        # No deberia calificar (menos habitaciones de las pedidas).
        make_property(
            city="Pereira",
            neighborhood="Pinares",
            price=Decimal("300000000"),
            bedrooms=1,
            purpose=LeadPurpose.RESIDENTIAL,
        )

        lead, conversation, _state = make_lead_conversation(current_state=LeadStage.DISCOVERING)
        payload = {
            "intent": "property_search",
            "entities": {
                "location": "Pinares",
                "budget_max": 450_000_000,
                "bedrooms": 3,
                "purpose": "residential",
            },
            "confidence": 0.92,
            "requires_clarification": False,
        }
        client = FakeAsyncAnthropic([make_tool_use_response(payload)])
        result = _run(
            handle_message(
                db_session,
                message="Busco apto en Pinares, 450 millones, 3 habitaciones, para vivir",
                conversation_id=conversation.id,
                lead_id=lead.id,
                llm_client=client,
            )
        )
        assert result.final_state == LeadStage.PRESENTING
        assert result.properties is not None
        assert [p.id for p in result.properties] == [matching.id]
        # Regla dura CLAUDE.md/SPEC.md seccion 14: el LLM presenta SOLO lo
        # que devuelve search_database -- nunca una propiedad inventada.
        for prop in result.properties:
            assert prop.id in {matching.id}

        state_row = db_session.execute(
            select(ConversationState).where(ConversationState.conversation_id == conversation.id)
        ).scalar_one()
        assert state_row.current_state == LeadStage.PRESENTING

    def test_search_no_results_transitions_back_to_discovering_and_increments_counter(
        self,
        db_session: Session,
        default_tenant: Tenant,
        make_lead_conversation: LeadConversationFactory,
        make_property: PropertyFactory,
    ) -> None:
        # Ninguna propiedad sembrada coincide con "Marte".
        make_property(city="Pereira", neighborhood="Pinares")

        lead, conversation, _state = make_lead_conversation(current_state=LeadStage.DISCOVERING)
        payload = {
            "intent": "property_search",
            "entities": {
                "location": "Marte",
                "budget_max": 100_000_000,
                "bedrooms": 1,
                "purpose": "residential",
            },
            "confidence": 0.9,
            "requires_clarification": False,
        }
        client = FakeAsyncAnthropic([make_tool_use_response(payload)])
        result = _run(
            handle_message(
                db_session,
                message="Busco en Marte, 100 millones, 1 habitacion, para vivir",
                conversation_id=conversation.id,
                lead_id=lead.id,
                llm_client=client,
            )
        )
        assert result.final_state == LeadStage.DISCOVERING
        assert result.properties == []

        state_row = db_session.execute(
            select(ConversationState).where(ConversationState.conversation_id == conversation.id)
        ).scalar_one()
        assert state_row.current_state == LeadStage.DISCOVERING
        assert state_row.empty_search_count == 1

    def test_property_search_error_triggers_fail_safe_handoff(
        self,
        db_session: Session,
        default_tenant: Tenant,
        make_lead_conversation: LeadConversationFactory,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        lead, conversation, _state = make_lead_conversation(current_state=LeadStage.DISCOVERING)
        payload = {
            "intent": "property_search",
            "entities": {
                "location": "Pinares",
                "budget_max": 450_000_000,
                "bedrooms": 3,
                "purpose": "residential",
            },
            "confidence": 0.9,
            "requires_clarification": False,
        }
        client = FakeAsyncAnthropic([make_tool_use_response(payload)])

        def _raise_property_search_error(*args: object, **kwargs: object) -> None:
            raise PropertySearchError("simulated PostgreSQL failure")

        monkeypatch.setattr(
            orchestrator_module, "tool_search_database", _raise_property_search_error
        )

        result = _run(
            handle_message(
                db_session,
                message="Busco apto en Pinares, 450 millones, 3 habitaciones, para vivir",
                conversation_id=conversation.id,
                lead_id=lead.id,
                llm_client=client,
            )
        )
        assert result.technical_error is True
        assert result.technical_error_message == _TECHNICAL_ERROR_MESSAGE
        assert result.final_state == LeadStage.HANDOFF
        assert result.handoff_id is not None


class TestSecondConsecutiveEmptySearchReachesHandoff:
    """SPEC.md seccion 2: `PROPERTY_SEARCH -> HANDOFF` tras 2 `results_empty`
    consecutivos CON LOS MISMOS 4 criterios de busqueda (SPEC.md seccion 1:
    el contador solo se resetea si el usuario cambia un criterio). Corregido
    tras QA -- ver docstring del modulo. Se ejercita end-to-end via
    `handle_message()` con dos turnos reales, sin manipular contadores a
    mano ni llamar `_run_property_search` directamente.
    """

    def test_same_criteria_two_empty_searches_reaches_handoff(
        self,
        db_session: Session,
        default_tenant: Tenant,
        make_lead_conversation: LeadConversationFactory,
        make_property: PropertyFactory,
    ) -> None:
        make_property(city="Pereira", neighborhood="Pinares")  # no coincide con "Marte"

        lead, conversation, _state = make_lead_conversation(current_state=LeadStage.DISCOVERING)
        payload = {
            "intent": "property_search",
            "entities": {
                "location": "Marte",
                "budget_max": 100_000_000,
                "bedrooms": 1,
                "purpose": "residential",
            },
            "confidence": 0.9,
            "requires_clarification": False,
        }
        # Dos respuestas identicas en la cola: el usuario repite los mismos
        # 4 criterios en el segundo turno.
        client = FakeAsyncAnthropic(
            [make_tool_use_response(payload), make_tool_use_response(payload)]
        )

        first = _run(
            handle_message(
                db_session,
                message="Busco en Marte, 100 millones, 1 habitacion, para vivir",
                conversation_id=conversation.id,
                lead_id=lead.id,
                llm_client=client,
            )
        )
        assert first.final_state == LeadStage.DISCOVERING
        assert first.properties == []

        state_row = db_session.execute(
            select(ConversationState).where(ConversationState.conversation_id == conversation.id)
        ).scalar_one()
        assert state_row.current_state == LeadStage.DISCOVERING
        assert state_row.empty_search_count == 1

        second = _run(
            handle_message(
                db_session,
                message="Busco en Marte, 100 millones, 1 habitacion, para vivir",
                conversation_id=conversation.id,
                lead_id=lead.id,
                llm_client=client,
            )
        )

        assert second.final_state == LeadStage.HANDOFF
        assert second.properties == []
        assert second.handoff_id is not None

        db_session.refresh(lead)
        assert lead.stage == LeadStage.HANDOFF

        state_row = db_session.execute(
            select(ConversationState).where(ConversationState.conversation_id == conversation.id)
        ).scalar_one()
        assert state_row.current_state == LeadStage.HANDOFF
        assert state_row.empty_search_count == 0

        handoffs = db_session.execute(
            select(HumanHandoff).where(HumanHandoff.lead_id == lead.id)
        ).scalars().all()
        assert len(handoffs) == 1
        assert handoffs[0].reason == "empty_search_2x"


class TestCriteriaChangeResetsEmptySearchCounter:
    """SPEC.md seccion 1: complemento del fix de arriba -- confirma que el
    reset legitimo por "cambio de criterio" sigue funcionando (no solo se
    arreglo la rama de HANDOFF, sino que no se rompio el reset)."""

    def test_changed_budget_between_attempts_resets_counter_stays_in_discovering(
        self,
        db_session: Session,
        default_tenant: Tenant,
        make_lead_conversation: LeadConversationFactory,
        make_property: PropertyFactory,
    ) -> None:
        make_property(city="Pereira", neighborhood="Pinares")  # no coincide con "Marte"

        lead, conversation, _state = make_lead_conversation(current_state=LeadStage.DISCOVERING)
        first_payload = {
            "intent": "property_search",
            "entities": {
                "location": "Marte",
                "budget_max": 100_000_000,
                "bedrooms": 1,
                "purpose": "residential",
            },
            "confidence": 0.9,
            "requires_clarification": False,
        }
        # Segundo intento: el usuario sube el presupuesto -- criterio cambia.
        second_payload = {
            "intent": "property_search",
            "entities": {
                "location": "Marte",
                "budget_max": 150_000_000,
                "bedrooms": 1,
                "purpose": "residential",
            },
            "confidence": 0.9,
            "requires_clarification": False,
        }
        client = FakeAsyncAnthropic(
            [make_tool_use_response(first_payload), make_tool_use_response(second_payload)]
        )

        first = _run(
            handle_message(
                db_session,
                message="Busco en Marte, 100 millones, 1 habitacion, para vivir",
                conversation_id=conversation.id,
                lead_id=lead.id,
                llm_client=client,
            )
        )
        assert first.final_state == LeadStage.DISCOVERING

        state_row = db_session.execute(
            select(ConversationState).where(ConversationState.conversation_id == conversation.id)
        ).scalar_one()
        assert state_row.empty_search_count == 1

        second = _run(
            handle_message(
                db_session,
                message="Mejor hasta 150 millones",
                conversation_id=conversation.id,
                lead_id=lead.id,
                llm_client=client,
            )
        )

        assert second.final_state == LeadStage.DISCOVERING
        assert second.properties == []

        state_row = db_session.execute(
            select(ConversationState).where(ConversationState.conversation_id == conversation.id)
        ).scalar_one()
        assert state_row.current_state == LeadStage.DISCOVERING
        # Se reseteo a 0 por el cambio de presupuesto y volvio a subir a 1
        # (no a 2) -- sin este reset legitimo, este segundo intento vacio
        # dispararia HANDOFF incorrectamente.
        assert state_row.empty_search_count == 1

        handoffs = db_session.execute(
            select(HumanHandoff).where(HumanHandoff.lead_id == lead.id)
        ).scalars().all()
        assert handoffs == []


class TestHandleMessageHandoffAndLost:
    def test_human_request_triggers_real_handoff_human_tool(
        self, db_session: Session, make_lead_conversation: LeadConversationFactory
    ) -> None:
        lead, conversation, _state = make_lead_conversation(current_state=LeadStage.DISCOVERING)
        result = _run(
            handle_message(
                db_session,
                message="Quiero hablar con un asesor",
                conversation_id=conversation.id,
                lead_id=lead.id,
            )
        )
        assert result.final_state == LeadStage.HANDOFF
        assert result.handoff_id is not None

        handoff = db_session.get(HumanHandoff, result.handoff_id)
        assert handoff is not None
        assert handoff.lead_id == lead.id

        db_session.refresh(lead)
        assert lead.stage == LeadStage.HANDOFF

    def test_not_interested_marks_lead_lost_without_calling_handoff_tool(
        self, db_session: Session, make_lead_conversation: LeadConversationFactory
    ) -> None:
        lead, conversation, _state = make_lead_conversation(current_state=LeadStage.DISCOVERING)
        result = _run(
            handle_message(
                db_session,
                message="Ya no me interesa",
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

    def test_handoff_human_failure_raises_tool_execution_error_no_infinite_loop(
        self,
        db_session: Session,
        make_lead_conversation: LeadConversationFactory,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        lead, conversation, _state = make_lead_conversation(current_state=LeadStage.DISCOVERING)
        call_count = {"n": 0}

        def _raise_lead_persistence_error(*args: object, **kwargs: object) -> None:
            call_count["n"] += 1
            raise LeadPersistenceError("simulated PostgreSQL failure")

        monkeypatch.setattr(
            orchestrator_module, "tool_handoff_human", _raise_lead_persistence_error
        )

        with pytest.raises(ToolExecutionError):
            _run(
                handle_message(
                    db_session,
                    message="Quiero hablar con un asesor",
                    conversation_id=conversation.id,
                    lead_id=lead.id,
                )
            )
        # Fail-safe critico sin reintentos ni loop: se llamo exactamente una vez.
        assert call_count["n"] == 1
