# CLAUDE.md — CorelIA

@BITACORA.md
@SPEC.md
@MARCA.md

Contexto de negocio completo (objetivo, pricing, verticales, decisiones) está en `BITACORA.md`. Los 10 contratos técnicos detallados (functional spec, state machine, JSON schemas, tool contracts, modelo de datos, RAG, error/handoff policy, security baseline, testing, Definition of Done) están en `SPEC.md`. Colores, tipografía, jerarquía visual, modo oscuro, restricciones de logo y tono de voz están en `MARCA.md` — obligatorio al construir `/web` o cualquier material de cara al cliente. Este archivo es el resumen operativo: principios, qué NO construir todavía, estructura, comandos, y las reglas de "siempre aplica" que no dependen de en qué parte del sistema se esté trabajando.

**Antes de implementar cualquier funcionalidad del agent engine, RAG, tools o state machine: consultar el contrato correspondiente en `SPEC.md`. No improvisar comportamiento que ya está especificado ahí.**

## Resumen del proyecto

MVP de validación de CorelIA Sales Agent (vertical Real Estate) y CorelIA Legal (RAG documental). Un solo backend, un solo tenant hardcodeado, un solo proveedor de LLM. El objetivo del código en esta fase es sostener demos vendibles y el primer cliente real, no escalar.

## Principios de arquitectura (no negociables en esta fase)

1. **Determinístico + LLM híbrido:** intención simple → state machine con reglas. Lenguaje natural que requiere interpretación → LLM (Claude) extrae a JSON estructurado, y el state machine decide con eso. El LLM nunca controla el flujo completo de una conversación de venta.
2. **RAG siempre cita fuente exacta** (documento, página/sección). Una respuesta de RAG sin cita es un bug, no un detalle menor.
3. **Un tenant fijo, hardcodeado.** No implementar lógica de multi-tenancy (aislamiento de datos por cliente, autenticación por organización, etc.) todavía.
4. **Un solo proveedor de LLM (Claude), sin capa de abstracción.** No crear interfaces genéricas para soportar múltiples proveedores todavía.
5. **Sin orquestador de agentes ni event store.** Cada función del sistema (agente inmobiliario, RAG legal) es un servicio simple y directo, no un agente autónomo dentro de un framework de orquestación.

## Qué NO construir todavía (Fase 2/3 — ver BITACORA.md sección 7)

Explícitamente fuera de alcance hasta que haya 2-3 clientes reales pagando:
- Multi-tenancy real
- Abstraction layer de múltiples LLM providers
- CorelIA Revenue OS: Research/Intelligence/Qualification/Outreach/Response/Reception/Discovery/Strategy Agents, orquestador, event store, motor de políticas, dashboard "Control Center"
- Cualquier forma de outreach automatizado a escala (scraping, envío masivo) — cuando se construya, requiere revisión legal previa y mecanismo de opt-out/supresión global desde el diseño, no como añadido posterior

Si una tarea pide construir algo de esta lista, señalarlo explícitamente antes de empezar en vez de proceder.

## Estructura de carpetas

```
/app
  /agent_engine      # classifier, state machine, extracción de slots vía LLM
  /rag                # ingesta de documentos, chunking, embeddings, retrieval, citación
  /tools              # create_lead, update_lead, search_database, handoff_human, get_availability, book_meeting, cancel_meeting
  /calendar           # integración Google Calendar
  /whatsapp           # webhook entrante/saliente
  /webchat            # endpoint del canal Web Chat (mismo agent engine que WhatsApp)
  /models             # SQLAlchemy models
  /api                # routers FastAPI
  main.py
/web                   # sitio público: homepage, /legal-ai, /real-estate-ai + widget de Web Chat
/migrations            # Alembic
/tests
```

**Monorepo, no repos separados.** La web vive en `/web` dentro del mismo repositorio que el backend, específicamente para que el widget de Web Chat consuma `/app/webchat` sin fricción de integración entre proyectos. El copy de las landing pages (`/legal-ai`, `/real-estate-ai`) ya está escrito en `Plan_Operativo_14_Dias.md` — Claude Code lo usa tal cual, no lo reinventa.

## Comandos

Verificados el Día 1 (Windows + PowerShell/Git Bash). Todos se corren desde la raíz del repo con el venv activado.

- Entorno: `python -m venv .venv` luego `.venv\Scripts\activate` (PowerShell) o `source .venv/Scripts/activate` (Git Bash)
- Instalar dependencias: `pip install -r requirements-dev.txt` (incluye `requirements.txt` + pytest/httpx/ruff)
- Config local: copiar `.env.example` a `.env` y completar `DATABASE_URL` / `ANTHROPIC_API_KEY`
- Postgres local (pgvector): `docker compose up -d` → expone el puerto **5433** (el 5432 puede estar ocupado por una instancia nativa)
- Dev server: `uvicorn app.main:app --reload`
- Migraciones: `alembic upgrade head` (nueva migración: `alembic revision --autogenerate -m "mensaje"`)
- Tests: `pytest tests/ -q` (requiere Postgres arriba — usan la misma `DATABASE_URL` del `.env`)
- Lint/format: `ruff check .` + `ruff format .`
- Healthchecks: `GET /health` (liveness) y `GET /health/db` (valida conexión a Postgres)

**Nota Día 1:** en esta máquina Docker Desktop no arrancó (`Docker Desktop is unable to start`). Se usó temporalmente el PostgreSQL nativo del sistema en el puerto 5432 (ver comentario en `.env`) para no bloquear el sprint. Ese Postgres nativo **no tiene la extensión `pgvector` instalada** — sirve para Fases 1-3, pero antes de Fase 4 (RAG) hay que resolver Docker Desktop y volver a `docker-compose.yml` (puerto 5433), o instalar la extensión `vector` manualmente en el Postgres nativo.

## Modelo de datos (Fase 1)

- **Tenant** — id fijo por ahora (no dinámico)
- **Conversation** — vinculada a tenant, canal (whatsapp/web), lead
- **Message** — conversation_id, role, content, timestamp
- **Lead** — nombre, teléfono, email, fuente, intención, presupuesto, ubicación, score, etapa, último_contacto, próximo_contacto
- **Agent** — nombre, system_prompt, tools_enabled

## Tools que debe exponer el agente

```
create_lead()
update_lead()
search_database()      # catálogo de propiedades (Real Estate) o índice de documentos (Legal, vía RAG)
handoff_human()
get_availability(date_range)      # Calendar
book_meeting(datetime, lead_id, notes)
cancel_meeting(meeting_id)
```

## Fases y alcance día por día (Sprint activo)

Ver `Sprint_7_Dias_CorelIA.md` para el detalle día por día completo y los prompts ya redactados por bloque (skeleton, agent engine, RAG, calendar, WhatsApp). Resumen de fases técnicas:

| Fase | Contenido |
|---|---|
| 1 — Core | FastAPI + PostgreSQL + modelos base (tenant fijo, conversations, messages, leads, agents) |
| 2 — Agent engine | Classifier + state machine flujo inmobiliario + extracción LLM a JSON |
| 3 — Tools | create_lead, update_lead, search_database (catálogo de ejemplo), handoff_human |
| 4 — RAG | Upload de documentos, chunking, embeddings (pgvector), retrieval + citación |
| 5 — Calendar | Google Calendar API: disponibilidad, agendar, cancelar |
| 6 — WhatsApp | Webhook entrante/saliente conectado al agent engine |
| 7 — Demo | Ensamblar end-to-end (Real Estate + Legal), pulir para demo comercial |

## Flujo de trabajo multi-agente (Spec-Driven Development)

CorelIA usa un flujo de 5 roles separados para que ningún agente apruebe su propio trabajo: `spec-guardian` (verifica contrato en SPEC.md) → `engineer` (implementa) → `test-writer` (escribe tests, siempre en turno separado del que implementó) → `qa-reviewer` (aprueba o rechaza contra SPEC.md secciones 10-11) → `deployer` (solo si QA aprobó). Definiciones completas en `.claude/agents/`. El flujo se orquesta con la skill `.claude/skills/spec-task/SKILL.md` — úsala en vez de pedir implementación directa: "Usa el flujo spec-task para implementar X (SPEC.md sección N)".

Un hook en `.claude/settings.json` corre pytest automáticamente después de editar `agent_engine`, `rag` o `tools`, y devuelve los fallos a Claude antes de que pueda reportar algo como terminado — esto es enforcement determinístico, no una instrucción que dependa de que el modelo la recuerde. Detalle completo en `README_SCAFFOLD.md`.

## Convenciones de código

- Type hints obligatorios, modelos de datos con Pydantic.
- Cada función de `tools/` debe tener docstring claro (se usan como definiciones de tool-calling para el LLM).
- Mantener el state machine y el LLM como capas separadas — no mezclar lógica de negocio dentro de prompts.
- Sin dependencias nuevas fuera del stack definido (FastAPI, SQLAlchemy, Alembic, pgvector, Claude SDK) sin justificarlo explícitamente antes de agregarlas.

## Reglas de "siempre aplica" (resumen — detalle completo en SPEC.md secciones 8 y 10)

**Seguridad:** secrets solo en variables de entorno, `.env` fuera de Git, sin API keys en código/logs, inputs validados con Pydantic, verificación de firma en el webhook de WhatsApp, rate limiting básico en endpoints públicos.

**Definition of Done:** ninguna funcionalidad se considera terminada sin implementación + type hints + tests (incluyendo golden conversations si toca el agent engine) + manejo de errores según la política de fail-safe + logs estructurados + migración de Alembic si aplica + criterios de aceptación cumplidos.

**Regla dura, sin excepción:** el LLM nunca inventa datos que deberían venir de un tool (propiedades, disponibilidad de Calendar, contenido de documentos). Si un tool no devuelve evidencia suficiente, la respuesta es "no puedo determinarlo" o escalar a humano — nunca completar con conocimiento general del modelo.
