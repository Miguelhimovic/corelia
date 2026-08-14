import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import Channel


class Conversation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Vinculada a tenant, canal y lead. CLAUDE.md 'Modelo de datos (Fase 1)'."""

    __tablename__ = "conversations"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("leads.id"), nullable=False
    )
    channel: Mapped[Channel] = mapped_column(SAEnum(Channel, name="channel"), nullable=False)
