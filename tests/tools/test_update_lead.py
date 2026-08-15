"""Unit tests de `update_lead()` (SPEC.md seccion 4, Tool Contracts, y seccion
5 -- precision de campos no editables).

Contrato: actualizacion parcial de un `Lead` existente; `stage`/`score` nunca
editables via esta tool (SPEC.md seccion 5); `lead_id` inexistente ->
`LeadNotFoundError` ("404 logico"); falla de PostgreSQL -> `LeadPersistenceError`.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy.exc
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models import Tenant
from app.models.enums import LeadPurpose
from app.tools.errors import LeadNotFoundError, LeadPersistenceError
from app.tools.update_lead import update_lead
from tests.conftest import LeadFactory


class TestUpdateLeadSuccess:
    def test_partial_update_only_changes_given_fields(
        self, db_session: Session, default_tenant: Tenant, make_lead: LeadFactory
    ) -> None:
        lead = make_lead(name="Juan Perez", location="Envigado")
        updated = update_lead(
            db_session,
            lead_id=lead.id,
            fields={"location": "Pinares", "budget_max": 450_000_000},
        )
        assert updated.location == "Pinares"
        assert float(updated.budget_max) == 450_000_000
        # No provisto en `fields` -> queda intacto.
        assert updated.name == "Juan Perez"

    def test_none_value_explicitly_clears_field(
        self, db_session: Session, default_tenant: Tenant, make_lead: LeadFactory
    ) -> None:
        lead = make_lead(location="Envigado")
        updated = update_lead(db_session, lead_id=lead.id, fields={"location": None})
        assert updated.location is None

    def test_updates_all_four_required_slots(
        self, db_session: Session, default_tenant: Tenant, make_lead: LeadFactory
    ) -> None:
        lead = make_lead()
        updated = update_lead(
            db_session,
            lead_id=lead.id,
            fields={
                "location": "Sabaneta",
                "budget_max": 300_000_000,
                "bedrooms": 2,
                "purpose": "investment",
            },
        )
        assert updated.location == "Sabaneta"
        assert float(updated.budget_max) == 300_000_000
        assert updated.bedrooms == 2
        assert updated.purpose == LeadPurpose.INVESTMENT

    def test_empty_fields_dict_leaves_lead_unchanged(
        self, db_session: Session, default_tenant: Tenant, make_lead: LeadFactory
    ) -> None:
        lead = make_lead(location="Envigado")
        updated = update_lead(db_session, lead_id=lead.id, fields={})
        assert updated.location == "Envigado"


class TestUpdateLeadValidation:
    def test_stage_field_is_rejected(
        self, db_session: Session, default_tenant: Tenant, make_lead: LeadFactory
    ) -> None:
        lead = make_lead()
        with pytest.raises(ValidationError):
            update_lead(db_session, lead_id=lead.id, fields={"stage": "BOOKED"})

    def test_score_field_is_rejected(
        self, db_session: Session, default_tenant: Tenant, make_lead: LeadFactory
    ) -> None:
        lead = make_lead()
        with pytest.raises(ValidationError):
            update_lead(db_session, lead_id=lead.id, fields={"score": 90})

    def test_unknown_field_is_rejected(
        self, db_session: Session, default_tenant: Tenant, make_lead: LeadFactory
    ) -> None:
        lead = make_lead()
        with pytest.raises(ValidationError):
            update_lead(db_session, lead_id=lead.id, fields={"favorite_color": "blue"})

    def test_invalid_phone_format_is_rejected(
        self, db_session: Session, default_tenant: Tenant, make_lead: LeadFactory
    ) -> None:
        lead = make_lead()
        with pytest.raises(ValidationError):
            update_lead(db_session, lead_id=lead.id, fields={"phone": "no-es-telefono"})

    def test_invalid_purpose_value_is_rejected(
        self, db_session: Session, default_tenant: Tenant, make_lead: LeadFactory
    ) -> None:
        lead = make_lead()
        with pytest.raises(ValidationError):
            update_lead(db_session, lead_id=lead.id, fields={"purpose": "vacation_home"})


class TestUpdateLeadNotFound:
    def test_unknown_lead_id_raises_lead_not_found_error(
        self, db_session: Session, default_tenant: Tenant
    ) -> None:
        with pytest.raises(LeadNotFoundError):
            update_lead(db_session, lead_id=uuid.uuid4(), fields={"location": "Pinares"})


class TestUpdateLeadPersistenceFailure:
    def test_sqlalchemy_error_during_flush_raises_lead_persistence_error(
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
            update_lead(db_session, lead_id=lead.id, fields={"location": "Pinares"})
