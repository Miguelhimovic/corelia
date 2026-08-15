"""Unit tests del orquestador del turno (SPEC.md secciones 1, 2, 3, 7).

Usa `db_session` (rollback por test, `tests/conftest.py`) contra Postgres
real y un `AsyncAnthropic` mockeado (`tests/agent_engine/llm_test_doubles.py`)
— nunca llama a la API real. Los escenarios "verificados manualmente" que
`engineer` menciona en su memoria de agente (`.claude/agent-memory/engineer/
project_agent_engine_orchestrator.md`) se convierten aqui en tests
automatizados de verdad.

Las golden conversations completas (formato YAML de SPEC.md seccion 9) viven
en `tests/agent_engine/golden/` y se corren desde
`tests/agent_engine/test_golden_conversations.py` — este archivo cubre casos
unitarios adicionales del orquestador (errores, persistencia, merge de
entities) que no encajan en el formato de golden conversation.
"""

import asyncio
import uuid

import pytest
import sqlalchemy.exc
from sqlalchemy.orm import Session

from app.agent_engine.orchestrator import (
    ConversationNotFoundError,
    LeadConversationMismatchError,
    OrchestratorAction,
    OrchestratorPersistenceError,
    process_incoming_message,
)
from app.models.enums import LeadPurpose, LeadStage, MessageRole
from tests.agent_engine.conftest import LeadConversationFactory
from tests.agent_engine.llm_test_doubles import FakeAsyncAnthropic, make_tool_use_response


def _run(coro):
    return asyncio.run(coro)


class TestNotFoundGuards:
    def test_unknown_conversation_id_raises(
        self, db_session: Session, make_lead_conversation: LeadConversationFactory
    ) -> None:
        lead, _conversation, _state = make_lead_conversation()
        with pytest.raises(ConversationNotFoundError):
            _run(
                process_incoming_message(
                    db_session,
                    conversation_id=uuid.uuid4(),
                    lead_id=lead.id,
                    message="hola",
                )
            )

    def test_unknown_lead_id_with_valid_conversation_raises_mismatch_not_lead_not_found(
        self, db_session: Session, make_lead_conversation: LeadConversationFactory
    ) -> None:
        # conversation.lead_id no coincide con un lead_id inexistente ->
        # el orquestador valida conversation.lead_id != lead_id ANTES de
        # buscar el Lead, por lo que el error es de mismatch, no de "lead no
        # existe" (ver orden de validaciones en process_incoming_message).
        _lead, conversation, _state = make_lead_conversation()
        with pytest.raises(LeadConversationMismatchError):
            _run(
                process_incoming_message(
                    db_session,
                    conversation_id=conversation.id,
                    lead_id=uuid.uuid4(),
                    message="hola",
                )
            )

    def test_conversation_lead_mismatch_raises(
        self, db_session: Session, make_lead_conversation: LeadConversationFactory
    ) -> None:
        _lead_a, conversation_a, _state_a = make_lead_conversation()
        lead_b, _conversation_b, _state_b = make_lead_conversation()
        with pytest.raises(LeadConversationMismatchError):
            _run(
                process_incoming_message(
                    db_session,
                    conversation_id=conversation_a.id,
                    lead_id=lead_b.id,
                    message="hola",
                )
            )


class TestMessagePersistence:
    def test_incoming_message_is_persisted_with_user_role(
        self, db_session: Session, make_lead_conversation: LeadConversationFactory
    ) -> None:
        lead, conversation, _state = make_lead_conversation(current_state=LeadStage.DISCOVERING)
        result = _run(
            process_incoming_message(
                db_session,
                conversation_id=conversation.id,
                lead_id=lead.id,
                message="Quiero hablar con un asesor",
            )
        )
        from app.models import Message

        message_row = db_session.get(Message, result.message_id)
        assert message_row is not None
        assert message_row.role == MessageRole.USER
        assert message_row.content == "Quiero hablar con un asesor"
        assert message_row.conversation_id == conversation.id


class TestUniversalTransitions:
    @pytest.mark.parametrize(
        "current_state",
        [
            LeadStage.NEW,
            LeadStage.DISCOVERING,
            LeadStage.PRESENTING,
            LeadStage.SCHEDULING,
            LeadStage.BOOKED,
        ],
    )
    def test_human_request_always_goes_to_handoff(
        self,
        db_session: Session,
        make_lead_conversation: LeadConversationFactory,
        current_state: LeadStage,
    ) -> None:
        lead, conversation, _state = make_lead_conversation(current_state=current_state)
        result = _run(
            process_incoming_message(
                db_session,
                conversation_id=conversation.id,
                lead_id=lead.id,
                message="Quiero hablar con una persona",
            )
        )
        assert result.new_state == LeadStage.HANDOFF
        assert result.action == OrchestratorAction.OFFER_HANDOFF
        assert result.handoff_reason == "human_request_explicit"
        assert result.previous_state == current_state

    @pytest.mark.parametrize(
        "current_state",
        [
            LeadStage.DISCOVERING,
            LeadStage.PRESENTING,
            LeadStage.SCHEDULING,
            LeadStage.PROPERTY_SEARCH,
        ],
    )
    def test_not_interested_always_goes_to_lost(
        self,
        db_session: Session,
        make_lead_conversation: LeadConversationFactory,
        current_state: LeadStage,
    ) -> None:
        lead, conversation, _state = make_lead_conversation(current_state=current_state)
        result = _run(
            process_incoming_message(
                db_session,
                conversation_id=conversation.id,
                lead_id=lead.id,
                message="Ya no me interesa",
            )
        )
        assert result.new_state == LeadStage.LOST
        assert result.action == OrchestratorAction.MARK_LOST
        assert result.handoff_reason is None


class TestCancelBranch:
    def test_cancel_with_booked_meeting_goes_to_handoff_with_specific_reason(
        self, db_session: Session, make_lead_conversation: LeadConversationFactory
    ) -> None:
        lead, conversation, _state = make_lead_conversation(current_state=LeadStage.BOOKED)
        result = _run(
            process_incoming_message(
                db_session,
                conversation_id=conversation.id,
                lead_id=lead.id,
                message="Necesito cancelar mi cita",
            )
        )
        assert result.new_state == LeadStage.HANDOFF
        assert result.handoff_reason == "cancellation_with_meeting_booked"

    def test_cancel_without_booked_meeting_goes_to_handoff_with_different_reason(
        self, db_session: Session, make_lead_conversation: LeadConversationFactory
    ) -> None:
        lead, conversation, _state = make_lead_conversation(current_state=LeadStage.DISCOVERING)
        result = _run(
            process_incoming_message(
                db_session,
                conversation_id=conversation.id,
                lead_id=lead.id,
                message="Quiero cancelar mi cita",
            )
        )
        assert result.new_state == LeadStage.HANDOFF
        assert result.handoff_reason == "cancel_without_scheduled_meeting"


class TestPropertySearchBranch:
    def test_full_slots_high_confidence_from_discovering_advances_to_property_search(
        self, db_session: Session, make_lead_conversation: LeadConversationFactory
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
        result = _run(
            process_incoming_message(
                db_session,
                conversation_id=conversation.id,
                lead_id=lead.id,
                message="Busco apto en Pinares, 450 millones, 3 habitaciones, para vivir",
                llm_client=client,
            )
        )
        assert result.new_state == LeadStage.PROPERTY_SEARCH
        assert result.action == OrchestratorAction.SEARCH_PROPERTIES
        assert result.merged_entities.location == "Pinares"
        assert result.merged_entities.purpose == LeadPurpose.RESIDENTIAL
        assert result.state_changed is True

    def test_new_lead_first_message_with_full_slots_advances_in_a_single_turn(
        self, db_session: Session, make_lead_conversation: LeadConversationFactory
    ) -> None:
        # NEW -> DISCOVERING (bootstrap) -> QUALIFYING -> PROPERTY_SEARCH
        # (automatico) en UN SOLO turno, igual que el golden conversation de
        # SPEC.md seccion 9.
        lead, conversation, _state = make_lead_conversation(current_state=LeadStage.NEW)
        payload = {
            "intent": "property_search",
            "entities": {
                "location": "Pinares",
                "budget_max": 450_000_000,
                "bedrooms": 3,
                "purpose": "residential",
            },
            "confidence": 0.95,
            "requires_clarification": False,
        }
        client = FakeAsyncAnthropic([make_tool_use_response(payload)])
        result = _run(
            process_incoming_message(
                db_session,
                conversation_id=conversation.id,
                lead_id=lead.id,
                message=(
                    "Busco apartamento en Pinares, maximo 450 millones, 3 habitaciones, para vivir"
                ),
                llm_client=client,
            )
        )
        assert result.previous_state == LeadStage.NEW
        assert result.new_state == LeadStage.PROPERTY_SEARCH
        assert result.action == OrchestratorAction.SEARCH_PROPERTIES

    def test_partial_slots_from_discovering_requests_more_info_without_advancing(
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
        result = _run(
            process_incoming_message(
                db_session,
                conversation_id=conversation.id,
                lead_id=lead.id,
                message="Busco en Pinares",
                llm_client=client,
            )
        )
        assert result.new_state == LeadStage.DISCOVERING
        assert result.state_changed is False
        assert result.action == OrchestratorAction.REQUEST_MORE_INFO
        assert result.merged_entities.location == "Pinares"
        assert result.merged_entities.budget_max is None

    def test_low_confidence_below_threshold_requests_more_info_even_with_full_slots(
        self, db_session: Session, make_lead_conversation: LeadConversationFactory
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
            "confidence": 0.69,
            "requires_clarification": False,
        }
        client = FakeAsyncAnthropic([make_tool_use_response(payload)])
        result = _run(
            process_incoming_message(
                db_session,
                conversation_id=conversation.id,
                lead_id=lead.id,
                message="Busco en Pinares, 450 millones, 3 habitaciones, para vivir",
                llm_client=client,
            )
        )
        assert result.new_state == LeadStage.DISCOVERING
        assert result.action == OrchestratorAction.REQUEST_MORE_INFO

    def test_entities_merge_across_two_turns_completes_slots_and_advances(
        self, db_session: Session, make_lead_conversation: LeadConversationFactory
    ) -> None:
        lead, conversation, _state = make_lead_conversation(current_state=LeadStage.DISCOVERING)

        turn1_payload = {
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
        client1 = FakeAsyncAnthropic([make_tool_use_response(turn1_payload)])
        turn1 = _run(
            process_incoming_message(
                db_session,
                conversation_id=conversation.id,
                lead_id=lead.id,
                message="Busco en Pinares",
                llm_client=client1,
            )
        )
        assert turn1.new_state == LeadStage.DISCOVERING
        assert turn1.action == OrchestratorAction.REQUEST_MORE_INFO

        # Fase 3 (update_lead) persistiria turn1.merged_entities en el Lead;
        # se simula aqui a mano porque esta tarea no incluye ese tool.
        lead.location = turn1.merged_entities.location
        db_session.flush()

        turn2_payload = {
            "intent": "property_search",
            "entities": {
                "location": None,
                "budget_max": 450_000_000,
                "bedrooms": 3,
                "purpose": "residential",
            },
            "confidence": 0.9,
            "requires_clarification": False,
        }
        client2 = FakeAsyncAnthropic([make_tool_use_response(turn2_payload)])
        turn2 = _run(
            process_incoming_message(
                db_session,
                conversation_id=conversation.id,
                lead_id=lead.id,
                message="450 millones, 3 habitaciones, para vivir",
                llm_client=client2,
            )
        )
        assert turn2.new_state == LeadStage.PROPERTY_SEARCH
        assert turn2.action == OrchestratorAction.SEARCH_PROPERTIES
        assert turn2.merged_entities.location == "Pinares"
        assert turn2.merged_entities.budget_max == 450_000_000
        assert turn2.merged_entities.bedrooms == 3

    def test_property_search_intent_after_discovering_is_acknowledged_without_transition(
        self, db_session: Session, make_lead_conversation: LeadConversationFactory
    ) -> None:
        # SPEC.md no define una transicion para "el usuario agrega/corrige
        # criterios" en un estado posterior a DISCOVERING -- ver docstring
        # de `_resolve_turn` en orchestrator.py.
        lead, conversation, _state = make_lead_conversation(current_state=LeadStage.PRESENTING)
        payload = {
            "intent": "property_search",
            "entities": {
                "location": "Laureles",
                "budget_max": 300_000_000,
                "bedrooms": 2,
                "purpose": "investment",
            },
            "confidence": 0.9,
            "requires_clarification": False,
        }
        client = FakeAsyncAnthropic([make_tool_use_response(payload)])
        result = _run(
            process_incoming_message(
                db_session,
                conversation_id=conversation.id,
                lead_id=lead.id,
                message="Mejor en Laureles, 300 millones, 2 habitaciones, para invertir",
                llm_client=client,
            )
        )
        assert result.new_state == LeadStage.PRESENTING
        assert result.state_changed is False
        assert result.action == OrchestratorAction.ACKNOWLEDGE


class TestClarificationBranch:
    def test_requires_clarification_true_does_not_advance_state_machine(
        self, db_session: Session, make_lead_conversation: LeadConversationFactory
    ) -> None:
        lead, conversation, _state = make_lead_conversation(current_state=LeadStage.DISCOVERING)
        payload = {
            "intent": "property_search",
            "entities": {
                "location": None,
                "budget_max": None,
                "bedrooms": None,
                "purpose": None,
            },
            "confidence": 0.2,
            "requires_clarification": True,
        }
        client = FakeAsyncAnthropic([make_tool_use_response(payload)])
        result = _run(
            process_incoming_message(
                db_session,
                conversation_id=conversation.id,
                lead_id=lead.id,
                message="mmm no se",
                llm_client=client,
            )
        )
        assert result.new_state == LeadStage.DISCOVERING
        assert result.state_changed is False
        assert result.action == OrchestratorAction.ASK_CLARIFICATION
        assert result.handoff_reason is None

    def test_requires_clarification_takes_precedence_over_incomplete_slots_action(
        self, db_session: Session, make_lead_conversation: LeadConversationFactory
    ) -> None:
        # Con requires_clarification=True el resultado es ASK_CLARIFICATION,
        # no REQUEST_MORE_INFO, aunque el intent tambien sea property_search
        # con slots incompletos (orden de evaluacion de `_resolve_turn`).
        lead, conversation, _state = make_lead_conversation(current_state=LeadStage.DISCOVERING)
        payload = {
            "intent": "property_search",
            "entities": {
                "location": "Pinares",
                "budget_max": None,
                "bedrooms": None,
                "purpose": None,
            },
            "confidence": 0.3,
            "requires_clarification": True,
        }
        client = FakeAsyncAnthropic([make_tool_use_response(payload)])
        result = _run(
            process_incoming_message(
                db_session,
                conversation_id=conversation.id,
                lead_id=lead.id,
                message="en pinares creo",
                llm_client=client,
            )
        )
        assert result.action == OrchestratorAction.ASK_CLARIFICATION


class TestQuestionAndOtherBranch:
    @pytest.mark.parametrize("intent", ["question", "other"])
    def test_question_or_other_intent_offers_handoff_no_faq_reason(
        self,
        db_session: Session,
        make_lead_conversation: LeadConversationFactory,
        intent: str,
    ) -> None:
        lead, conversation, _state = make_lead_conversation(current_state=LeadStage.DISCOVERING)
        payload = {
            "intent": intent,
            "entities": {
                "location": None,
                "budget_max": None,
                "bedrooms": None,
                "purpose": None,
            },
            "confidence": 0.85,
            "requires_clarification": False,
        }
        client = FakeAsyncAnthropic([make_tool_use_response(payload)])
        result = _run(
            process_incoming_message(
                db_session,
                conversation_id=conversation.id,
                lead_id=lead.id,
                message="¿Manejan financiacion con el banco?",
                llm_client=client,
            )
        )
        assert result.new_state == LeadStage.HANDOFF
        assert result.action == OrchestratorAction.OFFER_HANDOFF
        assert result.handoff_reason == "unanswered_question_no_faq"


class TestLLMExtractionFailure:
    def test_llm_extraction_failed_is_treated_as_handoff(
        self, db_session: Session, make_lead_conversation: LeadConversationFactory
    ) -> None:
        from tests.agent_engine.llm_test_doubles import make_no_tool_use_response

        lead, conversation, _state = make_lead_conversation(current_state=LeadStage.DISCOVERING)
        client = FakeAsyncAnthropic([make_no_tool_use_response(), make_no_tool_use_response()])
        result = _run(
            process_incoming_message(
                db_session,
                conversation_id=conversation.id,
                lead_id=lead.id,
                message="algo que el LLM no puede procesar",
                llm_client=client,
            )
        )
        assert result.new_state == LeadStage.HANDOFF
        assert result.action == OrchestratorAction.OFFER_HANDOFF
        assert result.handoff_reason == "llm_extraction_failed"

    def test_llm_extraction_failed_from_new_state_still_reaches_handoff(
        self, db_session: Session, make_lead_conversation: LeadConversationFactory
    ) -> None:
        from tests.agent_engine.llm_test_doubles import make_no_tool_use_response

        lead, conversation, _state = make_lead_conversation(current_state=LeadStage.NEW)
        client = FakeAsyncAnthropic([make_no_tool_use_response(), make_no_tool_use_response()])
        result = _run(
            process_incoming_message(
                db_session,
                conversation_id=conversation.id,
                lead_id=lead.id,
                message="mensaje raro",
                llm_client=client,
            )
        )
        assert result.previous_state == LeadStage.NEW
        assert result.new_state == LeadStage.HANDOFF
        assert result.handoff_reason == "llm_extraction_failed"


class TestNurtureReactivation:
    def test_nurture_lead_sending_new_message_bootstraps_back_to_discovering(
        self, db_session: Session, make_lead_conversation: LeadConversationFactory
    ) -> None:
        lead, conversation, _state = make_lead_conversation(current_state=LeadStage.NURTURE)
        payload = {
            "intent": "property_search",
            "entities": {
                "location": "Envigado",
                "budget_max": None,
                "bedrooms": None,
                "purpose": None,
            },
            "confidence": 0.8,
            "requires_clarification": False,
        }
        client = FakeAsyncAnthropic([make_tool_use_response(payload)])
        result = _run(
            process_incoming_message(
                db_session,
                conversation_id=conversation.id,
                lead_id=lead.id,
                message="Hola, sigo buscando en Envigado",
                llm_client=client,
            )
        )
        assert result.previous_state == LeadStage.NURTURE
        assert result.new_state == LeadStage.DISCOVERING
        assert result.state_changed is True
        assert result.action == OrchestratorAction.REQUEST_MORE_INFO


class TestConversationStateAutoCreated:
    def test_missing_conversation_state_row_is_created_with_new_default(
        self, db_session: Session, make_lead_conversation: LeadConversationFactory
    ) -> None:
        from sqlalchemy import delete

        from app.models.conversation_state import ConversationState

        lead, conversation, state = make_lead_conversation(current_state=LeadStage.DISCOVERING)
        db_session.execute(
            delete(ConversationState).where(ConversationState.conversation_id == conversation.id)
        )
        db_session.flush()

        result = _run(
            process_incoming_message(
                db_session,
                conversation_id=conversation.id,
                lead_id=lead.id,
                message="Quiero hablar con una persona",
            )
        )
        # ConversationState nueva arranca en NEW (default del modelo) -- el
        # bootstrap se salta porque human_request es universal, por lo que
        # previous_state observado es NEW, no DISCOVERING.
        assert result.previous_state == LeadStage.NEW
        assert result.new_state == LeadStage.HANDOFF


class TestPersistenceFailure:
    def test_sqlalchemy_error_during_flush_raises_orchestrator_persistence_error(
        self,
        db_session: Session,
        make_lead_conversation: LeadConversationFactory,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        lead, conversation, _state = make_lead_conversation(current_state=LeadStage.DISCOVERING)

        def _raise_on_flush(*args: object, **kwargs: object) -> None:
            raise sqlalchemy.exc.SQLAlchemyError("simulated PostgreSQL failure")

        # No se desactiva autoflush aqui: `process_incoming_message` envuelve
        # TODA la logica de DB del turno (desde `db.get(Conversation, ...)`
        # hasta el `db.flush()` final) en un unico `try/except
        # SQLAlchemyError`, asi que un fallo disparado por autoflush durante
        # una lectura intermedia (p.ej. el `db.execute(select(...))` de
        # `_get_or_create_conversation_state`) queda cubierto igual que el
        # flush final -- este test ejercita ese path real sin necesitar
        # ningun workaround.
        monkeypatch.setattr(db_session, "flush", _raise_on_flush)

        with pytest.raises(OrchestratorPersistenceError):
            _run(
                process_incoming_message(
                    db_session,
                    conversation_id=conversation.id,
                    lead_id=lead.id,
                    message="Quiero hablar con una persona",
                )
            )
