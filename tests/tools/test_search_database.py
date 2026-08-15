"""Unit tests de `search_database()` (SPEC.md seccion 4, Tool Contracts).

Algoritmo exacto (SPEC.md seccion 4 / docstring del modulo): filtros duros,
TODOS deben cumplirse -- status=='available', location substring
case-insensitive contra city O neighborhood, price<=budget_max,
bedrooms>=solicitado, purpose exacto -- ordenado por precio ascendente,
maximo 5 resultados. Vacio -> lista vacia, nunca excepcion.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import sqlalchemy.exc
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models import Tenant
from app.models.enums import LeadPurpose, PropertyStatus
from app.tools.errors import PropertySearchError
from app.tools.search_database import search_database
from tests.conftest import PropertyFactory


class TestSearchDatabaseFilters:
    def test_filters_by_location_substring_in_neighborhood_case_insensitive(
        self, db_session: Session, default_tenant: Tenant, make_property: PropertyFactory
    ) -> None:
        matching = make_property(neighborhood="Laureles", city="Medellin")
        make_property(neighborhood="Poblado", city="Medellin")  # distinto barrio, mismo criterio

        results = search_database(
            db_session,
            location="laureles",  # minuscula a proposito
            budget_max=1_000_000_000,
            bedrooms=1,
            purpose="residential",
        )
        assert [p.id for p in results] == [matching.id]

    def test_filters_by_location_substring_in_city_case_insensitive(
        self, db_session: Session, default_tenant: Tenant, make_property: PropertyFactory
    ) -> None:
        matching = make_property(city="Bogota", neighborhood="Chapinero")
        make_property(city="Cali", neighborhood="Granada")

        results = search_database(
            db_session,
            location="BOGOTA",  # mayuscula a proposito
            budget_max=1_000_000_000,
            bedrooms=1,
            purpose="residential",
        )
        assert [p.id for p in results] == [matching.id]

    def test_excludes_property_above_budget_max(
        self, db_session: Session, default_tenant: Tenant, make_property: PropertyFactory
    ) -> None:
        affordable = make_property(price=Decimal("300000000"))
        make_property(price=Decimal("900000000"))

        results = search_database(
            db_session,
            location="Laureles",
            budget_max=400_000_000,
            bedrooms=1,
            purpose="residential",
        )
        assert [p.id for p in results] == [affordable.id]

    def test_price_exactly_equal_to_budget_max_is_included(
        self, db_session: Session, default_tenant: Tenant, make_property: PropertyFactory
    ) -> None:
        exact = make_property(price=Decimal("400000000"))
        results = search_database(
            db_session,
            location="Laureles",
            budget_max=400_000_000,
            bedrooms=1,
            purpose="residential",
        )
        assert [p.id for p in results] == [exact.id]

    def test_requires_bedrooms_greater_or_equal_than_requested(
        self, db_session: Session, default_tenant: Tenant, make_property: PropertyFactory
    ) -> None:
        two_bed = make_property(bedrooms=2)
        three_bed = make_property(bedrooms=3)
        make_property(bedrooms=1)  # menos habitaciones de las pedidas -> excluida

        results = search_database(
            db_session,
            location="Laureles",
            budget_max=1_000_000_000,
            bedrooms=2,
            purpose="residential",
        )
        assert {p.id for p in results} == {two_bed.id, three_bed.id}

    def test_filters_by_exact_purpose_match(
        self, db_session: Session, default_tenant: Tenant, make_property: PropertyFactory
    ) -> None:
        residential = make_property(purpose=LeadPurpose.RESIDENTIAL)
        make_property(purpose=LeadPurpose.INVESTMENT)

        results = search_database(
            db_session,
            location="Laureles",
            budget_max=1_000_000_000,
            bedrooms=1,
            purpose="residential",
        )
        assert [p.id for p in results] == [residential.id]

    @pytest.mark.parametrize(
        "status",
        [
            PropertyStatus.RESERVED,
            PropertyStatus.SOLD,
            PropertyStatus.RENTED,
            PropertyStatus.INACTIVE,
        ],
    )
    def test_excludes_properties_not_available(
        self,
        db_session: Session,
        default_tenant: Tenant,
        make_property: PropertyFactory,
        status: PropertyStatus,
    ) -> None:
        make_property(status=status)
        results = search_database(
            db_session,
            location="Laureles",
            budget_max=1_000_000_000,
            bedrooms=1,
            purpose="residential",
        )
        assert results == []

    def test_no_matching_properties_returns_empty_list_not_exception(
        self, db_session: Session, default_tenant: Tenant, make_property: PropertyFactory
    ) -> None:
        make_property(city="Medellin", neighborhood="Laureles")
        results = search_database(
            db_session,
            location="CiudadInexistente",
            budget_max=1_000_000_000,
            bedrooms=1,
            purpose="residential",
        )
        assert results == []


class TestSearchDatabaseOrderingAndLimit:
    def test_results_ordered_by_price_ascending(
        self, db_session: Session, default_tenant: Tenant, make_property: PropertyFactory
    ) -> None:
        expensive = make_property(price=Decimal("500000000"))
        cheap = make_property(price=Decimal("250000000"))
        mid = make_property(price=Decimal("350000000"))

        results = search_database(
            db_session,
            location="Laureles",
            budget_max=1_000_000_000,
            bedrooms=1,
            purpose="residential",
        )
        assert [p.id for p in results] == [cheap.id, mid.id, expensive.id]

    def test_limits_results_to_five_even_with_more_matches(
        self, db_session: Session, default_tenant: Tenant, make_property: PropertyFactory
    ) -> None:
        for i in range(8):
            make_property(price=Decimal(str(200_000_000 + i * 1_000_000)))

        results = search_database(
            db_session,
            location="Laureles",
            budget_max=1_000_000_000,
            bedrooms=1,
            purpose="residential",
        )
        assert len(results) == 5
        prices = [float(p.price) for p in results]
        assert prices == sorted(prices)
        # Las 5 mas baratas del set de 8, no cualquier subconjunto arbitrario.
        assert prices[-1] <= 200_000_000 + 4 * 1_000_000


class TestSearchDatabaseValidation:
    def test_budget_max_zero_raises_validation_error(
        self, db_session: Session, default_tenant: Tenant
    ) -> None:
        with pytest.raises(ValidationError):
            search_database(
                db_session, location="Laureles", budget_max=0, bedrooms=1, purpose="residential"
            )

    def test_budget_max_negative_raises_validation_error(
        self, db_session: Session, default_tenant: Tenant
    ) -> None:
        with pytest.raises(ValidationError):
            search_database(
                db_session, location="Laureles", budget_max=-100, bedrooms=1, purpose="residential"
            )

    def test_bedrooms_zero_raises_validation_error(
        self, db_session: Session, default_tenant: Tenant
    ) -> None:
        with pytest.raises(ValidationError):
            search_database(
                db_session,
                location="Laureles",
                budget_max=400_000_000,
                bedrooms=0,
                purpose="residential",
            )

    def test_empty_location_raises_validation_error(
        self, db_session: Session, default_tenant: Tenant
    ) -> None:
        with pytest.raises(ValidationError):
            search_database(
                db_session, location="", budget_max=400_000_000, bedrooms=1, purpose="residential"
            )

    def test_invalid_purpose_raises_validation_error(
        self, db_session: Session, default_tenant: Tenant
    ) -> None:
        with pytest.raises(ValidationError):
            search_database(
                db_session,
                location="Laureles",
                budget_max=400_000_000,
                bedrooms=1,
                purpose="vacation_home",
            )


class TestSearchDatabasePersistenceFailure:
    def test_sqlalchemy_error_during_query_raises_property_search_error(
        self,
        db_session: Session,
        default_tenant: Tenant,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _raise_on_execute(*args: object, **kwargs: object) -> None:
            raise sqlalchemy.exc.SQLAlchemyError("simulated PostgreSQL failure")

        monkeypatch.setattr(db_session, "execute", _raise_on_execute)

        with pytest.raises(PropertySearchError):
            search_database(
                db_session,
                location="Laureles",
                budget_max=400_000_000,
                bedrooms=1,
                purpose="residential",
            )
