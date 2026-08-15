import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import UUIDPrimaryKeyMixin
from app.models.enums import HandoffStatus


class HumanHandoff(Base, UUIDPrimaryKeyMixin):
    """Escalamiento a un asesor humano. SPEC.md secciones 4 (handoff_human),
    5 (modelo de datos) y 7 (flujo de Human Handoff).

    Solo `created_at`, sin `TimestampMixin`/`updated_at`: SPEC.md seccion 5
    lista exactamente `lead_id, reason, summary, assigned_to, status,
    created_at` para esta tabla -- igual que `Message`, se modela como
    registro de un evento (el momento en que se dispara el handoff), no como
    una entidad que el agent engine edita in-place.

    `assigned_to`: en MVP no existe tabla de usuarios/agentes humanos (fuera
    de alcance -- ver CLAUDE.md "Que NO construir todavia"), por eso es
    texto libre nullable en vez de FK. Siempre NULL en MVP (la asignacion es
    manual, fuera del sistema).

    `status`: default `open`; la transicion a `resolved` es operacion manual
    del equipo humano, no algo que dispare el agent engine.
    """

    __tablename__ = "human_handoffs"

    lead_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("leads.id"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    assigned_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[HandoffStatus] = mapped_column(
        SAEnum(HandoffStatus, name="handoff_status"),
        nullable=False,
        default=HandoffStatus.OPEN,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
