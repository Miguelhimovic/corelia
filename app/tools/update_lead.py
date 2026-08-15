"""Tool `update_lead()` (SPEC.md seccion 4, Tool Contracts).

Actualizacion parcial de un `Lead` ya existente. Ver `UpdateLeadFields`
(`app/tools/schemas.py`) para el dominio exacto de campos aceptados y por que
`stage`/`score` se rechazan en vez de ignorarse en silencio.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.lead import Lead
from app.tools.errors import LeadNotFoundError, LeadPersistenceError
from app.tools.schemas import UpdateLeadFields

logger = logging.getLogger(__name__)


def update_lead(
    db: Session,
    *,
    lead_id: UUID,
    fields: dict[str, Any],
    request_id: str | None = None,
) -> Lead:
    """Actualiza parcialmente un `Lead` ya existente.

    Solo los campos presentes en `fields` se modifican (actualizacion
    parcial, no reemplazo completo) -- una clave ausente en `fields` deja el
    valor actual del `Lead` intacto; una clave presente con valor `None`
    limpia ese campo explicitamente.

    `stage` y `score` (pipeline) nunca son actualizables via esta tool
    (SPEC.md seccion 5, precision cerrada para la Tarea 3): si `fields` los
    incluye, la validacion los rechaza con un error en vez de ignorarlos en
    silencio -- ignorar en silencio ocultaria un bug real de quien llama a la
    tool (p.ej. el orquestador tratando de mover el state machine a traves de
    esta tool en vez de la logica de `app.agent_engine.state_machine`, que es
    la unica duena de esas 2 columnas).

    Args:
        db: sesion SQLAlchemy inyectada (mismo patron que `app.database.get_db`).
        lead_id: debe corresponder a un `Lead` existente.
        fields: subconjunto de `UpdateLeadFields` a modificar. Cualquier
            clave fuera de ese dominio (incluidos `stage`/`score`, o
            columnas de identidad como `tenant_id`/`channel`) es un error de
            validacion.
        request_id: opcional, solo para logging (SPEC.md seccion 10 item 5).
            Si no se provee se genera uno nuevo, mismo patron que
            `orchestrator.process_incoming_message`.

    Returns:
        El `Lead` actualizado.

    Raises:
        pydantic.ValidationError: `fields` contiene una clave fuera del
            schema de `Lead` (incluye `stage`/`score`) o un valor de tipo
            invalido (SPEC.md seccion 4: "Validacion: solo campos del schema
            de Lead").
        LeadNotFoundError: `lead_id` no existe (SPEC.md seccion 4: "404
            logico, se loguea y se responde con handoff" -- el logueo de
            este caso y la decision de handoff quedan del lado del llamador,
            que es quien tiene el contexto de conversacion/turno).
        LeadPersistenceError: PostgreSQL fallo durante la persistencia
            (SPEC.md seccion 7).
    """
    request_id = request_id or str(uuid4())

    try:
        validated = UpdateLeadFields.model_validate(fields)
    except ValidationError as exc:
        logger.warning(
            "update_lead_validation_failed",
            extra={
                "request_id": request_id,
                "tool": "update_lead",
                "tool_result": "error",
                "lead_id": str(lead_id),
                "error": str(exc),
            },
        )
        raise

    update_values = validated.model_dump(exclude_unset=True)

    try:
        lead = db.get(Lead, lead_id)
        if lead is None:
            logger.warning(
                "update_lead_not_found",
                extra={
                    "request_id": request_id,
                    "tool": "update_lead",
                    "tool_result": "error",
                    "lead_id": str(lead_id),
                },
            )
            raise LeadNotFoundError(lead_id)

        for field_name, value in update_values.items():
            setattr(lead, field_name, value)

        db.flush()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error(
            "update_lead_persistence_failed",
            extra={
                "request_id": request_id,
                "tool": "update_lead",
                "tool_result": "error",
                "lead_id": str(lead_id),
                "error": str(exc),
            },
        )
        raise LeadPersistenceError(
            "No se pudo actualizar el lead (SPEC.md seccion 7): PostgreSQL fallo"
        ) from exc

    logger.info(
        "update_lead_succeeded",
        extra={
            "request_id": request_id,
            "tool": "update_lead",
            "tool_result": "success",
            "lead_id": str(lead_id),
            "updated_fields": sorted(update_values.keys()),
        },
    )

    return lead
