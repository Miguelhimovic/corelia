"""Extraccion de intencion y slots via Claude (SPEC.md seccion 3).

Se invoca desde el orquestador del state machine (Fase 2, Tarea 5) cuando
`classify_deterministic()` (ver `app/agent_engine/classifier.py`) devuelve
`None` — es decir, cuando el mensaje del usuario requiere interpretacion de
lenguaje natural en vez de un match literal de keyword/regex.

Esta funcion SOLO produce el JSON estructurado del contrato de extraccion.
Nunca genera texto de respuesta para el usuario ni datos de negocio
(propiedades, citas, documentos) — esa es una regla dura de CLAUDE.md que no
aplica directamente aqui porque este modulo no genera ese tipo de contenido,
pero se documenta para que quede explicito el limite de responsabilidad.
"""

import logging
import time
from typing import Any

import anthropic
from anthropic import AsyncAnthropic
from pydantic import ValidationError

from app.agent_engine.schemas import ExtractionResult
from app.config import get_settings
from app.models.enums import LeadIntent, LeadPurpose

logger = logging.getLogger(__name__)

# Modelo unico y hardcodeado (CLAUDE.md principio #4: un solo proveedor de
# LLM, sin capa de abstraccion) — Haiku es suficiente para clasificar
# intencion y extraer 4 slots, no requiere el razonamiento de un modelo mayor.
_MODEL = "claude-3-5-haiku-20241022"
_TOOL_NAME = "extract_lead_intent"

_TOOL_SCHEMA: dict[str, Any] = {
    "name": _TOOL_NAME,
    "description": (
        "Registra la intencion y los slots extraidos del ultimo mensaje del "
        "usuario, segun el contrato de SPEC.md seccion 3. No es una "
        "respuesta para el usuario, es solo el analisis estructurado."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": [member.value for member in LeadIntent],
                "description": "Intencion detectada en el mensaje.",
            },
            "entities": {
                "type": "object",
                "description": (
                    "Los 4 slots siempre presentes; el que no se pueda "
                    "inferir del mensaje va como null explicito."
                ),
                "properties": {
                    "location": {"type": ["string", "null"]},
                    "budget_max": {"type": ["number", "null"]},
                    "bedrooms": {"type": ["integer", "null"]},
                    "purpose": {
                        "type": ["string", "null"],
                        "enum": [member.value for member in LeadPurpose] + [None],
                    },
                },
                "required": ["location", "budget_max", "bedrooms", "purpose"],
            },
            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": (
                    "Confianza global 0-1 de intent+entities en conjunto, "
                    "no una confianza por slot."
                ),
            },
            "requires_clarification": {"type": "boolean"},
        },
        "required": ["intent", "entities", "confidence", "requires_clarification"],
    },
}

_SYSTEM_PROMPT = """Eres el modulo de extraccion de intencion y slots del \
agente inmobiliario de CorelIA. Tu unica tarea es analizar el ultimo \
mensaje del usuario y llamar SIEMPRE a la herramienta `extract_lead_intent` \
con tu analisis. Nunca respondas en texto libre ni converses con el \
usuario, y nunca inventes datos que el mensaje no contenga.

Reglas:
- intent debe ser exactamente uno de: property_search, question, \
human_request, cancel, not_interested, other.
- entities.purpose debe ser exactamente uno de: residential, investment, o \
null si no se puede determinar del mensaje.
- Cada slot de entities que no puedas inferir va como null explicito, \
nunca se omite la clave.
- confidence es un unico numero global entre 0 y 1 (no una confianza por \
slot).
- Si tu confianza es menor a 0.5, marca requires_clarification en true.
"""

_STRICT_SUFFIX = """

IMPORTANTE: tu respuesta anterior no cumplio el formato exigido. Llama a \
`extract_lead_intent` UNA SOLA VEZ e incluye TODOS los campos exactamente \
segun su input_schema: los 4 slots de entities siempre presentes (usa null \
donde no aplique), intent y purpose limitados a los valores permitidos, y \
confidence como numero entre 0 y 1.
"""


class LLMExtractionFailed(Exception):
    """Senal explicita de que la extraccion via LLM no se pudo completar.

    Se lanza cuando la API de Claude falla de forma persistente (SPEC.md
    seccion 7) o cuando la salida no pasa el contrato de la seccion 3 ni
    siquiera tras el reintento con prompt estricto. El orquestador (Fase 2,
    Tarea 5) debe capturar esta excepcion y tratarla como disparador de
    `handoff_human()` en vez de dejar que el request falle sin control.
    """


async def _request_extraction(
    client: AsyncAnthropic, message: str, *, strict: bool, request_id: str | None
) -> dict[str, Any] | None:
    """Una llamada a Claude con tool-use forzado.

    El reintento ante fallos transitorios de la API (SPEC.md seccion 7:
    "reintento unico con backoff corto") lo resuelve el SDK de Anthropic via
    `max_retries` del cliente en vez de reimplementar backoff a mano — ver
    el cliente por defecto que construye `extract_with_llm`.

    Devuelve el dict crudo de `tool_use.input`, o `None` si Claude no
    devolvio ningun bloque `tool_use` (el llamador lo trata igual que una
    salida malformada).
    """
    system_prompt = _SYSTEM_PROMPT + (_STRICT_SUFFIX if strict else "")
    start = time.monotonic()
    response = await client.messages.create(
        model=_MODEL,
        max_tokens=512,
        system=system_prompt,
        tools=[_TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": _TOOL_NAME},
        messages=[{"role": "user", "content": message}],
    )
    latency_ms = round((time.monotonic() - start) * 1000, 1)
    usage = getattr(response, "usage", None)
    logger.info(
        "llm_extraction_call",
        extra={
            "request_id": request_id,
            "strict": strict,
            "latency_ms": latency_ms,
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
        },
    )

    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == _TOOL_NAME:
            return block.input

    logger.warning("llm_extraction_no_tool_use", extra={"request_id": request_id, "strict": strict})
    return None


def _sanitize_enum_violations(raw: dict[str, Any], *, request_id: str | None) -> dict[str, Any]:
    """Aplica la regla de enums cerrados de SPEC.md seccion 3.

    Un valor de intent/purpose fuera del enum cerrado no es una excepcion
    sin manejar: se degrada a other/null y se registra (log) como violacion
    de schema, tal como exige el contrato.
    """
    sanitized = dict(raw)

    intent = sanitized.get("intent")
    valid_intents = {member.value for member in LeadIntent}
    if intent not in valid_intents:
        logger.warning(
            "llm_schema_violation_intent",
            extra={"request_id": request_id, "received": repr(intent)},
        )
        sanitized["intent"] = LeadIntent.OTHER.value

    entities = dict(sanitized.get("entities") or {})
    purpose = entities.get("purpose")
    valid_purposes = {member.value for member in LeadPurpose}
    if purpose is not None and purpose not in valid_purposes:
        logger.warning(
            "llm_schema_violation_purpose",
            extra={"request_id": request_id, "received": repr(purpose)},
        )
        entities["purpose"] = None
    sanitized["entities"] = entities

    return sanitized


async def extract_with_llm(
    message: str, client: AsyncAnthropic | None = None, *, request_id: str | None = None
) -> ExtractionResult:
    """Extrae intencion + slots de un mensaje de usuario via Claude.

    Contrato: SPEC.md seccion 3 (shape de salida, reglas de enums cerrados,
    null explicito, confidence global, politica de reintento por
    malformacion) y seccion 7 (politica de reintento/handoff ante fallo de
    la API). Se invoca solo cuando `classify_deterministic()` devuelve
    `None` (SPEC.md seccion 1).

    `client` es inyectable para poder pasar un `AsyncAnthropic` mockeado en
    tests — la funcion nunca instancia un cliente global a nivel de modulo.

    `request_id` es opcional (default `None`) y solo se usa para logging
    (SPEC.md seccion 10 item 5): el orquestador (Fase 2, Tarea 5) genera un
    UUID por turno y lo pasa aqui para poder correlacionar todas las lineas
    de log de un mismo turno, incluidas las de este modulo.

    Reintentos (dos capas independientes, sin mezclarlas):
    - Fallos transitorios de la red/API de Claude: resueltos por el propio
      SDK (`max_retries=1` en el cliente por defecto de este modulo). Si el
      SDK agota su reintento, se escala de inmediato — no tiene sentido
      reintentar con un prompt distinto si la API no esta respondiendo.
    - Salida invalida (sin tool_use, o que no pasa el contrato de
      `ExtractionResult`): un reintento adicional con un prompt mas
      estricto. Si el segundo intento tampoco valida, se escala.

    Raises:
        LLMExtractionFailed: la API de Claude fallo de forma persistente, o
            la salida no paso el contrato ni tras el reintento estricto. El
            llamador debe tratar esto como senal de `handoff_human()`
            (SPEC.md seccion 7), nunca como excepcion sin manejar.
    """
    anthropic_client = client or AsyncAnthropic(
        api_key=get_settings().anthropic_api_key, max_retries=1
    )

    last_validation_error: ValidationError | None = None
    for strict in (False, True):
        try:
            raw = await _request_extraction(
                anthropic_client, message, strict=strict, request_id=request_id
            )
        except anthropic.APIError as exc:
            logger.error(
                "llm_extraction_api_error",
                extra={"request_id": request_id, "strict": strict, "error": str(exc)},
            )
            raise LLMExtractionFailed(
                "Claude API fallo de forma persistente tras su reintento interno"
            ) from exc

        if raw is None:
            continue

        sanitized = _sanitize_enum_violations(raw, request_id=request_id)
        try:
            result = ExtractionResult.model_validate(sanitized)
        except ValidationError as exc:
            last_validation_error = exc
            logger.warning(
                "llm_extraction_schema_invalid",
                extra={"request_id": request_id, "strict": strict, "error": str(exc)},
            )
            continue

        if result.confidence < 0.5:
            result = result.model_copy(update={"requires_clarification": True})
        return result

    logger.error(
        "llm_extraction_exhausted_retries",
        extra={"request_id": request_id, "error": str(last_validation_error)},
    )
    raise LLMExtractionFailed(
        "Extraccion invalida tras reintento con prompt estricto (SPEC.md seccion 3)"
    )
