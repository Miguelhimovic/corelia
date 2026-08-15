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
- **Classifier determinístico vs. LLM (CLAUDE.md principio 1):** reglas determinísticas (keyword/regex sobre el mensaje normalizado) se aplican SOLO para detectar `human_request`, `cancel` y `not_interested` a partir de frases literales cercanas a "hablar con una persona/asesor", "cancelar/reagendar cita", "ya no me interesa/no gracias". Cualquier mensaje que no matchee esas reglas —y en particular todo lo que requiera extraer `location/budget_max/bedrooms/purpose` de lenguaje natural— pasa siempre por el LLM (sección 3). El LLM se invoca en cada mensaje entrante que no matchea una regla determinística; sin caché de respuestas en MVP. El prompt de extracción vive en el código de `agent_engine` (no hay archivo externo de prompts pre-redactados para esta pieza).
- **Contador de búsquedas vacías:** vive en `ConversationState` (campo `empty_search_count: int`, default 0). Se incrementa en cada `results_empty` (sección 2). Se resetea a 0 en cuanto el usuario cambia cualquiera de los 4 criterios de búsqueda (nueva vuelta de `PROPERTY_SEARCH` = intento nuevo, no continuación del anterior).
- **Timeout de "no respuesta" (regla generalizada):** la regla de "2 recordatorios sin respuesta en el mismo estado → `stage=NURTURE`" (ver arriba) no aplica solo a `DISCOVERING` — aplica a cualquier estado activo que esté esperando una respuesta del usuario (incluye `PRESENTING` sin selección de propiedad, `SCHEDULING` sin confirmación de horario). Contador en `ConversationState.no_response_count`; se resetea a 0 en cada transición de estado (cada estado nuevo empieza su propio conteo de recordatorios).
- **Salida de `NURTURE`:** no hay reactivación automática en MVP (el Follow-up Agent que reactivaría proactivamente es Fase 2/3, fuera de alcance — ver BITACORA.md sección 7). Si el usuario envía cualquier mensaje nuevo estando en `NURTURE`, la transición es `NURTURE → DISCOVERING` y se retoma el flujo normal desde ahí.
- **"Cancelar" sin cita agendada:** la línea de arriba ("Quiere cancelar: si hay cita agendada, llamar `cancel_meeting`; si es 'ya no me interesa' en general, `stage=LOST`") cubre los dos casos donde la intención es inequívoca. Cuando el intent detectado es `cancel` pero NO hay cita agendada y el mensaje no es un opt-out explícito ("ya no me interesa"/"no gracias"), no se asume `stage=LOST`: cancelar algo que no existe todavía es una señal de confusión o de pregunta fuera de flujo, no necesariamente pérdida de interés — se trata igual que cualquier otra pregunta no cubierta por los slots (ver bullet "Pregunta fuera del flujo" arriba) y ofrece handoff (`HUMAN_REQUEST`), nunca `LOST` automático.

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
PROPERTY_SEARCH → DISCOVERING  : results_empty (una vuelta para ajustar criterio; 2 búsquedas vacías seguidas → HANDOFF; contador en ConversationState.empty_search_count, ver sección 1)
PRESENTING → SCHEDULING        : user_selects_property o wants_visit
PRESENTING → HANDOFF           : human_request
PRESENTING → NURTURE           : no_response tras 2 recordatorios sin selección (ver regla generalizada, sección 1)
SCHEDULING → BOOKED            : meeting_confirmed (éxito del tool de Calendar)
SCHEDULING → HANDOFF           : calendar_error o human_request
SCHEDULING → NURTURE           : no_response tras 2 recordatorios sin confirmación de horario
BOOKED → HANDOFF               : usuario pide cambios más allá de reagendar simple, o cancelación
NURTURE → DISCOVERING          : el usuario envía cualquier mensaje nuevo (sin reactivación automática en MVP, ver sección 1)
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
- `confidence` es un único float global por extracción (no hay confidence por slot individual). El criterio de "enough_data" de la sección 1 (`confidence ≥ 0.7` para location+budget_max+bedrooms+purpose) se evalúa contra ese mismo valor global, no contra un promedio ni un mínimo por campo.
- Falla de Claude API durante la extracción (sección 7): reintento único con backoff corto; si persiste, responder mensaje de problema técnico + `handoff_human` — mismo comportamiento que cualquier otra falla de Claude API.

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
# Éxito: retorna hasta 5 propiedades que cumplen todos los filtros duros, ordenadas por precio ascendente (ver algoritmo exacto abajo — no hay ranking por "grado de match")
# Error/vacío: retorna lista vacía (no excepción) — el flujo lo maneja como results_empty
# Regla dura: el LLM presenta SOLO lo que devuelve esta función. Nunca inventa propiedades.
#
# Algoritmo exacto (todos son filtros duros, deben cumplirse TODOS — sin ranking por "grado de match"):
#   - status == 'available' (excluir propiedades no disponibles)
#   - location: substring case-insensitive contra city O neighborhood de la propiedad
#   - price <= budget_max
#   - bedrooms >= bedrooms solicitado (una propiedad con más habitaciones de las pedidas es válida; con menos, no)
#   - purpose == purpose solicitado (comparación exacta del enum)
# Ordenamiento del resultado filtrado: precio ascendente. Retorna hasta 5.
# Si el filtrado da 0 resultados → lista vacía (no hay segundo intento de "relajar" criterios dentro de la misma
# llamada; esa relajación ya la maneja el state machine vía PROPERTY_SEARCH → DISCOVERING, sección 2).

handoff_human(lead_id: UUID, reason: str, summary: str) -> HandoffID
# Efecto secundario: crea HumanHandoff (status='open', assigned_to=NULL — ver sección 5), stage=HANDOFF,
# dispara notificación (ver sección 7). En MVP la notificación es un log estructurado (nivel WARNING,
# incluye handoff_id/lead_id/reason) — no hay integración real de email/Slack todavía; eso es Fase 2/3.

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
  │         ubicación, bedrooms, purpose, score, stage, último_contacto, próximo_contacto)
  │     ├── Conversation (canal: whatsapp|web, lead_id)
  │     │     ├── Message (conversation_id, role, content, timestamp)
  │     │     └── ConversationState (conversation_id, current_state, last_transition_at,
  │     │                            empty_search_count, no_response_count)
  │     ├── Appointment (lead_id, start_datetime, duration_minutes, status, calendar_event_id)
  │     ├── ToolExecution (lead_id, tool_name, input, output, status, timestamp)
  │     └── HumanHandoff (lead_id, reason, summary, assigned_to, status, created_at)
  ├── Property (id, title, property_type, city, neighborhood, price, bedrooms,
  │             bathrooms, area, purpose, status, description, features, images,
  │             availability, is_demo) — DEMO DATA en MVP
  └── KnowledgeDocument (id, filename, uploaded_at, status)
        └── KnowledgeChunk (document_id, chunk_id, page, section, content, embedding)
```

**Defaults y nullability aclarados (cerrados aquí porque bloqueaban Fase 3 — tools):**
- `HumanHandoff.status`: enum `open | resolved`, default `open` al crear vía `handoff_human()`. No hay transición automática a `resolved` en MVP (se actualiza manualmente, fuera del alcance de las tools de esta fase).
- `HumanHandoff.assigned_to`: nullable, siempre `NULL` en MVP — no existe asignación automática ni manual desde el sistema todavía (Fase 2/3).
- `ToolExecution`: **diferido explícitamente, no se construye en Fase 3.** A diferencia de `Appointment` (cuyo diferimiento a Fase 5/Calendar es evidente por estar atado a `get_availability`/`book_meeting`/`cancel_meeting`, sección 4), `ToolExecution` no tiene un contrato de tool propio — sería una tabla de auditoría genérica escrita por cada tool, no el resultado de una tool específica. En MVP, el requisito de DoD sección 10 ítem 5 (logs estructurados con `tool`/`tool_result`) ya lo cubre vía `logger.info/warning/error(extra=...)` en las 4 tools de Fase 3 — un log estructurado es suficiente trazabilidad para validar el MVP; la tabla persistida de auditoría se construye si un cliente real la pide (consistente con CLAUDE.md: "no construir todavía" lo que no está validado por demanda real).
- `Property.is_demo`: booleano, default `True`. Es la convención de marcado de datos demo (sección 13) — un campo explícito, no una convención de naming en `title`.
- `Lead.stage` y `Lead.score` **no son actualizables vía `update_lead()`** — `stage` cambia solo a través de las transiciones del state machine (sección 2); `score` se recalcula con la fórmula de la sección 1, no se acepta como campo arbitrario en `fields`. `update_lead()` acepta el resto de campos del schema de `Lead` (nombre, teléfono, email, fuente, intención, presupuesto, ubicación, bedrooms, purpose, último_contacto, próximo_contacto) — `bedrooms` y `purpose` son dos de los 4 slots que extrae el LLM (sección 3) y deben poder persistirse igual que `location`/`budget_max`.
- `create_lead()`: campos no provistos por los parámetros (`nombre`, `email`, `ubicación`, `presupuesto`, `intención`) quedan `NULL`; `último_contacto` se setea al timestamp de creación; `próximo_contacto` queda `NULL`. Validación de `channel` (enum `web|whatsapp`) y `phone` vía Pydantic; entrada inválida levanta error de validación (Pydantic `ValidationError`) sin crear el lead.

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

Empezar con al menos 3-5 golden conversations por rama del state machine antes de considerar el flujo "terminado". **Definición de "rama":** cada transición nombrada individualmente en la tabla de la sección 2 (cada línea `Estado → Estado : evento`) cuenta como una rama propia — no cada camino end-to-end completo. Ej. `DISCOVERING → HANDOFF : human_request` es una rama; `PROPERTY_SEARCH → DISCOVERING : results_empty` es otra.

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

**Real Estate:** 100-500 propiedades ficticias, marcadas con el campo booleano `Property.is_demo=True` (ver sección 5), para que nunca se confundan con inventario real de un cliente. `search_database()` (sección 4) filtra siempre por `status='available'`; el filtro por `is_demo` se aplica a nivel de tenant/seed, no como parámetro de la tool — en MVP con un solo tenant fijo, todo el catálogo sembrado es demo.
**Legal:** 20-50 documentos de demostración (contratos genéricos no confidenciales), igualmente marcados como demo.

---

## 14. Qué NO hará el agente (explícito)

**Real Estate — nunca:**
inventar precios · inventar disponibilidad · inventar propiedades · prometer descuentos · confirmar citas sin respuesta exitosa de Calendar · modificar el CRM sin pasar por un tool · entregar información privada de otros leads.

**Legal — nunca:**
inventar jurisprudencia · inventar artículos o cláusulas · dar respuestas sin fuente citada · afirmar certeza cuando no existe evidencia suficiente en los documentos indexados.
