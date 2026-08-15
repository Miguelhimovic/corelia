import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, SmallInteger, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import UUIDPrimaryKeyMixin
from app.models.enums import LeadStage


class ConversationState(Base, UUIDPrimaryKeyMixin):
    """Estado vivo del state machine para una Conversation. SPEC.md secciones 1, 2 y 5.

    Relacion uno-a-uno con Conversation (conversation_id es unico). `current_state`
    reutiliza `LeadStage` en vez de un enum propio: SPEC.md seccion 2 define un
    unico state machine de 10 estados compartido por Lead.stage y por el estado
    de la conversacion — mantenerlos como el mismo enum evita que ambos listados
    diverjan con el tiempo.

    `empty_search_count`: SPEC.md seccion 1/2 — se incrementa en cada
    `results_empty` de PROPERTY_SEARCH; se resetea a 0 cuando el usuario cambia
    cualquiera de los 4 criterios de busqueda (location/budget_max/bedrooms/
    purpose). 2 busquedas vacias seguidas -> HANDOFF.

    `no_response_count`: SPEC.md seccion 1 — cuenta recordatorios sin respuesta
    en el estado actual (DISCOVERING, PRESENTING, SCHEDULING). Se resetea a 0 en
    cada transicion de estado. 2 recordatorios sin respuesta -> NURTURE.

    `last_transition_at`: timestamp de la ultima transicion de estado, usado
    para calcular si toca enviar un recordatorio o hacer timeout.
    """

    __tablename__ = "conversation_states"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.id"),
        nullable=False,
        unique=True,
    )
    current_state: Mapped[LeadStage] = mapped_column(
        SAEnum(LeadStage, name="lead_stage"), nullable=False, default=LeadStage.NEW
    )
    last_transition_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    empty_search_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    no_response_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
