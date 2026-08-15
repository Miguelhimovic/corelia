"""Tool `handoff_human()` (SPEC.md seccion 4, Tool Contracts).

Via legitima del state machine para llegar a `HANDOFF` (SPEC.md seccion 2:
`* -> HANDOFF : human_request explicito`, y varias otras transiciones que
llegan al mismo estado -- ver seccion 1: "Pide un humano", "2 busquedas
vacias seguidas", falla irrecuperable de Claude API, etc.). Es la unica tool
que tiene permitido tocar `Lead.stage` directamente (a diferencia de
`update_lead()`, que la rechaza a proposito -- ver `UpdateLeadFields` en
`app/tools/schemas.py`): esta funcion ES la implementacion de esa transicion,
no un atajo alrededor de ella.

En MVP la "notificacion" del flujo de Human Handoff (SPEC.md seccion 7:
"Notificacion (canal a definir en implementacion: email/Slack)") es un log
estructurado en nivel WARNING -- no hay integracion real de email/Slack
todavia (eso es Fase 2/3, fuera de alcance de este sprint). El log de exito
de esta tool por eso se emite en WARNING en vez de INFO (a diferencia de
`create_lead`/`update_lead`/`search_database`): no es solo un registro de
auditoria, es el mecanismo de notificacion en si mismo.
"""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.enums import LeadStage
from app.models.human_handoff import HumanHandoff
from app.models.lead import Lead
from app.tools.errors import LeadNotFoundError, LeadPersistenceError
from app.tools.schemas import HandoffHumanInput

logger = logging.getLogger(__name__)


def handoff_human(
    db: Session,
    *,
    lead_id: UUID,
    reason: str,
    summary: str,
    conversation_id: UUID | None = None,
    request_id: str | None = None,
) -> UUID:
    """Escala la conversacion a un asesor humano.

    Efectos secundarios, todos en la misma transaccion logica (sin `commit`:
    igual que el resto de `app/tools`, la transaccion es responsabilidad de
    quien llama):
    - Crea `HumanHandoff` con `status=OPEN` y `assigned_to=NULL` (SPEC.md
      seccion 5: no hay tabla de asesores humanos en MVP, la asignacion es
      manual y fuera del sistema).
    - Actualiza `Lead.stage = HANDOFF` -- excepcion deliberada a la regla
      general de que `stage` solo lo mueve el state machine via esta tool,
      nunca via `update_lead()` (SPEC.md seccion 2, transiciones `* ->
      HANDOFF`).
    - Emite el log de nivel WARNING que en MVP hace las veces de
      notificacion (SPEC.md seccion 7).

    No construye el `summary` a partir del historial de la conversacion:
    SPEC.md seccion 7 describe que informacion "idealmente" deberia llegar al
    humano (resumen, presupuesto, historial, propiedades vistas, etc.), pero
    el contrato de esta funcion (seccion 4) solo recibe `reason`/`summary` ya
    compuestos. Componer ese contexto rico es responsabilidad de quien llama
    (el orquestador, que tiene visibilidad del turno completo), no de esta
    tool.

    Args:
        db: sesion SQLAlchemy inyectada (mismo patron que `app.database.get_db`).
        lead_id: debe corresponder a un `Lead` existente.
        reason: motivo corto y categorico del escalamiento (p.ej.
            "human_request", "calendar_error", "empty_search_x2"). Se loguea
            tal cual -- debe ser texto corto, no un volcado de conversacion.
        summary: resumen ya compuesto por quien llama (ver arriba). No se
            incluye en el log de WARNING: puede contener datos personales del
            lead (SPEC.md seccion 8, "logs sin informacion sensible ...
            usar IDs"), asi que solo se persiste en `HumanHandoff.summary`,
            nunca se imprime en logs.
        conversation_id: opcional, solo para logging -- si quien llama ya
            tiene la conversacion en contexto (SPEC.md seccion 10 item 5
            pide `conversation_id` como campo estandar de logs cuando esta
            disponible). Esta tool no la valida ni la persiste, es
            puramente informativa.
        request_id: opcional, solo para logging. Si no se provee se genera
            uno nuevo, mismo patron que el resto de `app/tools`.

    Returns:
        El `id` (`HandoffID`) del `HumanHandoff` recien creado.

    Raises:
        pydantic.ValidationError: `reason`/`summary` vacios o `lead_id`
            invalido.
        LeadNotFoundError: `lead_id` no existe (SPEC.md seccion 4, mismo
            patron que `update_lead`: "404 logico, se loguea y se responde
            con handoff" -- la decision de que hacer con ese error queda del
            lado de quien llama).
        LeadPersistenceError: PostgreSQL fallo durante la persistencia
            (SPEC.md seccion 7).
    """
    request_id = request_id or str(uuid4())

    try:
        validated = HandoffHumanInput.model_validate(
            {"lead_id": lead_id, "reason": reason, "summary": summary}
        )
    except ValidationError as exc:
        logger.warning(
            "handoff_human_validation_failed",
            extra={
                "request_id": request_id,
                "conversation_id": str(conversation_id) if conversation_id else None,
                "tool": "handoff_human",
                "tool_result": "error",
                "lead_id": str(lead_id),
                "error": str(exc),
            },
        )
        raise

    try:
        lead = db.get(Lead, validated.lead_id)
        if lead is None:
            logger.warning(
                "handoff_human_lead_not_found",
                extra={
                    "request_id": request_id,
                    "conversation_id": str(conversation_id) if conversation_id else None,
                    "tool": "handoff_human",
                    "tool_result": "error",
                    "lead_id": str(validated.lead_id),
                },
            )
            raise LeadNotFoundError(validated.lead_id)

        handoff = HumanHandoff(
            lead_id=lead.id,
            reason=validated.reason,
            summary=validated.summary,
        )
        db.add(handoff)
        db.flush()

        lead.stage = LeadStage.HANDOFF
        db.flush()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error(
            "handoff_human_persistence_failed",
            extra={
                "request_id": request_id,
                "conversation_id": str(conversation_id) if conversation_id else None,
                "tool": "handoff_human",
                "tool_result": "error",
                "lead_id": str(validated.lead_id),
                "error": str(exc),
            },
        )
        raise LeadPersistenceError(
            "No se pudo crear el handoff (SPEC.md seccion 7): PostgreSQL fallo"
        ) from exc

    # Nivel WARNING deliberado (ver docstring del modulo): en MVP este log ES
    # la notificacion de SPEC.md seccion 7, no solo un registro de exito.
    logger.warning(
        "handoff_human_triggered",
        extra={
            "request_id": request_id,
            "conversation_id": str(conversation_id) if conversation_id else None,
            "tool": "handoff_human",
            "tool_result": "success",
            "handoff_id": str(handoff.id),
            "lead_id": str(lead.id),
            "reason": validated.reason,
        },
    )

    return handoff.id
