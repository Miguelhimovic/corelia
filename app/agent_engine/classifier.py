import re
import unicodedata

from app.agent_engine.schemas import ExtractedEntities, ExtractionResult
from app.models.enums import LeadIntent

# Match literal de una regla determinista no tiene la ambiguedad que modela
# el score de confianza del LLM (seccion 3) — se fija en el maximo.
_DETERMINISTIC_CONFIDENCE = 1.0

# Variantes coloquiales colombianas cubiertas a proposito, sin sobre-ingenieria
# (SPEC.md seccion 1): pedir un humano, cancelar/reagendar cita, decir que ya
# no interesa. Cualquier otra frase cae al LLM por diseno.
_HUMAN_REQUEST_PATTERNS = [
    r"\bhablar con (?:un|una|el|la)?\s*(persona|asesor|agente|humano|alguien)\b",
    r"\bquiero (?:un|una)?\s*asesor\b",
    r"\bpasa\w*\s+con\s+(?:un|una|el|la)?\s*(persona|asesor|agente|humano)\b",
    r"\bnecesito (?:hablar con )?(?:un|una)?\s*(persona|asesor|agente|humano)\b",
    r"\b(asesor|agente) humano\b",
    r"\bpuedo hablar con alguien\b",
    r"\bquiero hablar con alguien\b",
]

_CANCEL_PATTERNS = [
    r"\bcancelar (?:la |mi )?cita\b",
    r"\bcancelar (?:la |mi )?reunion\b",
    r"\bquiero cancelar\b",
    r"\breagendar\b",
    r"\breprogramar\b",
    r"\bno puedo (?:ir|asistir) a la cita\b",
    r"\bcambiar (?:la |mi )?cita\b",
]

_NOT_INTERESTED_PATTERNS = [
    r"\bya no me interesa\b",
    r"\bno me interesa\b",
    r"\bno,? gracias\b",
    r"\bno quiero (?:continuar|seguir)\b",
    r"\bdejal[oa] asi\b",
    r"\bya no quiero\b",
]


def normalize_text(text: str) -> str:
    """Minusculas, sin tildes/diacriticos, espacios colapsados y sin bordes.

    Enfoque explicito con unicodedata en vez de sumar una libreria de NLP
    nueva (CLAUDE.md: sin dependencias nuevas sin justificar) — el MVP solo
    necesita igualar variantes como "asesor"/"asesor" o "interes"/"interés".
    """
    lowered = unicodedata.normalize("NFKD", text.lower())
    without_accents = "".join(ch for ch in lowered if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", without_accents).strip()


def _matches_any(patterns: list[str], normalized_text: str) -> bool:
    return any(re.search(pattern, normalized_text) for pattern in patterns)


def classify_deterministic(message: str) -> ExtractionResult | None:
    """Classifier determinista de SPEC.md seccion 1.

    Reglas keyword/regex sobre el mensaje normalizado que detectan SOLO
    human_request, cancel y not_interested a partir de frases literales
    cercanas a las descritas en el contrato. Cualquier otro mensaje —y en
    particular todo lo que requiera extraer location/budget_max/bedrooms/
    purpose de lenguaje natural— devuelve None para que el orquestador pase
    el turno a la extraccion via LLM (seccion 3).

    entities siempre va en null: este classifier no extrae slots, solo
    detecta estos 3 intents. confidence es alto (1.0) porque es un match
    literal, no una inferencia con la ambiguedad que modela el LLM.
    """
    normalized = normalize_text(message)
    if not normalized:
        return None

    # human_request se evalua primero: es la transicion de mayor prioridad
    # del state machine (SPEC.md seccion 2) y se preserva el mismo orden aqui.
    if _matches_any(_HUMAN_REQUEST_PATTERNS, normalized):
        intent = LeadIntent.HUMAN_REQUEST
    elif _matches_any(_CANCEL_PATTERNS, normalized):
        intent = LeadIntent.CANCEL
    elif _matches_any(_NOT_INTERESTED_PATTERNS, normalized):
        intent = LeadIntent.NOT_INTERESTED
    else:
        return None

    return ExtractionResult(
        intent=intent,
        entities=ExtractedEntities(),
        confidence=_DETERMINISTIC_CONFIDENCE,
        requires_clarification=False,
    )
