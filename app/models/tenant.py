from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class Tenant(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Tenant unico y hardcodeado para el MVP (CLAUDE.md principio #3).

    No hay logica de multi-tenancy todavia: esta tabla existe para que el
    modelo de datos sea correcto desde ya, pero en runtime todo el sistema
    opera contra el unico registro cuyo id es app.config.DEFAULT_TENANT_ID.
    """

    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(nullable=False)
