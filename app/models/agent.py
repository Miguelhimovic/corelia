import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class Agent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Definicion de agente (Real Estate, Legal, ...). CLAUDE.md, 'Modelo de datos'."""

    __tablename__ = "agents"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    tools_enabled: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
