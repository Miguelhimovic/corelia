"""Tool `create_lead()` (SPEC.md seccion 4, Tool Contracts).

Se invoca en el primer mensaje entrante de un lead, sin precondicion alguna
(SPEC.md: "Precondicion: ninguna (se llama en el primer mensaje)"). Ademas de
crear el `Lead`, crea la `Conversation` y el primer `Message` en la misma
operacion -- ver el docstring de `CreateLeadResult`
(`app/tools/schemas.py`) para por que el contrato de retorno se amplia mas
alla de solo `LeadID`.

No crea `ConversationState`: el orquestador (Fase 2, Tarea 5,
`_get_or_create_conversation_state`) ya la crea perezosamente con sus
defaults (`current_state=NEW`, contadores en 0) la primera vez que procesa un
turno de esa `Conversation` -- duplicar esa creacion aqui arriesgaria que
ambos lugares diverjan en los defaults.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import DEFAULT_TENANT_ID
from app.models.conversation import Conversation
from app.models.enums import MessageRole
from app.models.lead import Lead
from app.models.message import Message
from app.tools.errors import LeadPersistenceError
from app.tools.schemas import CreateLeadInput, CreateLeadResult

logger = logging.getLogger(__name__)


def create_lead(
    db: Session,
    *,
    source: str,
    channel: str,
    phone: str | None,
    initial_message: str,
    request_id: str | None = None,
) -> CreateLeadResult:
    """Crea un `Lead` nuevo junto con su `Conversation` y primer `Message`.

    Se llama en el primer mensaje entrante de un canal (SPEC.md seccion 1:
    "Cuando se crea el Lead: en el primer mensaje entrante, incluso antes de
    conocer ningun slot"), por eso no valida que el lead no exista todavia --
    no hay una clave natural (telefono puede ser `None` en Web Chat) contra
    la cual deduplicar en el MVP.

    Efecto en la DB (una sola transaccion logica, sin `commit`: igual que
    `orchestrator.process_incoming_message`, la transaccion es
    responsabilidad del llamador, esta funcion solo hace `flush()`):
    - `Lead`: `tenant_id` fijo (`DEFAULT_TENANT_ID`, CLAUDE.md principio #3),
      `stage=NEW` y `score=0` por default del modelo, `last_contact_at`
      seteado al timestamp de creacion, `next_contact_at` y el resto de
      campos (`name/email/intent/location/budget_max/bedrooms/purpose`)
      quedan `NULL` -- SPEC.md seccion 5: "campos no provistos por los
      parametros quedan NULL".
    - `Conversation`: vinculada al `Lead` recien creado, mismo `channel`.
    - `Message`: `role=USER`, `content=initial_message`, vinculado a la
      `Conversation` recien creada.

    Args:
        db: sesion SQLAlchemy inyectada (mismo patron que `app.database.get_db`).
        source: origen del lead (p.ej. campana, landing, referido). Texto
            libre no vacio.
        channel: `"web"` o `"whatsapp"` (SPEC.md seccion 4). Cualquier otro
            valor es un error de validacion.
        phone: telefono del lead, o `None` (v.g. un primer contacto por Web
            Chat sin telefono todavia). Si se provee, debe matchear un
            formato E.164-ish (ver `CreateLeadInput`).
        initial_message: contenido del primer mensaje entrante. No puede
            estar vacio.
        request_id: opcional, solo para logging (SPEC.md seccion 10 item 5).
            Si no se provee se genera uno nuevo, mismo patron que
            `orchestrator.process_incoming_message`.

    Returns:
        `CreateLeadResult` con `lead_id`, `conversation_id` y `message_id`.

    Raises:
        pydantic.ValidationError: `channel`/`phone`/`source`/`initial_message`
            invalidos (SPEC.md seccion 4: "teléfono/canal inválido -> error
            de validación, no crea el lead") -- no se toca la DB antes de
            validar, asi que ningun registro parcial queda creado.
        LeadPersistenceError: PostgreSQL fallo durante la persistencia
            (SPEC.md seccion 7).
    """
    request_id = request_id or str(uuid4())

    try:
        validated = CreateLeadInput.model_validate(
            {
                "source": source,
                "channel": channel,
                "phone": phone,
                "initial_message": initial_message,
            }
        )
    except ValidationError as exc:
        logger.warning(
            "create_lead_validation_failed",
            extra={
                "request_id": request_id,
                "tool": "create_lead",
                "tool_result": "error",
                "error": str(exc),
            },
        )
        raise

    try:
        lead = Lead(
            tenant_id=DEFAULT_TENANT_ID,
            channel=validated.channel,
            source=validated.source,
            phone=validated.phone,
            last_contact_at=datetime.now(UTC),
        )
        db.add(lead)
        db.flush()

        conversation = Conversation(
            tenant_id=DEFAULT_TENANT_ID, lead_id=lead.id, channel=validated.channel
        )
        db.add(conversation)
        db.flush()

        message = Message(
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content=validated.initial_message,
        )
        db.add(message)
        db.flush()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error(
            "create_lead_persistence_failed",
            extra={
                "request_id": request_id,
                "tool": "create_lead",
                "tool_result": "error",
                "error": str(exc),
            },
        )
        raise LeadPersistenceError(
            "No se pudo crear el lead (SPEC.md seccion 7): PostgreSQL fallo"
        ) from exc

    logger.info(
        "create_lead_succeeded",
        extra={
            "request_id": request_id,
            "tool": "create_lead",
            "tool_result": "success",
            "lead_id": str(lead.id),
            "conversation_id": str(conversation.id),
            "channel": validated.channel.value,
        },
    )

    return CreateLeadResult(
        lead_id=lead.id, conversation_id=conversation.id, message_id=message.id
    )
