from collections.abc import Callable, Generator
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import DEFAULT_TENANT_ID, get_settings
from app.models import Base, Lead, Property, Tenant
from app.models.enums import Channel, LeadPurpose, PropertyStatus


@pytest.fixture(scope="session")
def engine() -> Generator[Engine, None, None]:
    test_engine = create_engine(get_settings().database_url, future=True)
    Base.metadata.create_all(test_engine)
    yield test_engine
    Base.metadata.drop_all(test_engine)
    test_engine.dispose()


@pytest.fixture
def db_session(engine: Engine) -> Generator[Session, None, None]:
    """Cada test corre en una transaccion que se revierte al terminar — no ensucia la DB."""
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, future=True)()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


# ---------------------------------------------------------------------------
# Fixtures compartidas del tenant fijo (SPEC.md secciones 4-5, Fase 3 --
# tools). Viven en el conftest raiz (no en tests/tools/) porque tanto
# tests/tools/ como tests/agent_engine/ (handle_message, golden conversations
# con tools reales) las necesitan por igual.
#
# `app.config.DEFAULT_TENANT_ID` es el tenant fijo hardcodeado que
# `create_lead()`/`search_database()` usan sin parametrizar (CLAUDE.md
# principio #3). En produccion existe porque la migracion inicial lo siembra
# (`migrations/versions/108f0dd0d579_modelos_base_tenant_agent_lead_.py`),
# pero `engine` (arriba) crea las tablas via `Base.metadata.create_all()` --
# no corre migraciones de Alembic -- asi que ese tenant no existe por default
# en la DB de test. `default_tenant` lo crea explicitamente con el mismo id
# fijo para que cualquier tool que dependa de ese FK (`Lead.tenant_id`,
# `Property.tenant_id`) se comporte igual que en produccion.
# ---------------------------------------------------------------------------


@pytest.fixture
def default_tenant(db_session: Session) -> Tenant:
    tenant = Tenant(id=DEFAULT_TENANT_ID, name="CorelIA MVP (test)")
    db_session.add(tenant)
    db_session.flush()
    return tenant


LeadFactory = Callable[..., Lead]


@pytest.fixture
def make_lead(db_session: Session, default_tenant: Tenant) -> LeadFactory:
    """Crea un `Lead` ya existente bajo el tenant fijo, sin pasar por
    `create_lead()` -- para tests que necesitan un lead pre-existente sin
    ejercitar la tool que lo crea.
    """

    def _make(**overrides: Any) -> Lead:
        defaults: dict[str, Any] = {
            "tenant_id": default_tenant.id,
            "channel": Channel.WEB,
            "source": "test_tools",
        }
        defaults.update(overrides)
        lead = Lead(**defaults)
        db_session.add(lead)
        db_session.flush()
        return lead

    return _make


PropertyFactory = Callable[..., Property]


@pytest.fixture
def make_property(db_session: Session, default_tenant: Tenant) -> PropertyFactory:
    """Crea una `Property` bajo el tenant fijo, con defaults razonables que
    cada test de `search_database()`/`handle_message()` sobreescribe segun el
    filtro que ejercita.
    """

    def _make(**overrides: Any) -> Property:
        defaults: dict[str, Any] = {
            "tenant_id": default_tenant.id,
            "title": "Apartamento de prueba",
            "property_type": "Apartamento",
            "city": "Medellin",
            "neighborhood": "Laureles",
            "price": Decimal("300000000"),
            "bedrooms": 2,
            "bathrooms": 2,
            "purpose": LeadPurpose.RESIDENTIAL,
            "status": PropertyStatus.AVAILABLE,
            "is_demo": True,
        }
        defaults.update(overrides)
        prop = Property(**defaults)
        db_session.add(prop)
        db_session.flush()
        return prop

    return _make
