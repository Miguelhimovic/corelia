"""Unit tests de `create_lead()` (SPEC.md seccion 4, Tool Contracts).

Contrato: "Precondicion: ninguna (se llama en el primer mensaje)". "Exito:
retorna lead_id, stage=NEW, score=0". "Error: telefono/canal invalido -> error
de validacion, no crea el lead".
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy.exc
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Conversation, Lead, Message, Tenant
from app.models.enums import Channel, LeadStage, MessageRole
from app.tools.create_lead import create_lead
from app.tools.errors import LeadPersistenceError


class TestCreateLeadSuccess:
    def test_creates_lead_conversation_and_message(
        self, db_session: Session, default_tenant: Tenant
    ) -> None:
        result = create_lead(
            db_session,
            source="landing_real_estate",
            channel="web",
            phone=None,
            initial_message="Busco apartamento en Pinares",
        )

        lead = db_session.get(Lead, result.lead_id)
        conversation = db_session.get(Conversation, result.conversation_id)
        message = db_session.get(Message, result.message_id)

        assert lead is not None
        assert conversation is not None
        assert message is not None
        assert conversation.lead_id == lead.id
        assert message.conversation_id == conversation.id
        assert message.role == MessageRole.USER
        assert message.content == "Busco apartamento en Pinares"

    def test_lead_defaults_stage_new_score_zero_and_slots_null(
        self, db_session: Session, default_tenant: Tenant
    ) -> None:
        result = create_lead(
            db_session,
            source="landing_real_estate",
            channel="web",
            phone=None,
            initial_message="Hola",
        )
        lead = db_session.get(Lead, result.lead_id)
        assert lead is not None
        assert lead.stage == LeadStage.NEW
        assert lead.score == 0
        assert lead.location is None
        assert lead.budget_max is None
        assert lead.bedrooms is None
        assert lead.purpose is None
        assert lead.tenant_id == default_tenant.id

    def test_phone_none_is_allowed(self, db_session: Session, default_tenant: Tenant) -> None:
        result = create_lead(
            db_session,
            source="landing_real_estate",
            channel="web",
            phone=None,
            initial_message="Hola, quiero informacion",
        )
        lead = db_session.get(Lead, result.lead_id)
        assert lead is not None
        assert lead.phone is None

    def test_valid_phone_is_persisted(self, db_session: Session, default_tenant: Tenant) -> None:
        result = create_lead(
            db_session,
            source="whatsapp_campaign",
            channel="whatsapp",
            phone="+573001234567",
            initial_message="Hola",
        )
        lead = db_session.get(Lead, result.lead_id)
        assert lead is not None
        assert lead.phone == "+573001234567"
        assert lead.channel == Channel.WHATSAPP


class TestCreateLeadValidation:
    def test_invalid_channel_raises_validation_error_and_creates_nothing(
        self, db_session: Session, default_tenant: Tenant
    ) -> None:
        before = db_session.execute(select(Lead)).scalars().all()
        with pytest.raises(ValidationError):
            create_lead(
                db_session,
                source="landing_real_estate",
                channel="sms",  # fuera del dominio cerrado web|whatsapp
                phone=None,
                initial_message="Hola",
            )
        after = db_session.execute(select(Lead)).scalars().all()
        assert len(after) == len(before)

    def test_invalid_phone_format_raises_validation_error(
        self, db_session: Session, default_tenant: Tenant
    ) -> None:
        with pytest.raises(ValidationError):
            create_lead(
                db_session,
                source="landing_real_estate",
                channel="whatsapp",
                phone="no-es-un-telefono",
                initial_message="Hola",
            )

    def test_empty_initial_message_raises_validation_error(
        self, db_session: Session, default_tenant: Tenant
    ) -> None:
        with pytest.raises(ValidationError):
            create_lead(
                db_session,
                source="landing_real_estate",
                channel="web",
                phone=None,
                initial_message="",
            )

    def test_empty_source_raises_validation_error(
        self, db_session: Session, default_tenant: Tenant
    ) -> None:
        with pytest.raises(ValidationError):
            create_lead(
                db_session,
                source="",
                channel="web",
                phone=None,
                initial_message="Hola",
            )


class TestCreateLeadPersistenceFailure:
    def test_sqlalchemy_error_during_flush_raises_lead_persistence_error(
        self,
        db_session: Session,
        default_tenant: Tenant,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _raise_on_flush(*args: object, **kwargs: object) -> None:
            raise sqlalchemy.exc.SQLAlchemyError("simulated PostgreSQL failure")

        monkeypatch.setattr(db_session, "flush", _raise_on_flush)

        with pytest.raises(LeadPersistenceError):
            create_lead(
                db_session,
                source="landing_real_estate",
                channel="web",
                phone=None,
                initial_message="Hola",
                request_id=str(uuid4()),
            )
