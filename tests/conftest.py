from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import Base


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
