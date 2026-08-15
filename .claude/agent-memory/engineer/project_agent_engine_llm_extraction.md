---
name: project-agent-engine-llm-extraction
description: Donde vive la extraccion LLM (Tarea 3), como maneja tool-use/reintentos/enums, y la excepcion que Tarea 5 debe capturar para handoff
metadata:
  type: project
---

Fase 2, Tarea 3 (extraccion de slots via Claude, SPEC.md seccion 3) implementada en
`app/agent_engine/llm_extraction.py`. Re-exportada desde `app/agent_engine/__init__.py`
junto con `classify_deterministic` ([[project-agent-engine-classifier]]).

**Diseno clave:**
- `async def extract_with_llm(message: str, client: AsyncAnthropic | None = None) -> ExtractionResult`
  — nunca instancia un `AsyncAnthropic` global a nivel de modulo, siempre inyectable para tests.
- Usa tool-use forzado (`tool_choice={"type": "tool", "name": "extract_lead_intent"}`) en vez
  de parsear texto libre — mas robusto para el contrato de la seccion 3. Modelo hardcodeado:
  `claude-3-5-haiku-20241022` (constante `_MODEL`, sin abstraction layer, CLAUDE.md principio #4).
- Dos capas de reintento independientes, no mezcladas:
  1. Fallos transitorios de la API (seccion 7) → resueltos por el propio SDK de Anthropic
     (`AsyncAnthropic(max_retries=1)` en el cliente por defecto), no reimplementado a mano.
     Si el SDK agota su reintento, se escala de inmediato (no tiene sentido reintentar con
     prompt distinto si la API no responde).
  2. Salida invalida / sin tool_use / que no pasa `ExtractionResult.model_validate` (seccion 3)
     → un reintento adicional con prompt mas estricto (`_STRICT_SUFFIX`). Si falla de nuevo, se escala.
- Violaciones de enum (`intent`/`entities.purpose` fuera del enum cerrado) NO son excepcion:
  se degradan a `other`/`null` vía `_sanitize_enum_violations()` y se loguean como warning —
  esto pasa ANTES de la validacion Pydantic, para cumplir literalmente la regla de la seccion 3
  ("tratar como other/null y registrar violacion", no simplemente dejar que Pydantic falle).
- `confidence < 0.5` fuerza `requires_clarification=True` en el resultado final, sin importar
  lo que haya devuelto el LLM.
- Mecanismo de escalamiento: excepcion `LLMExtractionFailed` (definida en el mismo modulo).
  El orquestador (Tarea 5, aun no implementado) debe capturarla y disparar `handoff_human()`
  — se eligio excepcion explicita en vez de un valor sentinel para que sea imposible ignorar
  el caso de fallo por accidente.

**Why:** SPEC.md seccion 3 exige dos reglas de reintento distintas (API vs. schema) y una regla
de enums que NO es "lanzar excepcion" sino "degradar y loguear" — mezclar las tres en un solo
try/except habria sido mas fragil y menos trazable en logs.

**How to apply:** Tarea 5 (orquestador) debe: intentar `classify_deterministic()` primero: si
`None`, llamar `await extract_with_llm(message)`, capturar `LLMExtractionFailed` y tratarlo como
trigger de handoff (igual que "Claude API falla" o "2 búsquedas vacías" en SPEC.md seccion 7).
Tests de este modulo (mock de `AsyncAnthropic`, casos de enum invalido, retry con prompt estricto,
confidence<0.5, API error) son responsabilidad de un turno separado de test-writer — no se
escribieron en esta tarea. `ANTHROPIC_API_KEY` esta vacia en `.env` local a la fecha de esta
tarea (2026-08-14) — no se pudo probar contra la API real, solo se verifico import + sanitizacion
de enums + `pytest tests/ -q` (4 tests preexistentes, ninguno cubre este modulo todavia).
