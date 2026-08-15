"""Configuracion de logging estructurado (SPEC.md seccion 10, item 5).

Logs estructurados simples en JSON, sin OTel/Grafana -- CLAUDE.md exige
explicitamente "logs estructurados simples" para el MVP, no una plataforma
de observabilidad. Este modulo NO se auto-ejecuta al importar
`app.agent_engine.*`: los modulos de negocio solo hacen
`logging.getLogger(__name__)` (patron estandar de `logging`), y
`configure_logging()` se llama una unica vez desde el entrypoint de la app
(`app/main.py`). Antes de este modulo no existia ninguna configuracion de
logging en el proyecto: el root logger quedaba en su nivel por defecto
(WARNING), asi que los `logger.info(...)` de `agent_engine` (p.ej.
`orchestrator_turn_processed`) nunca se emitian, y los campos de
`extra={...}` se descartaban en silencio por falta de un formatter que los
referenciara -- hallazgo de QA en la revision de Fase 2.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

# Atributos que `logging.LogRecord` ya trae por defecto. Cualquier clave que
# un call site agregue via `logger.info(..., extra={...})` NO esta en este
# set, y por lo tanto se serializa como campo estructurado adicional en
# `StructuredJsonFormatter.format()` (request_id, conversation_id, lead_id,
# tool, tool_result, latency_ms, tokens, error, etc. -- SPEC.md seccion 10).
_STANDARD_LOG_RECORD_ATTRS = frozenset(
    logging.LogRecord(
        name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None
    ).__dict__.keys()
) | {"message", "asctime", "taskName"}


class StructuredJsonFormatter(logging.Formatter):
    """Formatter minimo: una linea JSON por registro, con `timestamp`,
    `level`, `logger`, `message` y TODOS los campos pasados via `extra=`
    (sin filtrar ninguno -- cada call site decide cuales aplican segun
    SPEC.md seccion 10: request_id, conversation_id, lead_id, tool,
    tool_result, LLM latency, LLM tokens, error, timestamp).
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_LOG_RECORD_ATTRS:
                continue
            payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        # default=str: algunos valores de `extra` (UUID, Decimal, enums) no
        # son JSON-serializables nativamente; para logs no vale la pena
        # imponerle al call site que los convierta a mano.
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Configura el root logger una sola vez, al arrancar la app.

    Nivel INFO por defecto (no el WARNING por defecto de `logging`): sin
    esto los `logger.info(...)` estructurados del agent engine nunca se
    emiten. Se limpian los handlers existentes antes de agregar el propio
    para que llamar esta funcion mas de una vez (p.ej. varios modulos que
    importan `app.main` en el mismo proceso) no duplique lineas de log.
    """
    root = logging.getLogger()
    root.setLevel(level)

    handler = logging.StreamHandler()
    handler.setFormatter(StructuredJsonFormatter())

    root.handlers.clear()
    root.addHandler(handler)
