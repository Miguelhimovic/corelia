from pydantic import BaseModel, Field

from app.models.enums import LeadIntent, LeadPurpose


class ExtractedEntities(BaseModel):
    """Slots del contrato de extraccion (SPEC.md seccion 3). Las claves estan
    siempre presentes; un slot ausente se representa como None explicito,
    nunca se omite la clave."""

    location: str | None = None
    budget_max: float | None = None
    bedrooms: int | None = None
    purpose: LeadPurpose | None = None


class ExtractionResult(BaseModel):
    """Shape de salida comun al classifier determinista (SPEC.md seccion 1)
    y a la extraccion via LLM (SPEC.md seccion 3, Tarea 3) — el resto del
    sistema (state machine, orquestador) no diferencia el origen del match.
    """

    intent: LeadIntent
    entities: ExtractedEntities = Field(default_factory=ExtractedEntities)
    confidence: float = Field(ge=0.0, le=1.0)
    requires_clarification: bool = False
