import enum


class Channel(enum.StrEnum):
    """Canal de entrada. SPEC.md seccion 12: Web es obligatorio en el MVP,
    WhatsApp se conecta en Fase 6 — ambos comparten el mismo agent engine."""

    WHATSAPP = "whatsapp"
    WEB = "web"


class LeadStage(enum.StrEnum):
    """Estados del state machine de ventas. SPEC.md seccion 2."""

    NEW = "NEW"
    DISCOVERING = "DISCOVERING"
    QUALIFYING = "QUALIFYING"
    PROPERTY_SEARCH = "PROPERTY_SEARCH"
    PRESENTING = "PRESENTING"
    SCHEDULING = "SCHEDULING"
    BOOKED = "BOOKED"
    HANDOFF = "HANDOFF"
    NURTURE = "NURTURE"
    LOST = "LOST"


class LeadIntent(enum.StrEnum):
    """Enum cerrado del contrato de extraccion del LLM. SPEC.md seccion 3 —
    el LLM no puede inventar valores nuevos; si lo hace, se trata como OTHER."""

    PROPERTY_SEARCH = "property_search"
    QUESTION = "question"
    HUMAN_REQUEST = "human_request"
    CANCEL = "cancel"
    NOT_INTERESTED = "not_interested"
    OTHER = "other"


class LeadPurpose(enum.StrEnum):
    RESIDENTIAL = "residential"
    INVESTMENT = "investment"


class MessageRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"
