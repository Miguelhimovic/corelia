import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, SmallInteger, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import Channel, LeadIntent, LeadPurpose, LeadStage


class Lead(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """CLAUDE.md 'Modelo de datos (Fase 1)' + criterios de calificacion de SPEC.md seccion 1.

    location/budget_max/bedrooms/purpose son los 4 slots requeridos antes de
    PROPERTY_SEARCH (SPEC.md secciones 1 y 2) y se guardan aqui porque
    update_lead() (Fase 3) los persiste en el Lead a medida que el LLM los
    extrae — no se modelan en una tabla aparte.
    """

    __tablename__ = "leads"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )

    # Identidad / origen
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    channel: Mapped[Channel] = mapped_column(SAEnum(Channel, name="channel"), nullable=False)

    # Calificacion (SPEC.md secciones 1 y 3)
    intent: Mapped[LeadIntent | None] = mapped_column(
        SAEnum(LeadIntent, name="lead_intent"), nullable=True
    )
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    budget_max: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    bedrooms: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    purpose: Mapped[LeadPurpose | None] = mapped_column(
        SAEnum(LeadPurpose, name="lead_purpose"), nullable=True
    )

    # Pipeline
    score: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    stage: Mapped[LeadStage] = mapped_column(
        SAEnum(LeadStage, name="lead_stage"), nullable=False, default=LeadStage.NEW
    )
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
