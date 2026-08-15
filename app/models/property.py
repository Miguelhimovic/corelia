import uuid

from sqlalchemy import Boolean, ForeignKey, Numeric, SmallInteger, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import LeadPurpose, PropertyStatus


class Property(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Catalogo de propiedades. SPEC.md secciones 4 (search_database), 5 y 13
    (demo data).

    `purpose` reutiliza el enum `LeadPurpose` (residential|investment): es el
    mismo dominio de valores del contrato de extraccion del LLM (SPEC.md
    seccion 3) y del parametro `purpose` de `search_database()` (seccion 4)
    -- mantener un unico enum evita que las dos listas de valores diverjan.

    `property_type` y `availability` se guardan como texto libre: a
    diferencia de `purpose`/`status`, SPEC.md no define un dominio cerrado
    para el tipo de inmueble ni para el estado de disponibilidad de mudanza
    -- restringirlos con un enum ahora seria inventar un contrato que no
    esta en SPEC.md.

    `is_demo`: SPEC.md secciones 5 y 13 -- mecanismo explicito de marcado de
    datos de demostracion (no una convencion de naming). Default True porque
    en MVP todo el catalogo es demo data hasta que exista inventario real de
    un cliente.
    """

    __tablename__ = "properties"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    property_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    city: Mapped[str] = mapped_column(String(255), nullable=False)
    neighborhood: Mapped[str | None] = mapped_column(String(255), nullable=True)
    price: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    bedrooms: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    bathrooms: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    area: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    purpose: Mapped[LeadPurpose] = mapped_column(
        SAEnum(LeadPurpose, name="lead_purpose"), nullable=False
    )
    status: Mapped[PropertyStatus] = mapped_column(
        SAEnum(PropertyStatus, name="property_status"),
        nullable=False,
        default=PropertyStatus.AVAILABLE,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    features: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    images: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    availability: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
