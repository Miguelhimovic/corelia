"""Fixtures compartidas para los tests de orquestador / golden conversations
del agent engine. Reutiliza el `db_session` de `tests/conftest.py` (rollback
por test, mismo patron que `tests/test_models.py`)."""

from collections.abc import Callable

import pytest
from sqlalchemy.orm import Session

from app.models import Conversation, ConversationState, Lead, Tenant
from app.models.enums import Channel, LeadPurpose, LeadStage

# Alias explicito del tipo que devuelve la factory, para legibilidad en los
# tests que la consumen.
LeadConversationFactory = Callable[..., tuple[Lead, Conversation, ConversationState]]


@pytest.fixture
def make_lead_conversation(db_session: Session) -> LeadConversationFactory:
    """Crea Tenant + Lead + Conversation + ConversationState listos para
    pasarle a `process_incoming_message`, con el estado/contadores/slots ya
    conocidos que cada test necesite simular.

    No hace `commit` (mismo patron que el resto del codebase, ver
    `orchestrator.py`) — el rollback de `db_session` limpia todo al final
    del test.
    """

    def _make(
        *,
        current_state: LeadStage = LeadStage.NEW,
        empty_search_count: int = 0,
        no_response_count: int = 0,
        location: str | None = None,
        budget_max: float | None = None,
        bedrooms: int | None = None,
        purpose: LeadPurpose | None = None,
    ) -> tuple[Lead, Conversation, ConversationState]:
        tenant = Tenant(name="CorelIA Demo")
        db_session.add(tenant)
        db_session.flush()

        lead = Lead(
            tenant_id=tenant.id,
            channel=Channel.WEB,
            source="test_orchestrator",
            location=location,
            budget_max=budget_max,
            bedrooms=bedrooms,
            purpose=purpose,
        )
        db_session.add(lead)
        db_session.flush()

        conversation = Conversation(tenant_id=tenant.id, lead_id=lead.id, channel=Channel.WEB)
        db_session.add(conversation)
        db_session.flush()

        state = ConversationState(
            conversation_id=conversation.id,
            current_state=current_state,
            empty_search_count=empty_search_count,
            no_response_count=no_response_count,
        )
        db_session.add(state)
        db_session.flush()

        return lead, conversation, state

    return _make
