# SPEC.md — Contratos técnicos de CorelIA MVP v0.1

Este archivo cierra los 10 contratos necesarios antes de que Claude Code implemente sin tomar decisiones de arquitectura por su cuenta. Referenciado desde `CLAUDE.md` vía `@SPEC.md`.

---

## 1. Real Estate — Functional Spec

**Flujo principal:**
```
NEW → DISCOVERING (identificar intención + recolectar location/budget/bedrooms/purpose)
    → QUALIFYING (validar que los 4 campos requeridos estén completos)
    → PROPERTY_SEARCH (llamar search_database)
    → PRESENTING (mostrar máximo 5 opciones)
    → SCHEDULING (intentar book_meeting)
    → BOOKED
    → HANDOFF (si corresponde)
```

**Comportamiento en casos borde:**
- **Usuario no responde:** después de 2 recordatorios sin respuesta en el mismo estado, marcar `stage=NURTURE` y detener el prompting activo. El seguimiento automático (Follow-up Agent) es Fase 2/3, no MVP — en MVP solo se registra y se detiene.
- **Pregunta fuera del flujo** (ej. "¿tienen financiación?"): el MVP no tiene base de FAQ para Real Estate. Cualquier pregunta no cubierta por los slots ofrece handoff, nunca se ignora en silencio.
- **Sin propiedades que cumplan criterios:** presentar honestamente el resultado vacío, ofrecer ampliar un criterio (presupuesto o habitaciones) con una pregunta de seguimiento. Nunca inventar propiedades.
- **Pide un humano:** transición inmediata a HANDOFF sin importar el estado actual — es la transición de mayor prioridad, se evalúa antes que cualquier otra lógica.
- **Quiere cancelar:** si hay cita agendada, llamar `cancel_meeting`; si es "ya no me interesa" en general, `stage=LOST` con motivo registrado.
- **Cuándo se crea el Lead:** en el primer mensaje entrante, incluso antes de conocer ningún slot — así nada se pierde. `score` inicia en 0.
- **Cuándo se considera "calificado":** location + budget_max + bedrooms + purpose presentes con `confidence ≥ 0.7` Y al menos una propiedad coincidente existe.
- **Campos obligatorios antes de PROPERTY_SEARCH:** location, budget_max, bedrooms, purpose.
- **Significado de `score` (0-100):** 40% completitud de datos + 30% confianza de intención + 30% responsividad/engagement. Fórmula simplificada para MVP, se refina con datos reales post-lanzamiento.
- **Cambios de `stage`:** siguen exactamente las transiciones de la sección 2.

---

## 2. State Machine formal

**Estados:** `NEW, DISCOVERING, QUALIFYING, PROPERTY_SEARCH, PRESENTING, SCHEDULING, BOOKED, HANDOFF, NURTURE, LOST`

**Transiciones:**
```
NEW → DISCOVERING              : primer mensaje entrante procesado
DISCOVERING → QUALIFYING       : enough_data (los 4 slots requeridos con confidence≥0.7)
DISCOVERING → HANDOFF          : human_request (en cualquier punto, máxima prioridad)
DISCOVERING → NURTURE          : no_response tras 2 recordatorios
QUALIFYING → PROPERTY_SEARCH   : automático al entrar al estado (disparado por el sistema, no por el usuario)
PROPERTY_SEARCH → PRESENTING   : results_found (>0 propiedades)
PROPERTY_SEARCH → DISCOVERING  : results_empty (una vuelta para ajustar criterio; 2 búsquedas vacías seguidas → HANDOFF)
PRESENTING → SCHEDULING        : user_selects_property o wants_visit
PRESENTING → HANDOFF           : human_request
SCHEDULING → BOOKED            : meeting_confirmed (éxito del tool de Calendar)
SCHEDULING → HANDOFF           : calendar_error o human_request
BOOKED → HANDOFF               : usuario pide cambios más allá de reagendar simple, o cancelación
* → LOST                       : opt-out explícito ("no me interesa")
* → HANDOFF                    : human_request explícito (se evalúa antes que cualquier otra transición)
```

---

## 3. Contrato de salida del LLM (extracción)

```json
{
  "intent": "property_search | question | human_request | cancel | not_interested | other",
  "entities": {
    "location": "string | null",
    "budget_max": "number | null",
    "bedrooms": "integer | null",
    "purpose": "residential | investment | null"
  },
  "confidence": "float 0-1",
  "requires_clarification": "boolean"
}
```

**Reglas:**
- Enums cerrados para `intent`/`purpose` — el LLM no puede inventar valores nuevos; si lo hace, se trata como `other`/null y se registra una violación de schema.
- Campos ausentes se devuelven como `null` explícito, nunca se omite la clave.
- `confidence < 0.5` → forzar `requires_clarification=true` y hacer una pregunta aclaratoria en vez de avanzar el state machine.
- JSON malformado o campos extra → validar con Pydantic; si falla, reintentar una vez con instrucción más estricta; si falla la segunda vez, escalar a HANDOFF.

---

## 4. Tool Contracts

```python
create_lead(source: str, channel: str, phone: str | None, initial_message: str) -> LeadID
# Precondición: ninguna (se llama en el primer mensaje)
# Éxito: retorna lead_id, stage=NEW, score=0
# Error: teléfono/canal inválido → error de validación, no crea el lead

update_lead(lead_id: UUID, fields: dict) -> Lead
# Precondición: lead_id existe
# Validación: solo campos del schema de Lead; entities del LLM pasan por el contrato de la sección 3 antes de llegar aquí
# Éxito: retorna Lead actualizado
# Error: lead_id no existe → 404 lógico, se loguea y se responde con handoff

search_database(location: str, budget_max: float, bedrooms: int, purpose: str) -> list[Property]
# Precondición: los 4 parámetros no-null
# Validación: budget_max > 0, bedrooms > 0
# Éxito: retorna hasta 5 propiedades ordenadas por relevancia (match de criterios, luego precio ascendente)
# Error/vacío: retorna lista vacía (no excepción) — el flujo lo maneja como results_empty
# Regla dura: el LLM presenta SOLO lo que devuelve esta función. Nunca inventa propiedades.

handoff_human(lead_id: UUID, reason: str, summary: str) -> HandoffID
# Efecto secundario: crea HumanHandoff, stage=HANDOFF, dispara notificación (ver sección 7)

get_availability(date_range: tuple[date, date]) -> list[TimeSlot]
book_meeting(lead_id: UUID, start_datetime: datetime, duration_minutes: int, notes: str | None) -> AppointmentID
# Error de Calendar → no se confirma al usuario hasta recibir éxito explícito del tool (nunca "asumir" que la cita quedó agendada)

cancel_meeting(meeting_id: UUID) -> bool
```

Para el vertical Legal, `search_database` se reemplaza por el contrato de RAG (sección 6) — no reutiliza la misma función que Real Estate.

---

## 5. Modelo de datos completo

```
Tenant (id fijo en MVP)
  ├── Agent (nombre, system_prompt, tools_enabled)
  ├── Lead (nombre, teléfono, email, fuente, canal, intención, presupuesto,
  │         ubicación, score, stage, último_contacto, próximo_contacto)
  │     ├── Conversation (canal: whatsapp|web, lead_id)
  │     │     ├── Message (conversation_id, role, content, timestamp)
  │     │     └── ConversationState (conversation_id, current_state, last_transition_at)
  │     ├── Appointment (lead_id, start_datetime, duration_minutes, status, calendar_event_id)
  │     ├── ToolExecution (lead_id, tool_name, input, output, status, timestamp)
  │     └── HumanHandoff (lead_id, reason, summary, assigned_to, status, created_at)
  ├── Property (id, title, property_type, city, neighborhood, price, bedrooms,
  │             bathrooms, area, purpose, status, description, features, images,
  │             availability) — DEMO DATA en MVP
  └── KnowledgeDocument (id, filename, uploaded_at, status)
        └── KnowledgeChunk (document_id, chunk_id, page, section, content, embedding)
```

---

## 6. RAG Contract (Legal)

**Ingestión:** PDF, DOCX, TXT.
**Metadata por chunk:** `document_id, filename, page, section, chunk_id, uploaded_at`.
**Retrieval:** `top_k=5`, `similarity_threshold=0.75`, sin reranking en MVP, `max_context_tokens=4000`.
**Formato de respuesta:**
```
[Respuesta generada]

Fuentes:
[1] Nombre_documento.pdf — página 12
[2] Nombre_documento.pdf — sección 4.2
```
**Regla no negociable:** si no hay evidencia suficiente (ningún chunk supera el `similarity_threshold`), el agente responde explícitamente que no puede determinarlo con la información disponible. Nunca completa con conocimiento general del LLM.

---

## 7. Error & Handoff Policy

| Falla | Comportamiento |
|---|---|
| Claude API falla | Reintento único con backoff corto; si persiste, responder "estoy teniendo problemas técnicos, un asesor te contacta" + `handoff_human` |
| PostgreSQL cae | 503 lógico, no se pierde el mensaje entrante (queda en cola/log), no se inventa respuesta |
| Calendar no responde | No confirmar cita al usuario; ofrecer reintentar o handoff |
| WhatsApp devuelve error | Reintento único; si falla, log + alerta, sin reintentos infinitos |
| RAG no encuentra información | Responder que no hay evidencia suficiente (sección 6) |
| Usuario pide información inexistente | Igual que arriba — nunca inventar |

**Principio general: FAIL SAFE.** Ante cualquier duda, el sistema prefiere decir "no sé" o escalar a humano antes que inventar.

**Flujo de Human Handoff:**
```
Trigger (human_request, error irrecuperable, 2 búsquedas vacías, etc.)
  → handoff_human() crea HumanHandoff
  → Lead.stage = HANDOFF
  → Notificación (canal a definir en implementación: email/Slack)
  → Mensaje al usuario confirmando que un asesor continúa
```
**Información entregada al humano:** resumen de la conversación, necesidad detectada, presupuesto, historial de mensajes, propiedades vistas (Real Estate) o documentos consultados (Legal), preguntas pendientes, última interacción.

---

## 8. Security Baseline (production-safe, no enterprise)

- Secrets solo en variables de entorno; `.env` fuera de Git (`.gitignore` desde el commit inicial).
- Ninguna API key en código ni en logs.
- Logs sin información sensible (sin contenido completo de documentos legales ni datos personales completos — usar IDs).
- Validación de inputs en todos los endpoints (Pydantic).
- Queries parametrizadas (SQLAlchemy ORM cubre esto por defecto — no usar SQL crudo con interpolación de strings).
- Límite de tamaño de archivo en upload de documentos (ej. 20MB) + validación de MIME type real (no solo extensión).
- Verificación de firma en el webhook de WhatsApp (validar que la request viene de Meta).
- Rate limiting básico en endpoints públicos (webhook, chat web).

---

## 9. Testing / Golden Conversations

**Unit tests:** classifier, state machine (todas las transiciones de la sección 2), scoring, cada tool, retrieval de RAG.
**Integration tests:** PostgreSQL, Calendar API, Claude API, WhatsApp webhook.
**Golden conversations:** 30-50 conversaciones de ejemplo con estado esperado, corridas en cada cambio de prompt para evitar que una "mejora" rompa comportamiento ya validado. Formato:

```yaml
- input: "Busco apartamento en Pinares, máximo 450 millones, 3 habitaciones, para vivir"
  expected:
    intent: property_search
    entities: {location: "Pinares", budget_max: 450000000, bedrooms: 3, purpose: residential}
    state_after: QUALIFYING

- input: "Quiero hablar con una persona"
  expected:
    intent: human_request
    state_after: HANDOFF

- input: "¿Manejan financiación con el banco?"
  expected:
    intent: question
    state_after: HANDOFF   # fuera de alcance del flujo, no hay FAQ en MVP
```

Empezar con al menos 3-5 golden conversations por rama del state machine antes de considerar el flujo "terminado".

---

## 10. Definition of Done

Una funcionalidad no está terminada hasta que tiene:
1. Implementación
2. Type hints completos
3. Tests (unit + al menos 1 golden conversation si toca el agent engine)
4. Manejo de errores según la sección 7
5. Logs estructurados (`request_id, conversation_id, lead_id, tool, tool_result, LLM latency, LLM tokens, error, timestamp` — sin OpenTelemetry/Grafana en MVP, logs estructurados simples)
6. Documentación (docstring en tools, comentario de decisión si algo no es obvio)
7. Migración de Alembic si cambia el modelo de datos
8. Actualización de este archivo o de `CLAUDE.md` si cambia un contrato
9. Criterios de aceptación de la sección 11 cumplidos para esa funcionalidad

---

## 11. Criterios de aceptación del MVP

**Real Estate está terminado cuando:**
recibe conversación · identifica intención · mantiene estado · extrae datos · consulta catálogo · no inventa propiedades · crea lead · actualiza lead · consulta Calendar · agenda · cancela · hace handoff · conserva historial · funciona en Web · funciona en WhatsApp o fallback documentado.

**Legal está terminado cuando:**
carga documento · procesa · indexa · recupera · responde · cita página/sección · rechaza preguntas sin evidencia suficiente.

---

## 12. Decisiones de infraestructura, canales y CRM

**Infraestructura:**
```
Local:      Docker Compose → FastAPI + PostgreSQL/pgvector
Producción: Cloud Run + Cloud SQL + Cloud Storage (documentos) + Secret Manager
```

**Canales:** Web chat es obligatorio en el MVP (permite hacer demos sin depender de aprobación/configuración de WhatsApp Business). Mismo backend para ambos canales — Web y WhatsApp son solo adaptadores de entrada/salida al mismo agent engine.

**CRM:** no se construye un CRM completo en el MVP. Se usa el modelo `Lead` + pipeline básico (sección 5). Sincronización con HubSpot queda para después del primer cliente — evita scope creep ahora.

---

## 13. Demo data

**Real Estate:** 100-500 propiedades ficticias, claramente marcadas como `DEMO DATA` en un campo o convención de naming, para que nunca se confundan con inventario real de un cliente.
**Legal:** 20-50 documentos de demostración (contratos genéricos no confidenciales), igualmente marcados como demo.

---

## 14. Qué NO hará el agente (explícito)

**Real Estate — nunca:**
inventar precios · inventar disponibilidad · inventar propiedades · prometer descuentos · confirmar citas sin respuesta exitosa de Calendar · modificar el CRM sin pasar por un tool · entregar información privada de otros leads.

**Legal — nunca:**
inventar jurisprudencia · inventar artículos o cláusulas · dar respuestas sin fuente citada · afirmar certeza cuando no existe evidencia suficiente en los documentos indexados.
