"""Unit tests de `handoff_human()` (SPEC.md secciones 4 y 7).

Contrato: crea `HumanHandoff` con `status=open`/`assigned_to=NULL`, mueve
`Lead.stage=HANDOFF` -- unica tool con permiso de tocar `stage` directamente.
`lead_id` inexistente -> `LeadNotFoundError`. Atomicidad: si la escritura de
`Lead.stage` falla despues de que el `HumanHandoff` ya se inserto en la misma
transaccion, el rollback debe revertir ambos efectos (SPEC.md seccion 7,
"no se inventa respuesta" -- tampoco un handoff a medias).
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy.exc
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import HumanHandoff, Tenant
from app.models.enums import HandoffStatus, LeadStage
from app.tools.errors import LeadNotFoundError, LeadPersistenceError
from app.tools.handoff_human import handoff_human
from tests.conftest import LeadFactory


class TestHandoffHumanSuccess:
    def test_creates_handoff_with_open_status_and_no_assignee(
        self, db_session: Session, default_tenant: Tenant, make_lead: LeadFactory
    ) -> None:
        lead = make_lead()
        handoff_id = handoff_human(
            db_session,
            lead_id=lead.id,
            reason="human_request_explicit",
            summary="El lead pidio hablar con un asesor.",
        )
        handoff = db_session.get(HumanHandoff, handoff_id)
        assert handoff is not None
        assert handoff.status == HandoffStatus.OPEN
        assert handoff.assigned_to is None
        assert handoff.lead_id == lead.id
        assert handoff.reason == "human_request_explicit"
        assert handoff.summary == "El lead pidio hablar con un asesor."

    def test_sets_lead_stage_to_handoff(
        self, db_session: Session, default_tenant: Tenant, make_lead: LeadFactory
    ) -> None:
        lead = make_lead()
        assert lead.stage == LeadStage.NEW
        handoff_human(
            db_session, lead_id=lead.id, reason="empty_search_2x", summary="2 busquedas vacias."
        )
        db_session.refresh(lead)
        assert lead.stage == LeadStage.HANDOFF

    def test_optional_conversation_id_is_accepted_but_not_persisted_on_handoff(
        self, db_session: Session, default_tenant: Tenant, make_lead: LeadFactory
    ) -> None:
        lead = make_lead()
        handoff_id = handoff_human(
            db_session,
            lead_id=lead.id,
            reason="human_request_explicit",
            summary="resumen",
            conversation_id=uuid.uuid4(),
        )
        handoff = db_session.get(HumanHandoff, handoff_id)
        assert handoff is not None
        assert not hasattr(handoff, "conversation_id")


class TestHandoffHumanValidation:
    def test_empty_reason_raises_validation_error(
        self, db_session: Session, default_tenant: Tenant, make_lead: LeadFactory
    ) -> None:
        lead = make_lead()
        with pytest.raises(ValidationError):
            handoff_human(db_session, lead_id=lead.id, reason="", summary="resumen")

    def test_empty_summary_raises_validation_error(
        self, db_session: Session, default_tenant: Tenant, make_lead: LeadFactory
    ) -> None:
        lead = make_lead()
        with pytest.raises(ValidationError):
            handoff_human(db_session, lead_id=lead.id, reason="human_request", summary="")


class TestHandoffHumanNotFound:
    def test_unknown_lead_id_raises_lead_not_found_error(
        self, db_session: Session, default_tenant: Tenant
    ) -> None:
        with pytest.raises(LeadNotFoundError):
            handoff_human(
                db_session, lead_id=uuid.uuid4(), reason="human_request", summary="resumen"
            )


class TestHandoffHumanAtomicity:
    def test_failure_after_handoff_insert_rolls_back_both_effects(
        self,
        db_session: Session,
        default_tenant: Tenant,
        make_lead: LeadFactory,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        lead = make_lead()
        real_flush = db_session.flush
        call_count = {"n": 0}

        def _flush_fails_on_second_call(*args: object, **kwargs: object) -> None:
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise sqlalchemy.exc.SQLAlchemyError("simulated PostgreSQL failure")
            return real_flush(*args, **kwargs)

        monkeypatch.setattr(db_session, "flush", _flush_fails_on_second_call)

        with pytest.raises(LeadPersistenceError):
            handoff_human(
                db_session, lead_id=lead.id, reason="human_request", summary="resumen"
            )

        # Atomicidad: el rollback deshace el HumanHandoff insertado en el
        # primer flush (todavia no confirmado) junto con el cambio de stage
        # que fallo -- no debe quedar un handoff huerfano.
        remaining = db_session.execute(
            select(HumanHandoff).where(HumanHandoff.lead_id == lead.id)
        ).scalars().all()
        assert remaining == []

    def test_sqlalchemy_error_before_any_write_raises_lead_persistence_error(
        self,
        db_session: Session,
        default_tenant: Tenant,
        make_lead: LeadFactory,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        lead = make_lead()

        def _raise_on_flush(*args: object, **kwargs: object) -> None:
            raise sqlalchemy.exc.SQLAlchemyError("simulated PostgreSQL failure")

        monkeypatch.setattr(db_session, "flush", _raise_on_flush)

        with pytest.raises(LeadPersistenceError):
            handoff_human(
                db_session, lead_id=lead.id, reason="human_request", summary="resumen"
            )
