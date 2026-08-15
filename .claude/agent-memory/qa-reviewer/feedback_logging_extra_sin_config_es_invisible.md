---
name: feedback-logging-extra-sin-config-es-invisible
description: logger.info/error(..., extra={...}) no produce logs estructurados si no hay logging.config en la app — verificar SIEMPRE con una llamada real, no solo leyendo el código
metadata:
  type: feedback
---

Al revisar DoD ítem 5 (SPEC.md sección 10: "logs estructurados... request_id, conversation_id,
lead_id, tool, tool_result, LLM latency, LLM tokens, error, timestamp"), no basta con verificar
que el código llama a `logger.info(..., extra={...})` con los campos correctos — hay que
verificar que existe una configuración de logging (`logging.basicConfig`, `logging.config.dictConfig`,
un `Formatter` custom que referencie esos campos, o `structlog`) en algún punto de arranque de
la app (`app/main.py`, `app/config.py`, etc.).

**Por qué importa:** sin esa configuración, Python's `logging` adjunta los campos de `extra` al
`LogRecord` pero el formatter por defecto (`%(message)s` vía `logging.lastResort`, y solo para
WARNING+) los descarta silenciosamente. Confirmado empíricamente en la revisión de Fase 2 (Agent
Engine, 2026-08-14): `app/agent_engine/orchestrator.py` y `llm_extraction.py` construyen `extra=`
dicts correctos (conversation_id, lead_id, latency_ms, tokens, error) pero `app/main.py` no tiene
ninguna configuración de logging — una llamada real a `logger.error(..., extra={...})` solo
imprime el mensaje pelado, sin ningún campo estructurado, y los `logger.info(...)` ni siquiera
se emiten (nivel por defecto del root logger es WARNING). Además faltaba `request_id` como campo
en absolutamente ningún log call del módulo — no solo un problema de config sino de campo ausente.

**Cómo aplicar:** al revisar cualquier funcionalidad con DoD ítem 5, correr una prueba rápida
(`python -c "import logging; logging.getLogger('app.x').error('msg', extra={...})"`) para
confirmar que los campos aparecen en la salida real, no solo leer el código fuente. Si no hay
`logging.config`/formatter en el proyecto, es motivo de RECHAZO de ese ítem específico aunque el
resto de la funcionalidad esté bien — el fix típico es una función de setup en `app/main.py` o
`app/logging_config.py` que se importe al arrancar (JSON formatter simple, sin OpenTelemetry/Grafana
per SPEC.md, que sí exige campos reales en el output).

**RESUELTO 2026-08-14 (re-revisión Fase 2):** `app/logging_config.py` (`StructuredJsonFormatter` +
`configure_logging()`) agregado, invocado desde `app/main.py` al importar. Re-verificado
empíricamente con `import app.main` + llamada real a `logger.info(...)`/`logger.error(...)` con
`extra=` — el JSON de salida trae `timestamp, level, logger, message` + todos los campos de
`extra` (incluido `request_id`, ahora generado por turno en `orchestrator.py` y propagado a
`llm_extraction.py`). El método de verificación empírica de esta memoria siguió siendo necesario
y confirmó que esta vez sí funciona (no dar por buena una futura corrección de logging solo
leyendo el código).
