from sqlalchemy.orm import Session

from app.models import Agent, Conversation, Lead, Message, Tenant
from app.models.enums import Channel, LeadStage, MessageRole


def test_tenant_lead_conversation_message_roundtrip(db_session: Session) -> None:
    tenant = Tenant(name="CorelIA Demo")
    db_session.add(tenant)
    db_session.flush()

    lead = Lead(tenant_id=tenant.id, channel=Channel.WEB, source="landing_real_estate")
    db_session.add(lead)
    db_session.flush()

    conversation = Conversation(tenant_id=tenant.id, lead_id=lead.id, channel=Channel.WEB)
    db_session.add(conversation)
    db_session.flush()

    message = Message(
        conversation_id=conversation.id,
        role=MessageRole.USER,
        content="Busco apartamento en Pinares",
    )
    db_session.add(message)
    db_session.flush()

    assert lead.stage == LeadStage.NEW
    assert lead.score == 0
    assert message.conversation_id == conversation.id


def test_agent_tools_enabled_defaults_to_list(db_session: Session) -> None:
    tenant = Tenant(name="CorelIA Demo")
    db_session.add(tenant)
    db_session.flush()

    agent = Agent(
        tenant_id=tenant.id,
        name="Real Estate Agent",
        system_prompt="placeholder",
        tools_enabled=["create_lead"],
    )
    db_session.add(agent)
    db_session.flush()

    assert agent.tools_enabled == ["create_lead"]
