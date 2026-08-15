"""Orquestador del turno del agent engine (Fase 2, Tarea 5).

Conecta lo construido en las tareas 1-4 del agent engine: clasificacion
determinista (`classifier.py`), extraccion via LLM (`llm_extraction.py`) y la
state machine formal (`state_machine.py`). Implementa SPEC.md secciones 1
(functional spec Real Estate), 2 (state machine formal), 3 (contrato de
extraccion) y 7 (error/handoff policy).

Alcance explicito de esta tarea (ver tambien los docstrings de los modulos
que reutiliza):
- Recibe un mensaje entrante de un lead/conversacion YA EXISTENTES.
  `create_lead()` (Fase 3) es quien crea Lead/Conversation en el primer
  mensaje real del sistema end-to-end; esta funcion no lo hace.
- No genera texto de respuesta para el usuario ni ejecuta ningun tool de
  Fase 3 (create_lead, update_lead, search_database, handoff_human,
  get_availability, book_meeting, cancel_meeting). El resultado
  (`TurnResult.action`) senala de forma inequivoca que le corresponde hacer
  a esa capa a continuacion, sin invocarla.
- No escribe los slots extraidos (location/budget_max/bedrooms/purpose) en
  el `Lead` directamente: eso es responsabilidad del tool `update_lead`
  (SPEC.md seccion 4, "entities del LLM pasan por el contrato de la seccion
  3 antes de llegar aquí"). Esta funcion SI necesita fusionar los datos ya
  conocidos del `Lead` con los nuevos del mensaje para decidir si ya hay
  suficiente informacion para avanzar (`ENOUGH_DATA`), y expone ese
  resultado fusionado en `TurnResult.merged_entities` para que el llamador
  se lo pase a `update_lead` despues.

Mapeo intent -> StateEvent pendiente de la Tarea 4 (`map_intent_to_event`
solo resuelve `human_request`/`not_interested`): se resuelve aqui, en
`_resolve_turn`, con el contexto que le faltaba al modulo puro de la state
machine (estado actual, datos ya conocidos del lead). Ver el docstring de
`_resolve_turn` para el detalle de cada caso.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from anthropic import AsyncAnthropic
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agent_engine.classifier import classify_deterministic
from app.agent_engine.llm_extraction import LLMExtractionFailed, extract_with_llm
from app.agent_engine.schemas import ExtractedEntities, ExtractionResult
from app.agent_engine.state_machine import (
    StateEvent,
    apply_automatic_transitions,
    map_intent_to_event,
    transition,
)
from app.models.conversation import Conversation
from app.models.conversation_state import ConversationState
from app.models.enums import LeadIntent, LeadStage, MessageRole
from app.models.lead import Lead
from app.models.message import Message

logger = logging.getLogger(__name__)

# SPEC.md seccion 1: los 4 slots requeridos antes de PROPERTY_SEARCH.
_REQUIRED_SLOTS = ("location", "budget_max", "bedrooms", "purpose")
# SPEC.md seccion 1/2: umbral de confianza para disparar ENOUGH_DATA.
_QUALIFYING_CONFIDENCE_THRESHOLD = 0.7


class OrchestratorError(Exception):
    """Error del orquestador (no es una falla de negocio comun del flujo)."""


class ConversationNotFoundError(OrchestratorError):
    """La conversacion no existe. Esta tarea asume que ya existe (Fase 3 la crea)."""

    def __init__(self, conversation_id: UUID) -> None:
        self.conversation_id = conversation_id
        super().__init__(f"Conversation {conversation_id} no existe")


class LeadNotFoundError(OrchestratorError):
    """El lead no existe. Esta tarea asume que ya existe (Fase 3 lo crea)."""

    def __init__(self, lead_id: UUID) -> None:
        self.lead_id = lead_id
        super().__init__(f"Lead {lead_id} no existe")


class LeadConversationMismatchError(OrchestratorError):
    """`conversation_id` y `lead_id` no corresponden entre si.

    Fail-safe explicito (CLAUDE.md): nunca se procesa un turno asumiendo en
    silencio una relacion Lead/Conversation que no existe en la DB.
    """

    def __init__(self, conversation_id: UUID, lead_id: UUID) -> None:
        self.conversation_id = conversation_id
        self.lead_id = lead_id
        super().__init__(f"Conversation {conversation_id} no pertenece al lead {lead_id}")


class OrchestratorPersistenceError(OrchestratorError):
    """PostgreSQL fallo durante la persistencia del turno (SPEC.md seccion 7:
    "PostgreSQL cae -> 503 logico, no se pierde el mensaje entrante (queda en
    cola/log), no se inventa respuesta"). El mensaje entrante ya quedo
    registrado en el log estructurado (`orchestrator_turn_received`) antes de
    intentar persistir -- el llamador (capa API, fuera de esta tarea) decide
    el 503/reintento/cola a partir de esta excepcion.
    """


class OrchestratorAction(enum.StrEnum):
    """Accion de alto nivel que le corresponde ejecutar a Fase 3 (tools)
    despues de este turno. Ningun valor de este enum ejecuta un tool: es la
    senal explicita para que la capa que si tiene los tools (create_lead,
    update_lead, search_database, handoff_human, book_meeting,
    cancel_meeting) sepa que hacer a continuacion.
    """

    # confidence < 0.5 (SPEC.md seccion 3): falta hacer una pregunta
    # aclaratoria antes de seguir, la state machine no avanzo este turno.
    ASK_CLARIFICATION = "ask_clarification"
    # DISCOVERING con slots incompletos o confidence < 0.7: seguir pidiendo
    # los datos que faltan, la state machine no avanzo este turno.
    REQUEST_MORE_INFO = "request_more_info"
    # Se entro a PROPERTY_SEARCH (via QUALIFYING automatico): corresponde
    # llamar search_database() con los 4 slots de `merged_entities`.
    SEARCH_PROPERTIES = "search_properties"
    # Se llego a HANDOFF: corresponde llamar handoff_human() con
    # `TurnResult.handoff_reason` como motivo.
    OFFER_HANDOFF = "offer_handoff"
    # Se llego a LOST (opt-out explicito): registrar el motivo, sin handoff.
    MARK_LOST = "mark_lost"
    # El mensaje se proceso y (si aplica) se registraron datos nuevos del
    # lead, pero no hay una accion de Fase 3 pendiente este turno.
    ACKNOWLEDGE = "acknowledge"


_ACTION_BY_STATE: dict[LeadStage, OrchestratorAction] = {
    LeadStage.PROPERTY_SEARCH: OrchestratorAction.SEARCH_PROPERTIES,
    LeadStage.HANDOFF: OrchestratorAction.OFFER_HANDOFF,
    LeadStage.LOST: OrchestratorAction.MARK_LOST,
}


@dataclass(frozen=True)
class TurnResult:
    """Resultado de procesar un mensaje entrante (un turno del agent engine)."""

    conversation_id: UUID
    lead_id: UUID
    message_id: UUID
    extraction: ExtractionResult
    previous_state: LeadStage
    new_state: LeadStage
    state_changed: bool
    action: OrchestratorAction
    merged_entities: ExtractedEntities
    handoff_reason: str | None = None


@dataclass(frozen=True)
class _ResolvedTurn:
    """Resultado intermedio de `_resolve_turn`: que evento (si alguno)
    corresponde disparar, y que accion/motivo usar si NO hay evento."""

    event: StateEvent | None
    fallback_action: OrchestratorAction | None
    handoff_reason: str | None
    merged_entities: ExtractedEntities


def _merge_entities(lead: Lead, new_entities: ExtractedEntities) -> ExtractedEntities:
    """Funde `entities` del mensaje actual sobre los datos ya guardados en el
    `Lead`, sin pisar con `null` un campo ya conocido (SPEC.md seccion 1: los
    slots se acumulan a lo largo de varios mensajes, no solo del ultimo).

    No escribe en el `Lead` -- ver el docstring del modulo. `lead.budget_max`
    es `Numeric` en la DB (`Decimal`); se normaliza a `float` para respetar
    el tipo de `ExtractedEntities.budget_max`.
    """
    return ExtractedEntities(
        location=new_entities.location if new_entities.location is not None else lead.location,
        budget_max=(
            new_entities.budget_max
            if new_entities.budget_max is not None
            else (float(lead.budget_max) if lead.budget_max is not None else None)
        ),
        bedrooms=new_entities.bedrooms if new_entities.bedrooms is not None else lead.bedrooms,
        purpose=new_entities.purpose if new_entities.purpose is not None else lead.purpose,
    )


def _slots_complete(entities: ExtractedEntities) -> bool:
    """SPEC.md seccion 1: los 4 campos obligatorios antes de PROPERTY_SEARCH."""
    return all(getattr(entities, slot) is not None for slot in _REQUIRED_SLOTS)


def _resolve_turn(
    extraction: ExtractionResult, *, current_state: LeadStage, lead: Lead
) -> _ResolvedTurn:
    """Completa el mapeo intent -> StateEvent que `map_intent_to_event()`
    dejo pendiente (ver su docstring en `state_machine.py`), usando el
    contexto que le faltaba a ese modulo puro: `current_state` y los datos
    ya conocidos del `lead`.

    Casos (SPEC.md secciones 1-2), en orden de evaluacion:
    1. `human_request`/`not_interested`: prioridad maxima, "se evalua antes
       que cualquier otra logica" -- se resuelve con `map_intent_to_event()`
       sin mirar `requires_clarification` ni el estado.
    2. `requires_clarification=True`: no se avanza la state machine este
       turno, se necesita una pregunta aclaratoria (SPEC.md seccion 3).
    3. `property_search`: solo dispara `ENOUGH_DATA` si `current_state` es
       DISCOVERING y los 4 slots fusionados estan completos con
       `confidence >= 0.7`. Si esta en DISCOVERING pero faltan datos o
       confianza, se pide mas informacion sin transicionar. Si el intent
       llega en un estado posterior a DISCOVERING (PROPERTY_SEARCH,
       PRESENTING, SCHEDULING, BOOKED, HANDOFF, LOST) SPEC.md seccion 2 no
       define una transicion para "el usuario agrega/corrige criterios" ahi
       -- decision de diseno de esta tarea: se actualizan los datos
       conocidos (`merged_entities`, para que Fase 3 los persista) sin mover
       el state machine, en vez de forzar una transicion no especificada.
    4. `cancel`: `CANCELLATION_REQUESTED` solo si `current_state` es BOOKED
       (hay cita agendada). Sin cita agendada, SPEC.md seccion 1 no define
       un "cancelar" generico -- se trata igual que una pregunta fuera de
       flujo (caso 5).
    5. `question`/`other`: sin FAQ en el MVP (SPEC.md seccion 1: "cualquier
       pregunta no cubierta por los slots ofrece handoff, nunca se ignora en
       silencio"). Se reutiliza el evento universal `HUMAN_REQUEST` porque
       es valido desde cualquier `current_state` y su efecto (transicion a
       HANDOFF) es exactamente el que pide la seccion 1 para estos casos --
       SPEC.md seccion 2 no define un `StateEvent` propio para "pregunta sin
       FAQ" o "cancelacion sin cita", asi que no se inventa uno nuevo.
    """
    merged = _merge_entities(lead, extraction.entities)

    direct_event = map_intent_to_event(extraction.intent)
    if direct_event is not None:
        reason = "human_request_explicit" if direct_event is StateEvent.HUMAN_REQUEST else None
        return _ResolvedTurn(direct_event, None, reason, merged)

    if extraction.requires_clarification:
        return _ResolvedTurn(None, OrchestratorAction.ASK_CLARIFICATION, None, merged)

    if extraction.intent is LeadIntent.PROPERTY_SEARCH:
        if current_state is LeadStage.DISCOVERING:
            enough_confidence = extraction.confidence >= _QUALIFYING_CONFIDENCE_THRESHOLD
            if _slots_complete(merged) and enough_confidence:
                return _ResolvedTurn(StateEvent.ENOUGH_DATA, None, None, merged)
            return _ResolvedTurn(None, OrchestratorAction.REQUEST_MORE_INFO, None, merged)
        return _ResolvedTurn(None, OrchestratorAction.ACKNOWLEDGE, None, merged)

    if extraction.intent is LeadIntent.CANCEL:
        if current_state is LeadStage.BOOKED:
            return _ResolvedTurn(
                StateEvent.CANCELLATION_REQUESTED,
                None,
                "cancellation_with_meeting_booked",
                merged,
            )
        return _ResolvedTurn(
            StateEvent.HUMAN_REQUEST, None, "cancel_without_scheduled_meeting", merged
        )

    # LeadIntent.QUESTION / LeadIntent.OTHER
    return _ResolvedTurn(StateEvent.HUMAN_REQUEST, None, "unanswered_question_no_faq", merged)


def _get_or_create_conversation_state(db: Session, conversation_id: UUID) -> ConversationState:
    """1-a-1 con `Conversation` (SPEC.md seccion 5). Si la fila todavia no
    existe (p.ej. `Conversation` recien creada por `create_lead`, Fase 3, sin
    inicializar su estado todavia) se crea con los defaults del modelo
    (`current_state=NEW`, contadores en 0).
    """
    stmt = select(ConversationState).where(ConversationState.conversation_id == conversation_id)
    state_row = db.execute(stmt).scalar_one_or_none()
    if state_row is None:
        state_row = ConversationState(conversation_id=conversation_id)
        db.add(state_row)
        db.flush()
    return state_row


async def process_incoming_message(
    db: Session,
    *,
    conversation_id: UUID,
    lead_id: UUID,
    message: str,
    llm_client: AsyncAnthropic | None = None,
) -> TurnResult:
    """Procesa un mensaje entrante de un lead/conversacion ya existentes (un
    turno del agent engine). Implementa SPEC.md secciones 1, 2, 3 y 7.

    Flujo:
    1. Clasifica el mensaje: `classify_deterministic()` primero, y si
       devuelve `None`, `extract_with_llm()`. Si esta ultima levanta
       `LLMExtractionFailed` (SPEC.md seccion 7: "Claude API falla"), el
       turno se resuelve igual que un `human_request` (evento universal,
       valido desde cualquier estado) con `handoff_reason="llm_extraction_failed"`.
    2. Si el estado actual es NEW o NURTURE y el intent no es ya universal
       (`human_request`/`not_interested`), aplica primero `NEW_MESSAGE`
       (SPEC.md seccion 2: "NEW -> DISCOVERING: primer mensaje entrante
       procesado"; NURTURE se reactiva igual).
    3. Resuelve el `StateEvent` sustantivo con `_resolve_turn()` (mapeo
       intent -> evento pendiente de la Tarea 4).
    4. Si hay evento, aplica `transition()` y, si el nuevo estado es
       QUALIFYING, `apply_automatic_transitions()` (SPEC.md seccion 2:
       unica transicion automatica).
    5. Persiste el `Message` entrante y el `ConversationState` resultante
       (sin hacer `commit`: la transaccion es responsabilidad del llamador,
       este modulo solo hace `flush()` para que `message_id` este
       disponible en el resultado).

    Toda lectura/escritura de DB del turno (pasos 2-5, incluida la lectura
    de `Conversation`/`Lead` y `_get_or_create_conversation_state`) esta
    cubierta por un unico `try/except SQLAlchemyError` (rollback +
    `OrchestratorPersistenceError`, SPEC.md seccion 7) -- no solo el
    `flush()` final, porque el autoflush de SQLAlchemy puede disparar un
    flush durante cualquier lectura intermedia tambien.

    No genera texto de respuesta ni ejecuta tools de Fase 3 -- ver
    `TurnResult.action` para la accion de alto nivel que le corresponde a
    esa capa.

    Args:
        db: sesion SQLAlchemy inyectada (mismo patron que `app.database.get_db`).
        conversation_id: conversacion ya existente (creada en Fase 3).
        lead_id: lead ya existente (creado en Fase 3).
        message: contenido de texto del mensaje entrante.
        llm_client: cliente `AsyncAnthropic` inyectable para tests, igual
            que `extract_with_llm()`.

    Raises:
        ConversationNotFoundError: `conversation_id` no existe.
        LeadNotFoundError: `lead_id` no existe.
        LeadConversationMismatchError: `conversation_id` no pertenece al `lead_id` dado.
        OrchestratorPersistenceError: PostgreSQL fallo durante la persistencia (seccion 7).
    """
    # SPEC.md seccion 10 item 5 exige `request_id` en los logs estructurados.
    # No existe un request_id real de HTTP en este punto del sprint (no hay
    # todavia un router/middleware de Fase 3 que lo genere y lo pase para
    # abajo), asi que se genera uno nuevo por turno aqui mismo -- suficiente
    # para correlacionar todas las lineas de log de un mismo
    # `process_incoming_message()`, incluidas las de `extract_with_llm()`.
    request_id = str(uuid4())

    logger.info(
        "orchestrator_turn_received",
        extra={
            "request_id": request_id,
            "conversation_id": str(conversation_id),
            "lead_id": str(lead_id),
        },
    )

    # SPEC.md seccion 7 ("PostgreSQL cae -> 503 logico ... no se inventa
    # respuesta") aplica a TODA lectura/escritura de DB de este turno, no
    # solo al flush final: el autoflush de SQLAlchemy puede disparar un
    # flush durante cualquiera de los `db.get()`/`db.execute()` de mas abajo
    # (incluido el que hace `_get_or_create_conversation_state`), asi que un
    # unico bloque try/except cubre desde la primera lectura hasta el flush
    # final -- la logica de negocio pura que queda en medio (extraccion,
    # resolucion de evento, transiciones) no toca DB y por lo tanto nunca
    # dispara este `except`, pero queda dentro del bloque porque partirlo en
    # dos ubicaciones distintas duplicaria el manejo de error sin necesidad.
    try:
        conversation = db.get(Conversation, conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(conversation_id)
        if conversation.lead_id != lead_id:
            raise LeadConversationMismatchError(conversation_id, lead_id)

        lead = db.get(Lead, lead_id)
        if lead is None:
            raise LeadNotFoundError(lead_id)

        state_row = _get_or_create_conversation_state(db, conversation_id)

        previous_state = state_row.current_state
        current_state = previous_state
        empty_search_count = state_row.empty_search_count
        no_response_count = state_row.no_response_count
        state_changed = False

        extraction = classify_deterministic(message)
        resolved: _ResolvedTurn | None = None
        if extraction is None:
            try:
                extraction = await extract_with_llm(
                    message, client=llm_client, request_id=request_id
                )
            except LLMExtractionFailed as exc:
                logger.error(
                    "orchestrator_llm_extraction_failed",
                    extra={
                        "request_id": request_id,
                        "conversation_id": str(conversation_id),
                        "lead_id": str(lead_id),
                        "error": str(exc),
                    },
                )
                extraction = ExtractionResult(
                    intent=LeadIntent.OTHER, confidence=0.0, requires_clarification=False
                )
                resolved = _ResolvedTurn(
                    event=StateEvent.HUMAN_REQUEST,
                    fallback_action=None,
                    handoff_reason="llm_extraction_failed",
                    merged_entities=_merge_entities(lead, extraction.entities),
                )

        if resolved is None:
            # SPEC.md seccion 1: human_request/not_interested tienen
            # prioridad maxima y saltan directo a su destino sin pasar por
            # DISCOVERING primero -- por eso el bootstrap de NEW_MESSAGE se
            # salta en ese caso.
            is_universal_intent = map_intent_to_event(extraction.intent) is not None
            if not is_universal_intent and current_state in (LeadStage.NEW, LeadStage.NURTURE):
                bootstrap = transition(
                    current_state,
                    StateEvent.NEW_MESSAGE,
                    empty_search_count=empty_search_count,
                    no_response_count=no_response_count,
                )
                current_state = bootstrap.new_state
                empty_search_count = bootstrap.empty_search_count
                no_response_count = bootstrap.no_response_count
                state_changed = state_changed or bootstrap.changed_state

            resolved = _resolve_turn(extraction, current_state=current_state, lead=lead)

        if resolved.event is not None:
            result = transition(
                current_state,
                resolved.event,
                empty_search_count=empty_search_count,
                no_response_count=no_response_count,
            )
            current_state = result.new_state
            empty_search_count = result.empty_search_count
            no_response_count = result.no_response_count
            state_changed = state_changed or result.changed_state

            auto_state = apply_automatic_transitions(current_state)
            if auto_state != current_state:
                current_state = auto_state
                state_changed = True

            action = _ACTION_BY_STATE.get(current_state, OrchestratorAction.ACKNOWLEDGE)
            handoff_reason = (
                resolved.handoff_reason if current_state is LeadStage.HANDOFF else None
            )
        else:
            # invariante: ver _ResolvedTurn/_resolve_turn
            assert resolved.fallback_action is not None
            action = resolved.fallback_action
            handoff_reason = None

        message_row = Message(
            conversation_id=conversation_id, role=MessageRole.USER, content=message
        )
        db.add(message_row)

        state_row.current_state = current_state
        state_row.empty_search_count = empty_search_count
        state_row.no_response_count = no_response_count
        if state_changed:
            state_row.last_transition_at = datetime.now(UTC)

        db.flush()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error(
            "orchestrator_persistence_failed",
            extra={
                "request_id": request_id,
                "conversation_id": str(conversation_id),
                "lead_id": str(lead_id),
                "error": str(exc),
            },
        )
        raise OrchestratorPersistenceError(
            "No se pudo persistir el turno (SPEC.md seccion 7): PostgreSQL fallo"
        ) from exc

    logger.info(
        "orchestrator_turn_processed",
        extra={
            "request_id": request_id,
            "conversation_id": str(conversation_id),
            "lead_id": str(lead_id),
            "intent": extraction.intent.value,
            "confidence": extraction.confidence,
            "previous_state": previous_state.value,
            "new_state": current_state.value,
            "action": action.value,
        },
    )

    return TurnResult(
        conversation_id=conversation_id,
        lead_id=lead_id,
        message_id=message_row.id,
        extraction=extraction,
        previous_state=previous_state,
        new_state=current_state,
        state_changed=state_changed,
        action=action,
        merged_entities=resolved.merged_entities,
        handoff_reason=handoff_reason,
    )
