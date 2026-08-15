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
from app.models.property import Property
from app.tools import LeadPersistenceError, PropertySearchError
from app.tools import create_lead as tool_create_lead
from app.tools import handoff_human as tool_handoff_human
from app.tools import search_database as tool_search_database
from app.tools import update_lead as tool_update_lead

logger = logging.getLogger(__name__)

# SPEC.md seccion 7, tabla de fallas: texto exacto para "Claude API falla"
# generalizado a cualquier falla de PostgreSQL en un tool de Fase 3 durante
# `handle_message()` -- mismo mensaje fail-safe para el usuario en todos los
# casos de falla tecnica irrecuperable de esta capa.
_TECHNICAL_ERROR_MESSAGE = "estoy teniendo problemas técnicos, un asesor te contacta"

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


def _lead_search_slots(lead: Lead) -> ExtractedEntities:
    """Los 4 slots de busqueda (SPEC.md seccion 1) tal como estan
    ACTUALMENTE persistidos en el `Lead`, normalizados al mismo tipo que
    `ExtractedEntities`. `lead.budget_max` es `Numeric` en la DB (`Decimal`);
    se normaliza a `float` para respetar el tipo de
    `ExtractedEntities.budget_max`.

    Usado tanto por `_merge_entities` (fusionar con los datos nuevos del
    mensaje) como por `handle_message` (capturar los criterios de la
    busqueda anterior ANTES de que `update_lead()` los sobreescriba este
    turno -- ver `_run_property_search`/`criteria_changed`, correccion post-QA
    de SPEC.md seccion 1).
    """
    return ExtractedEntities(
        location=lead.location,
        budget_max=float(lead.budget_max) if lead.budget_max is not None else None,
        bedrooms=lead.bedrooms,
        purpose=lead.purpose,
    )


def _merge_entities(lead: Lead, new_entities: ExtractedEntities) -> ExtractedEntities:
    """Funde `entities` del mensaje actual sobre los datos ya guardados en el
    `Lead`, sin pisar con `null` un campo ya conocido (SPEC.md seccion 1: los
    slots se acumulan a lo largo de varios mensajes, no solo del ultimo).

    No escribe en el `Lead` -- ver el docstring del modulo.
    """
    previous = _lead_search_slots(lead)
    return ExtractedEntities(
        location=new_entities.location if new_entities.location is not None else previous.location,
        budget_max=(
            new_entities.budget_max if new_entities.budget_max is not None else previous.budget_max
        ),
        bedrooms=new_entities.bedrooms if new_entities.bedrooms is not None else previous.bedrooms,
        purpose=new_entities.purpose if new_entities.purpose is not None else previous.purpose,
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
    message_id: UUID | None = None,
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
        message_id: opcional (Fase 3, Tarea 6). Si se provee, se asume que el
            `Message` YA fue persistido por el llamador (p.ej. `create_lead()`
            en el primer mensaje de una conversacion nueva, ver
            `handle_message()`) y esta funcion reutiliza esa fila en vez de
            insertar una duplicada con el mismo contenido. Si es `None`
            (default, comportamiento identico al de Fase 2), se inserta un
            `Message` nuevo como siempre.

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

        if message_id is not None:
            # Reutiliza el Message que `create_lead()` ya persistio en este
            # mismo turno (ver docstring de `message_id` arriba) -- evita
            # duplicar el primer mensaje de una conversacion nueva.
            message_row = db.get(Message, message_id)
            if message_row is None:
                # No deberia ocurrir en uso normal (el llamador acaba de
                # flushear ese Message en la misma transaccion, ver
                # `handle_message()`) -- fail-safe explicito de todos modos.
                db.rollback()
                raise OrchestratorPersistenceError(
                    f"message_id {message_id} no existe (se esperaba ya persistido)"
                )
        else:
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


# ---------------------------------------------------------------------------
# Fase 3, Tarea 6: conexion de las tools reales (create_lead, update_lead,
# search_database, handoff_human) al turno resuelto por
# `process_incoming_message` (arriba, Fase 2 -- sin modificar su contrato de
# negocio). `handle_message()` es el entrypoint completo que usaria un
# adaptador de canal (Web Chat/WhatsApp, Fase 6, todavia no construido).
# ---------------------------------------------------------------------------


class ToolExecutionError(OrchestratorError):
    """`handoff_human()` fallo mientras se intentaba escalar la conversacion
    (ya sea un escalamiento de negocio normal -- OFFER_HANDOFF -- o uno de
    fail-safe tras la falla de otro tool). SPEC.md seccion 7: "si
    handoff_human() mismo falla ... no hay a donde mas escalar" -- esta
    excepcion es ese callejon sin salida, se loguea como critico y se
    relanza; no hay otro mecanismo de fail-safe en este punto del turno.
    """


@dataclass(frozen=True)
class ExecutedTurnResult:
    """Resultado de `handle_message()`: el `TurnResult` de Fase 2 mas los
    efectos de la tool real que correspondio ejecutar segun
    `TurnResult.action`.

    `final_state` es el estado REAL de `ConversationState.current_state` una
    vez terminado el turno completo -- puede ser distinto de `turn.new_state`
    (que refleja unicamente el resultado de `process_incoming_message`,
    Fase 2, ANTES de que esta capa ejecute tools). El caso concreto:
    `turn.new_state == PROPERTY_SEARCH` es un estado transitorio del sistema
    (SPEC.md seccion 2, "automatico al entrar al estado") -- esta capa
    ejecuta `search_database()` en el mismo turno y avanza a
    `PRESENTING`/`DISCOVERING`/`HANDOFF` segun el resultado; `final_state` es
    el que quien consuma este resultado (Fase 6/7) debe usar para decidir que
    responder, no `turn.new_state`.

    `properties` solo se puebla cuando `turn.action` fue `SEARCH_PROPERTIES`
    (lista vacia si la busqueda no encontro resultados, `None` en cualquier
    otro caso -- distingue "no se busco" de "se busco y no hubo resultados").
    `handoff_id` solo se puebla si este turno disparo `handoff_human()`
    (accion `OFFER_HANDOFF`, o un fail-safe/`empty_search_2x` durante la
    busqueda). `technical_error`/`technical_error_message` senalan el caso de
    SPEC.md seccion 7 ("Claude API falla" generalizado a cualquier falla de
    PostgreSQL en un tool de esta capa): mensaje fijo de "problema tecnico"
    para el usuario, ademas del handoff ya disparado.
    """

    turn: TurnResult
    lead: Lead
    final_state: LeadStage
    properties: list[Property] | None = None
    handoff_id: UUID | None = None
    technical_error: bool = False
    technical_error_message: str | None = None


def _compose_handoff_summary(*, turn: TurnResult, message: str, extra: str | None = None) -> str:
    """Resumen simple del turno para `handoff_human(summary=...)`.

    SPEC.md seccion 7 describe el ideal (historial completo, propiedades
    vistas, documentos consultados, etc.) pero el enunciado de esta tarea
    acepta explicitamente "un resumen simple y honesto" en MVP, usando solo
    lo que ya esta disponible en este punto del turno (el mensaje que
    disparo el escalamiento + los slots conocidos/fusionados) -- sin
    reconstruir el historial completo de la conversacion, que no es
    responsabilidad de esta tarea.
    """
    entities = turn.merged_entities
    purpose_value = entities.purpose.value if entities.purpose is not None else None
    parts = [
        f"Ultimo mensaje del lead: {message!r}.",
        f"Intent detectado: {turn.extraction.intent.value} "
        f"(confidence={turn.extraction.confidence:.2f}).",
        "Datos conocidos: "
        f"location={entities.location!r}, budget_max={entities.budget_max!r}, "
        f"bedrooms={entities.bedrooms!r}, purpose={purpose_value!r}.",
        f"Estado de la conversacion: {turn.previous_state.value} -> {turn.new_state.value}.",
    ]
    if extra:
        parts.append(extra)
    return " ".join(parts)


def _invoke_handoff_human(
    db: Session,
    *,
    lead_id: UUID,
    reason: str,
    summary: str,
    conversation_id: UUID,
    request_id: str,
) -> UUID:
    """Wrapper de `handoff_human()` que trata su propia falla como el
    callejon sin salida de SPEC.md seccion 7 (ver `ToolExecutionError`).
    """
    try:
        return tool_handoff_human(
            db,
            lead_id=lead_id,
            reason=reason,
            summary=summary,
            conversation_id=conversation_id,
            request_id=request_id,
        )
    except LeadPersistenceError as exc:
        logger.critical(
            "handoff_human_failed_no_further_escalation",
            extra={
                "request_id": request_id,
                "conversation_id": str(conversation_id),
                "lead_id": str(lead_id),
                "reason": reason,
                "error": str(exc),
            },
        )
        raise ToolExecutionError(
            f"No se pudo escalar a humano (reason={reason!r}): PostgreSQL fallo y no "
            "hay otro mecanismo de fail-safe disponible (SPEC.md seccion 7)."
        ) from exc


def _fail_safe_handoff(
    db: Session,
    *,
    lead_id: UUID,
    conversation_id: UUID,
    request_id: str,
    reason: str,
    turn: TurnResult,
    message: str,
) -> ExecutedTurnResult:
    """SPEC.md seccion 7: cualquier falla de PostgreSQL en un tool de Fase 3
    durante este turno (`LeadPersistenceError`/`PropertySearchError`) se
    resuelve igual que cualquier otra falla tecnica -- mensaje fijo de
    "problema tecnico" + `handoff_human()`.

    Ademas de `Lead.stage` (que `handoff_human()` ya escribe), sincroniza
    `ConversationState.current_state` a `HANDOFF` -- si no, quedaria
    "atascado" en el estado previo (p.ej. `PROPERTY_SEARCH` si la falla fue
    en `search_database()`) mientras `Lead.stage` ya muestra `HANDOFF`,
    divergencia que el resto del modulo evita a proposito (ver docstring de
    `ConversationState` en `app/models/conversation_state.py`).
    """
    summary = _compose_handoff_summary(turn=turn, message=message, extra=f"Fallo tecnico: {reason}")
    handoff_id = _invoke_handoff_human(
        db,
        lead_id=lead_id,
        reason=reason,
        summary=summary,
        conversation_id=conversation_id,
        request_id=request_id,
    )

    state_row = _get_or_create_conversation_state(db, conversation_id)
    state_row.current_state = LeadStage.HANDOFF
    state_row.empty_search_count = 0
    state_row.no_response_count = 0
    state_row.last_transition_at = datetime.now(UTC)
    db.flush()

    lead = db.get(Lead, lead_id)
    if lead is None:  # pragma: no cover - ya validado antes de llegar aqui
        raise LeadNotFoundError(lead_id)
    return ExecutedTurnResult(
        turn=turn,
        lead=lead,
        final_state=LeadStage.HANDOFF,
        handoff_id=handoff_id,
        technical_error=True,
        technical_error_message=_TECHNICAL_ERROR_MESSAGE,
    )


def _run_property_search(
    db: Session,
    *,
    turn: TurnResult,
    lead: Lead,
    conversation_id: UUID,
    request_id: str,
    message: str,
    criteria_changed: bool = True,
) -> ExecutedTurnResult:
    """Ejecuta `search_database()` para el turno que acaba de entrar a
    `PROPERTY_SEARCH` y resuelve `results_found`/`results_empty` en el MISMO
    turno (SPEC.md seccion 2: `QUALIFYING -> PROPERTY_SEARCH` es automatico,
    y la busqueda que sigue tambien lo es -- no espera un nuevo mensaje del
    usuario). Incluye el caso "2 busquedas vacias seguidas -> HANDOFF"
    (seccion 1/2), disparando `handoff_human()` en ese mismo turno.

    `criteria_changed` (corregido tras QA, SPEC.md seccion 1: "resetea a 0
    en cuanto el usuario cambia cualquiera de los 4 criterios de busqueda"):
    decidido por `handle_message()` ANTES de llamar aqui, comparando los 4
    slots de `turn.merged_entities` contra los que el `Lead` tenia
    persistidos antes de que `update_lead()` los sobreescribiera este turno
    (`state_machine.transition()` es una funcion pura y no tiene esa
    visibilidad -- ver su docstring). Si `True` (incluye el primer intento de
    la conversacion, sin criterio anterior con que comparar), este intento de
    busqueda arranca con `empty_search_count=0` sin importar lo que tuviera
    persistido `ConversationState` -- es un intento nuevo, no continuacion
    del anterior. Default `True` para que llamadas directas (tests, smoke
    tests) sigan el comportamiento seguro por defecto sin tener que pasarlo
    explicitamente.
    """
    entities = turn.merged_entities
    # Invariante garantizada por `_resolve_turn`/`ENOUGH_DATA` (SPEC.md
    # seccion 1): solo se llega aqui con los 4 slots completos. Mismo
    # patron de assert de invariante que el resto de este modulo (ver
    # `resolved.fallback_action` mas arriba).
    assert entities.location is not None
    assert entities.budget_max is not None
    assert entities.bedrooms is not None
    assert entities.purpose is not None

    try:
        properties = tool_search_database(
            db,
            location=entities.location,
            budget_max=entities.budget_max,
            bedrooms=entities.bedrooms,
            purpose=entities.purpose,
            request_id=request_id,
        )
    except PropertySearchError:
        return _fail_safe_handoff(
            db,
            lead_id=lead.id,
            conversation_id=conversation_id,
            request_id=request_id,
            reason="property_search_failed",
            turn=turn,
            message=message,
        )

    state_row = _get_or_create_conversation_state(db, conversation_id)
    event = StateEvent.RESULTS_FOUND if properties else StateEvent.RESULTS_EMPTY
    # SPEC.md seccion 1: "resetea a 0 en cuanto el usuario cambia cualquiera
    # de los 4 criterios de busqueda (nueva vuelta de PROPERTY_SEARCH =
    # intento nuevo, no continuacion del anterior)" -- ver docstring de
    # `criteria_changed` arriba. `transition()` (funcion pura) no decide esto
    # por si sola, recibe el contador de entrada ya resuelto.
    starting_empty_search_count = 0 if criteria_changed else state_row.empty_search_count
    result = transition(
        LeadStage.PROPERTY_SEARCH,
        event,
        empty_search_count=starting_empty_search_count,
        no_response_count=state_row.no_response_count,
    )
    state_row.current_state = result.new_state
    state_row.empty_search_count = result.empty_search_count
    state_row.no_response_count = result.no_response_count
    if result.changed_state:
        state_row.last_transition_at = datetime.now(UTC)
    db.flush()

    logger.info(
        "property_search_executed",
        extra={
            "request_id": request_id,
            "conversation_id": str(conversation_id),
            "lead_id": str(lead.id),
            "tool": "search_database",
            "tool_result": "success" if properties else "empty",
            "result_count": len(properties),
            "new_state": result.new_state.value,
        },
    )

    if result.new_state is LeadStage.HANDOFF:
        # 2da busqueda vacia seguida (SPEC.md seccion 2).
        summary = _compose_handoff_summary(
            turn=turn,
            message=message,
            extra="2 busquedas de propiedades seguidas sin resultados.",
        )
        handoff_id = _invoke_handoff_human(
            db,
            lead_id=lead.id,
            reason="empty_search_2x",
            summary=summary,
            conversation_id=conversation_id,
            request_id=request_id,
        )
        return ExecutedTurnResult(
            turn=turn,
            lead=lead,
            final_state=LeadStage.HANDOFF,
            properties=[],
            handoff_id=handoff_id,
        )

    # RESULTS_FOUND -> PRESENTING (properties no vacia) o 1ra RESULTS_EMPTY
    # -> DISCOVERING (properties == []); ambos casos devuelven la lista real.
    return ExecutedTurnResult(
        turn=turn, lead=lead, final_state=result.new_state, properties=properties
    )


def _dispatch_action(
    db: Session,
    *,
    turn: TurnResult,
    lead: Lead,
    conversation_id: UUID,
    request_id: str,
    message: str,
    criteria_changed: bool = True,
) -> ExecutedTurnResult:
    """Ejecuta la tool (si alguna) que corresponde a `turn.action`.

    `criteria_changed` solo es relevante cuando `turn.action` es
    `SEARCH_PROPERTIES` -- ver `_run_property_search`. Se acepta aqui (en vez
    de leerlo directo en esa funcion) para que `handle_message()` sea el
    unico punto que lee el `Lead` pre-actualizacion y hace la comparacion.
    """
    if turn.action is OrchestratorAction.MARK_LOST:
        # SPEC.md seccion 1: "ya no me interesa" -> stage=LOST con motivo
        # registrado. SPEC.md seccion 4 no define una tool para esta
        # transicion (a diferencia de HANDOFF, que tiene handoff_human) --
        # se escribe Lead.stage directo, mismo criterio que
        # process_incoming_message ya escribe ConversationState.current_state
        # directo. El "motivo" queda registrado en el log estructurado: no
        # existe una columna de Lead para el motivo de perdida en el modelo
        # de datos de SPEC.md seccion 5.
        lead.stage = LeadStage.LOST
        db.flush()
        logger.info(
            "lead_marked_lost",
            extra={
                "request_id": request_id,
                "conversation_id": str(conversation_id),
                "lead_id": str(lead.id),
                "intent": turn.extraction.intent.value,
            },
        )
        return ExecutedTurnResult(turn=turn, lead=lead, final_state=turn.new_state)

    if turn.action is OrchestratorAction.OFFER_HANDOFF:
        summary = _compose_handoff_summary(turn=turn, message=message)
        handoff_id = _invoke_handoff_human(
            db,
            lead_id=lead.id,
            reason=turn.handoff_reason or "unspecified",
            summary=summary,
            conversation_id=conversation_id,
            request_id=request_id,
        )
        return ExecutedTurnResult(
            turn=turn, lead=lead, final_state=turn.new_state, handoff_id=handoff_id
        )

    if turn.action is OrchestratorAction.SEARCH_PROPERTIES:
        return _run_property_search(
            db,
            turn=turn,
            lead=lead,
            conversation_id=conversation_id,
            request_id=request_id,
            message=message,
            criteria_changed=criteria_changed,
        )

    # ASK_CLARIFICATION / REQUEST_MORE_INFO / ACKNOWLEDGE: ningun tool de
    # Fase 3 corresponde este turno (generacion del texto de vuelta al
    # usuario sigue fuera de alcance, ver docstring de `handle_message`).
    return ExecutedTurnResult(turn=turn, lead=lead, final_state=turn.new_state)


async def handle_message(
    db: Session,
    *,
    message: str,
    conversation_id: UUID | None = None,
    lead_id: UUID | None = None,
    channel: str | None = None,
    source: str | None = None,
    phone: str | None = None,
    llm_client: AsyncAnthropic | None = None,
) -> ExecutedTurnResult:
    """Entrypoint completo del agent engine para un mensaje entrante (Fase 3,
    Tarea 6): conecta `process_incoming_message()` (Fase 2, sin modificar su
    contrato de negocio) con las tools reales de `app/tools` (create_lead,
    update_lead, search_database, handoff_human).

    A diferencia de `process_incoming_message()` (que asume Lead/Conversation
    ya existentes y solo resuelve classificacion + state machine, sin
    ejecutar tools), esta es la funcion que usaria un adaptador de canal (Web
    Chat/WhatsApp, Fase 6, todavia no construido):

    1. Si `conversation_id`/`lead_id` no se proveen, crea el lead junto con
       su conversacion via `create_lead()` (SPEC.md seccion 1: "el lead nace
       en el primer mensaje entrante, incluso antes de conocer ningun
       slot"). El primer `Message` que crea `create_lead()` se reutiliza (no
       se duplica) al llamar `process_incoming_message()` a continuacion --
       ver el parametro `message_id` de esa funcion.
    2. Llama `process_incoming_message()` para resolver clasificacion +
       state machine (Fase 2).
    3. Si el mensaje trajo entities nuevas, las persiste con `update_lead()`
       usando los slots ya fusionados (`TurnResult.merged_entities` --
       SPEC.md seccion 4: "entities del LLM pasan por el contrato de la
       seccion 3 antes de llegar aqui").
    4. Ejecuta la tool que corresponda segun `TurnResult.action`:
       - `SEARCH_PROPERTIES`: `search_database()` + resuelve
         `results_found`/`results_empty` (incluyendo "2 busquedas vacias
         seguidas -> HANDOFF", SPEC.md seccion 2) en el MISMO turno, porque
         es una continuacion automatica del sistema, no un evento que espera
         un nuevo mensaje del usuario.
       - `OFFER_HANDOFF`: `handoff_human()` con el motivo ya resuelto por
         `process_incoming_message` (`TurnResult.handoff_reason`).
       - `MARK_LOST`: escribe `Lead.stage=LOST` directo (SPEC.md seccion 4 no
         define una tool para esta transicion).
       - `ASK_CLARIFICATION`/`REQUEST_MORE_INFO`/`ACKNOWLEDGE`: ningun tool
         corresponde este turno.

    Fail-safe (SPEC.md seccion 7): si `search_database()`/`update_lead()`
    lanzan `PropertySearchError`/`LeadPersistenceError`, se responde con el
    mensaje tecnico fijo (`ExecutedTurnResult.technical_error_message`) y se
    escala con `handoff_human()`. Si `handoff_human()` mismo falla (durante
    ese fail-safe o durante un `OFFER_HANDOFF` normal), se loguea como error
    critico y se relanza `ToolExecutionError` -- no hay a donde mas escalar.

    NO implementa `get_availability`/`book_meeting`/`cancel_meeting` (Fase 5,
    Calendar, fuera de alcance de esta tarea): los estados SCHEDULING/BOOKED
    ya quedan señalizados como `ACKNOWLEDGE` (sin accion) por
    `process_incoming_message`, sin cambios aqui.

    No genera el texto final de respuesta al usuario -- eso sigue siendo
    responsabilidad de una capa posterior (Fase 7 / demo); esta funcion deja
    todo lo necesario (`ExecutedTurnResult`) para componerlo.

    Args:
        db: sesion SQLAlchemy inyectada.
        message: contenido del mensaje entrante.
        conversation_id: conversacion ya existente. Debe proveerse junto con
            `lead_id`, o ninguno de los dos (primer mensaje).
        lead_id: lead ya existente. Mismo criterio que `conversation_id`.
        channel: `"web"`/`"whatsapp"` -- solo obligatorio cuando
            `conversation_id`/`lead_id` no se proveen.
        source: origen del lead -- mismo criterio que `channel`.
        phone: telefono del lead, o `None`. Solo relevante en la creacion.
        llm_client: cliente `AsyncAnthropic` inyectable, mismo patron que
            `process_incoming_message`.

    Raises:
        ValueError: `conversation_id`/`lead_id` provistos parcialmente, o
            falta `channel`/`source` para crear un lead nuevo.
        pydantic.ValidationError: datos invalidos para `create_lead()`
            (SPEC.md seccion 4) -- no toca la DB antes de validar.
        LeadPersistenceError: `create_lead()` fallo antes de que exista un
            `lead_id` al cual escalar -- no hay handoff posible en ese punto
            (FK obligatoria de `HumanHandoff` a `Lead`), se relanza tal cual;
            la capa API (fuera de esta tarea) decide el 503 (SPEC.md seccion
            7, mismo criterio que `OrchestratorPersistenceError`).
        ToolExecutionError: `handoff_human()` fallo durante un escalamiento
            -- fallo critico, no hay mas fallback.
        Cualquier excepcion de `process_incoming_message()` (ver su
            docstring): `ConversationNotFoundError`, `LeadNotFoundError`,
            `LeadConversationMismatchError`, `OrchestratorPersistenceError`.
    """
    request_id = str(uuid4())

    if (conversation_id is None) != (lead_id is None):
        raise ValueError("conversation_id y lead_id deben proveerse juntos o ninguno")

    created_message_id: UUID | None = None
    if conversation_id is None and lead_id is None:
        if channel is None or source is None:
            raise ValueError(
                "channel y source son obligatorios para crear un lead nuevo "
                "(conversation_id/lead_id no provistos)"
            )
        try:
            created = tool_create_lead(
                db,
                source=source,
                channel=channel,
                phone=phone,
                initial_message=message,
                request_id=request_id,
            )
        except LeadPersistenceError:
            # Fallo de PostgreSQL antes de que exista un lead_id: no hay a
            # quien escalar via handoff_human (FK obligatoria a Lead) -- se
            # relanza tal cual (ver docstring, Raises).
            logger.critical(
                "handle_message_create_lead_failed_no_handoff_possible",
                extra={"request_id": request_id},
            )
            raise
        conversation_id = created.conversation_id
        lead_id = created.lead_id
        created_message_id = created.message_id

    turn = await process_incoming_message(
        db,
        conversation_id=conversation_id,
        lead_id=lead_id,
        message=message,
        llm_client=llm_client,
        message_id=created_message_id,
    )

    lead = db.get(Lead, lead_id)
    if lead is None:  # pragma: no cover - ya validado dentro de process_incoming_message
        raise LeadNotFoundError(lead_id)

    # SPEC.md seccion 1 (corregido tras QA): se capturan los 4 criterios de
    # busqueda TAL COMO ESTABAN PERSISTIDOS antes de que `update_lead()` (mas
    # abajo) los sobreescriba con lo extraido este turno -- es la unica forma
    # de saber si el usuario realmente cambio algun criterio respecto al
    # intento de busqueda anterior. Ver docstring de
    # `_run_property_search`/`criteria_changed`.
    previous_search_slots = _lead_search_slots(lead)

    # SPEC.md seccion 4: persistir via update_lead() solo cuando el LLM
    # extrajo entities nuevas este turno (no en cada mensaje -- p.ej. un
    # "quiero hablar con un asesor" no trae entities y no amerita un write
    # de Lead sin cambios).
    new_entity_fields = turn.extraction.entities.model_dump(exclude_none=True)
    if new_entity_fields:
        fields_to_persist = turn.merged_entities.model_dump(exclude_none=True)
        try:
            lead = tool_update_lead(
                db, lead_id=lead_id, fields=fields_to_persist, request_id=request_id
            )
        except LeadPersistenceError:
            return _fail_safe_handoff(
                db,
                lead_id=lead_id,
                conversation_id=conversation_id,
                request_id=request_id,
                reason="lead_update_failed",
                turn=turn,
                message=message,
            )

    # SPEC.md seccion 1: "resetea a 0 en cuanto el usuario cambia cualquiera
    # de los 4 criterios de busqueda". Comparacion contra `turn.merged_entities`
    # (los slots que efectivamente se usaran si este turno dispara una
    # busqueda) -- solo tiene efecto cuando `turn.action` es
    # `SEARCH_PROPERTIES` (ver `_dispatch_action`/`_run_property_search`), se
    # calcula igual para cualquier turno porque es barato y mantiene un unico
    # punto de lectura del `Lead` pre-actualizacion.
    criteria_changed = previous_search_slots != turn.merged_entities

    return _dispatch_action(
        db,
        turn=turn,
        lead=lead,
        conversation_id=conversation_id,
        request_id=request_id,
        message=message,
        criteria_changed=criteria_changed,
    )
