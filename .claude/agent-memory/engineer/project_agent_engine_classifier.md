---
name: project-agent-engine-classifier
description: Where the deterministic classifier (SPEC.md sec 1) and shared ExtractionResult schema live, and the shape they must keep for the LLM extraction task to reuse
metadata:
  type: project
---

Fase 2, Tarea 2 (classifier determinista) implementada en:
- `app/agent_engine/schemas.py` — `ExtractedEntities` y `ExtractionResult` (Pydantic). Este es el shape compartido que reutilizará la Tarea 3 (extracción LLM) — no duplicar el schema, importar desde aquí.
- `app/agent_engine/classifier.py` — `normalize_text()` (minúsculas + sin tildes vía `unicodedata`, sin librería nueva) y `classify_deterministic(message) -> ExtractionResult | None`. Devuelve `None` cuando ninguna regla matchea, señal para que el orquestador caiga al LLM.
- `app/agent_engine/__init__.py` ya no está vacío — re-exporta `classify_deterministic`, `normalize_text`, `ExtractedEntities`, `ExtractionResult`.

**Why:** SPEC.md sec 1 dice que las reglas deterministas SOLO cubren `human_request`, `cancel`, `not_interested` por keyword/regex; todo lo demás (incluida cualquier extracción de slots location/budget_max/bedrooms/purpose) va siempre al LLM. `LeadIntent` y `LeadPurpose` ya existían en `app/models/enums.py` desde el Día 1 — el schema los reutiliza en vez de redefinir strings.

**How to apply:** Al implementar la Tarea 3 (extracción vía LLM), el resultado debe ser un `ExtractionResult` del mismo `app/agent_engine/schemas.py`. El orquestador del state machine debe: intentar `classify_deterministic()` primero, y si devuelve `None`, llamar al LLM. Tests de este módulo (classifier + golden conversations) son responsabilidad de un turno separado de test-writer, no se escribieron en esta tarea.
