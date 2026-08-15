# BITÁCORA — CorelIA

Documento vivo de negocio: contexto, decisiones, sprints y objetivos. Se actualiza al cierre de cada sprint. Para el contexto técnico que usa Claude Code al programar, ver `CLAUDE.md` (que importa este archivo).

---

## 1. Qué es CorelIA

**Posicionamiento:** CorelIA construye sistemas de IA que automatizan operaciones reales de negocio. No vende chatbots — vende sistemas de adquisición y operación comercial automatizada.

**Frase comercial:** "De un lead a una venta. De un documento a una decisión. De una conversación a una operación."

**Lo que el cliente debe pensar:** no "CorelIA hace chatbots", sino "CorelIA puede tomar este proceso que hoy hacemos manualmente y convertirlo en un sistema."

**Diferenciador central:** no reemplazamos los sistemas del cliente (CRM, ERP, WhatsApp, Calendar, Excel) — los conectamos y los hacemos inteligentes.

---

## 2. Objetivo de negocio actual

**$20M COP cobrados en máximo 60 días**, idealmente $10-12M dentro de los primeros 30 días. Objetivo secundario: que al día 60 exista una máquina comercial que siga generando oportunidades sin depender solo de contacto manual.

Métrica que manda: **cash collected**, no pipeline contratado, no followers, no impresiones.

Escenarios para llegar a $20M (cualquiera es válido, se persigue el que llegue primero):
- 1 Legal ($8M) + 1 BPO ($8M) + 1 Inmobiliaria ($4M) = $20M
- 2 Legal ($7M c/u) + 2 Inmobiliarias ($3M c/u) = $20M
- 1 BPO ($12M) + 2 Inmobiliarias ($4M c/u) = $20M

Recomendación financiera: perseguir **$25-30M contratados con 50-70% de anticipo**, no exactamente $20M — así el cash disponible real es mayor y hay margen de maniobra.

---

## 3. Verticales y priorización

| Prioridad | Vertical | Producto | Ticket objetivo | Canal inicial | Razón |
|---|---|---|---|---|---|
| 🥇 | Legal | RAG + automatización documental | $6-15M | Google + outbound | CPC alto, poca especialización competitiva local, ticket alto |
| 🥈 | Inmobiliario | AI Lead Agent | $2-5M + mensualidad | Google + outbound | Dolor evidente, WhatsApp, decisión rápida, demo espectacular |
| 🥉 | Clínicas | Recepcionista IA | $5-10M | Google + outbound | Deprioritizado por ahora, no está en el sprint activo |
| 4 | BPO | Contact Center Intelligence | $8-20M+ | Account-based (ABM) | Ticket más alto pero competidores más fuertes y sofisticados (Vozy, Wolkvox, Konecta) — no se ataca con campaña masiva |
| 5 | Logística | Operations Intelligence | $6-15M | Outbound | Fuera del foco de los primeros sprints |
| 6 | E-commerce | Sales Automation | $2-5M | Ads + inbound | Saturado de agencias, tickets menores — producto de entrada, no prioridad de adquisición |

**Foco activo ahora mismo: Legal + Real Estate.** BPO se trabaja solo vía ABM (cuentas específicas), nunca como campaña. Logística, e-commerce y clínicas quedan fuera del alcance hasta nueva decisión.

---

## 4. Portafolio de productos y pricing

### Legal AI Workspace (RAG documental)
| Tier | Precio | Incluye |
|---|---|---|
| Starter | $5M COP | Hasta 500 documentos, RAG básico, 1 admin + 3 usuarios |
| Professional | $8M COP | Hasta 3.000 documentos, trazabilidad, hasta 15 usuarios, integración Drive/SharePoint |
| Enterprise | $12-15M+ COP | Despliegue privado, SSO, auditoría, workflows |
| Mensualidad | $500k-$1,5M COP/mes | Mantenimiento, actualización del índice, soporte |

Característica de venta central: **"No responde sin mostrarte de dónde salió"** — respuestas con fuente citada (documento, página, cláusula). Ataca directamente el riesgo de alucinaciones jurídicas (relevante tras la sentencia STC17832-2025 de la Corte Suprema sobre citas falsas generadas por IA).

### CorelIA Sales Agent / Real Estate AI
| Modalidad | Precio |
|---|---|
| Setup básico | $3,5M COP + $700k/mes |
| Setup con integración a portales (FincaRaíz/Metrocuadrado) + CRM | $5M COP + $1M/mes |

Nota abierta: verificar con cada portal si existe API pública para automatización vía WhatsApp antes de comprometerlo en propuesta — varios no la exponen.

### BPO — Contact Center Intelligence / AI Quality Intelligence
$8-12M implementación + $1-3M/mes. Posicionamiento: "somos el integrador de IA de tu operación", no "reemplazamos tu plataforma de contact center". Venta consultiva, no campaña.

---

## 5. Investigación de mercado — resumen ejecutivo

Investigación competitiva profunda en Colombia/LATAM (6 verticales) confirmó:
- El mercado está saturado de agencias genéricas de chatbot/voz (BPO, e-commerce, inmobiliaria tienen competencia fuerte y/o commoditizada).
- **Legal e Inmobiliario tienen menor competencia especializada** con señales de intención de compra alta (CPC legal $4.800-$8.200 COP, uno de los más altos del mercado).
- BPO tiene el ticket más alto pero competidores muy sofisticados (Vozy, Wolkvox, Beex, Konecta) con casos de éxito cuantificados fuertes — no conviene competir de frente ahí.
- WhatsApp es el campo de batalla en 4 de 6 verticales.
- Ley 1581 de 2012 (Habeas Data) y, en cobranza, Ley 2300 de 2023, son barrera y argumento de venta a la vez — los competidores serios lo convierten en diferenciador.

Reporte completo entregado como documento separado (investigación competitiva por vertical: competidores, precios, keywords, ads, landing pages, pain points, diferenciadores).

---

## 6. Decisiones de arquitectura técnica tomadas

- **Híbrido determinístico + LLM:** classifier simple + state machine para intención simple; LLM (Claude) solo para interpretar lenguaje natural y extraer datos a JSON estructurado. No "LLM decide todo" en producción.
- **RAG con citación de fuente obligatoria** — no negociable, es el diferenciador de Legal.
- **Single-tenant hardcodeado para el MVP** — multi-tenancy real se construye después de 2-3 clientes reales pagando, no antes.
- **Un solo proveedor de LLM (Claude) para el MVP** — abstraction layer de múltiples proveedores se agrega cuando el volumen lo justifique, no antes.
- **Stack recortado para validar, no para escalar:** FastAPI + PostgreSQL + pgvector + Cloud Run + Claude API. Redis, Pub/Sub, CI/CD formal, observabilidad avanzada: después del primer cliente.

Detalle completo del alcance técnico y comandos: ver `CLAUDE.md`.

---

## 7. Roadmap de fases

**Fase 0-1 (ahora):** MVP de validación — demo Real Estate (WhatsApp/web) + demo Legal (RAG) + demo BPO opcional. Sprint de 7 días en ejecución (ver sección 10).

**Fase 2/3 (NO ahora — criterio de activación: 2-3 clientes reales pagando):** CorelIA Revenue OS — sistema de operación interna con agentes especializados (Research, Intelligence, Qualification, Outreach, Response, Reception, Discovery, Strategy), orquestador, event store, motor de políticas, dashboard de control ("Control Center"). Documentado como visión de largo plazo, explícitamente pospuesto para no repetir el error de construir la plataforma completa antes de vender.

Primer componente a construir cuando llegue el momento: **Response/Follow-up Agent** (clasificar respuestas + secuencia de seguimiento automático) — mayor ROI con menor riesgo de decisión.

Principio no negociable para cuando se construya outreach automatizado: sin scraping indiscriminado ni envío masivo, registro de consentimiento/opt-out por contacto, supresión global inmediata ante solicitud de no contacto, revisión legal previa. WhatsApp Business API tiene además sus propias políticas contra mensajería masiva no solicitada, independientes de la Ley 1581.

---

## 8. Documentos de apoyo ya generados

- `Playbook_Discovery_AI_Operations.md` — guion de discovery call por vertical (BPO, Comercial, Servicios Profesionales/Legal, Logística, Inmobiliaria, Clínicas), scoring 0-100, anclaje de propuesta a tiers.
- `Plan_Operativo_14_Dias.md` — oferta, estructura de sitio, copy de landing pages `/legal-ai` y `/real-estate-ai`, estructura de Google Ads, CRM/pipeline, guiones de outbound, calendario día por día.
- `Sprint_7_Dias_CorelIA.md` — blueprint resuelto + calendario técnico/comercial del sprint activo, prompts listos para Claude Code, adenda de Fase 2/3.

---

## 9. Decisiones pendientes / riesgos abiertos

- **Naming y dominio:** no decidido formalmente. Se puede lanzar bajo "CorelIA" directamente (marca ya definida como madre) mientras se valida mercado.
- **Verificación de APIs de portales inmobiliarios** (FincaRaíz/Metrocuadrado) antes de comprometer integración en propuestas.
- **Contrato/SOW:** checklist mínimo definido (alcance, IP, confidencialidad, condiciones de pago, qué incluye la mensualidad) — falta revisión de abogado antes de firmar el primer contrato real.
- **Capacidad real:** confirmada en 8+ horas/día para la semana del sprint activo. Revisar si se sostiene semana a semana; si baja, recortar alcance del sprint siguiente antes de comprometerlo.
- **Riesgo técnico del sprint activo:** integración de WhatsApp Business API (Día 6) es el punto más frágil — si se atrasa, el demo puede correr sobre chat web sin perder poder de venta.

---

## 10. Log de sprints

### Sprint 1 — inicio 2026-08-14
**Objetivo:** primer discovery calificado en pipeline + demo Real Estate y Legal funcionando end-to-end.
**Alcance:** Agent Core (single-tenant), state machine inmobiliario, RAG legal con citación, Calendar, WhatsApp (o web chat como fallback), landing `/legal-ai` y `/real-estate-ai`, 100+ outbound Real Estate, inicio outbound Legal.
**Fuera de alcance (explícito):** multi-tenancy, abstraction de LLM providers, CorelIA Revenue OS (agentes, orquestador, event store, dashboard de control).
**Resultado:** _a completar al cierre del Día 7._

**Día 1 (2026-08-14) — Core:**
- Hecho: scaffold multi-agente aplicado a la raíz (`.claude/agents`, skill `spec-task`, hook de tests, CI); repo FastAPI + PostgreSQL + Alembic inicializado; modelos base (`Tenant`, `Agent`, `Lead`, `Conversation`, `Message`) con migración inicial aplicada y tenant fijo sembrado; `/health` y `/health/db` funcionando; tests y `ruff` en verde.
- Bloqueo abierto: Docker Desktop no arranca en esta máquina (`Docker Desktop is unable to start`) — se usó temporalmente el PostgreSQL nativo del sistema (puerto 5432, sin `pgvector`) para no frenar el sprint. Hay que resolver Docker Desktop (o instalar `pgvector` a mano) antes de Fase 4 (RAG), que sí necesita la extensión.

**Día 2 (2026-08-15) — Cierre de infraestructura Fase 1 + QA:**
- Hecho: Docker Desktop volvió a funcionar; se migró de vuelta del Postgres nativo (workaround del Día 1) a `docker-compose.yml`. Se descubrió que esta máquina tiene DOS instancias nativas de PostgreSQL (`postgresql-x64-17` y `postgresql-x64-18`) que entre ambas ocupan los puertos 5432 y 5433 sin dar error de "puerto en uso" — causaba fallos intermitentes de autenticación al conectar a `:5433`. Se remapeó el puerto de host del contenedor a **5544** (`docker-compose.yml`, `.env`, `.env.example`). La extensión `pgvector` (habilitada a mano el día anterior, sin versionar) se agregó a la migración inicial vía `op.execute("CREATE EXTENSION IF NOT EXISTS vector")`, con `DROP EXTENSION` deliberadamente omitido en `downgrade()` por ser una extensión compartida a nivel de DB.
- QA (`qa-reviewer`) corrió sobre todo lo implementado Día 1-2: modelos base, migración, endpoints `/health`, tests y seguridad (`.env` fuera de Git) — **APROBADO** en cada pieza. El cambio de puerto salió inicialmente **RECHAZADO** porque el nuevo puerto 5544 no se había propagado a `CLAUDE.md` (seguía documentando 5433) ni al default de `Settings.database_url` en `app/config.py` (seguía hardcodeado en 5433) — violación de DoD sección 10 ítem 8. Corregido en el mismo día: `CLAUDE.md` y `app/config.py` actualizados a 5544, nota "Día 1" sobre el bloqueo de Docker Desktop marcada como resuelta. Tests re-verificados 4/4 en verde tras la corrección.
- Descubierto, no en SPEC.md: `ruff check .` falla con 18 errores preexistentes dentro de `migrations/` (import order, líneas largas del autogenerado de Alembic) — no bloquea CI (`.github/workflows/test.yml` solo corre `pytest`) y no es requisito explícito del DoD, pero queda como deuda técnica (agregar `exclude = ["migrations/"]` en `pyproject.toml`).
- Sin cambios de contrato en `SPEC.md` — lo corregido fue documentación de infraestructura (CLAUDE.md, config.py), no un contrato técnico de la sección 1-14.
- Pendiente para el resto del sprint: Fase 2 (Agent engine — classifier + state machine + extracción LLM) todavía no arrancó.

**Día 3 (2026-08-16) — Fase 2: Agent Engine (Real Estate), flujo spec-task completo:**
- Hecho: `spec-guardian` verificó el contrato antes de implementar y encontró 7 huecos en SPEC.md (secciones 1-3, 9) — todos resueltos y documentados directamente en SPEC.md antes de escribir código: reglas del classifier determinístico, `confidence` como float global (no por slot), ubicación/reset de `empty_search_count` y `no_response_count` en `ConversationState`, timeout de "no respuesta" generalizado a PRESENTING/SCHEDULING (no solo DISCOVERING), transición `NURTURE → DISCOVERING`, definición de "rama" para golden conversations (cada transición nombrada de la sección 2), y patrón de invocación del LLM (por mensaje, sin caché, prompt en código).
- Construido en `/app/agent_engine` (5 tareas de `engineer`, una por turno): modelo `ConversationState` + migración; `classifier.py` (reglas determinísticas para `human_request`/`cancel`/`not_interested`); `llm_extraction.py` (extracción a JSON vía tool-calling forzado de Claude, `claude-3-5-haiku-20241022`, con reintento único y `LLMExtractionFailed` como señal de escalamiento); `state_machine.py` (las 17 transiciones de SPEC.md sección 2, función pura, `InvalidTransitionError` para transiciones no definidas); `orchestrator.py` (conecta todo, fusiona slots entre turnos, señaliza acciones vía `TurnResult`/`OrchestratorAction` sin ejecutar tools de Fase 3, que todavía no existen).
- `test-writer` (turno separado) escribió 201 tests: 35 classifier, 63 state machine (las 17 transiciones individuales), 16 extracción LLM (mockeada, sin llamar a la API real), 30 orquestador (DB real de test), 53 golden conversations. Encontró un bug real sin arreglarlo (correspondía a engineer): el manejo de `SQLAlchemyError` del orquestador solo cubría el `flush()` final, no las lecturas anteriores — corregido en un turno de engineer aparte.
- `qa-reviewer` dio veredicto **RECHAZADO parcial** en la primera pasada: lógica de negocio sólida, pero 5 huecos de Definition of Done — logs estructurados que en la práctica no emitían nada (sin configuración de logging en la app, sin `request_id`), contradicción entre el docstring de `map_intent_to_event()` y el comportamiento real del orquestador para "cancel sin cita agendada", dos comentarios de test obsoletos, y `ruff` sin excluir `migrations/` (segunda revisión seguida con el mismo pendiente). Los 5 se cerraron en un turno de `engineer` — incluye nuevo `app/logging_config.py` (JSON formatter) y `request_id` por turno propagado a `orchestrator.py`/`llm_extraction.py`, y un bullet nuevo en SPEC.md sección 1 documentando la decisión de "cancel sin cita" → HANDOFF (no LOST).
- `qa-reviewer` re-revisó y dio veredicto **APROBADO en su totalidad**, verificando cada punto empíricamente (no solo leyendo código): confirmó output real de logs JSON con los campos esperados, y `ruff check .`/`pytest tests/ -q` limpios (201 passed) desde cero.
- Riesgo abierto conocido, no bloqueante en este punto del sprint: `ANTHROPIC_API_KEY` sigue vacía en `.env` local — la extracción LLM nunca se probó contra Claude real, solo con dobles de test. Hay que resolverlo antes de Fase 7 (demo), no antes.
- Pendiente para el resto del sprint: Fase 3 (tools — create_lead, update_lead, search_database, handoff_human, get_availability, book_meeting, cancel_meeting) todavía no arranca. El orquestador ya deja claro vía `TurnResult`/`OrchestratorAction` qué tool correspondería llamar en cada caso, lista para conectar.

**Día 4 (2026-08-17) — Fase 3: Tools Real Estate (create_lead, update_lead, search_database, handoff_human), flujo spec-task completo:**
- `spec-guardian` encontró 3 huecos bloqueantes en SPEC.md antes de implementar (mismo patrón que Día 3): convención de marcado de datos demo indefinida (sección 13 solo decía "un campo o convención de naming"), defaults/nullability de `HumanHandoff.status`/`assigned_to` sin especificar, y algoritmo de `search_database()` descrito como "ordenadas por relevancia" sin definir qué es "relevancia". Los 3 se cerraron en SPEC.md antes de escribir código: `Property.is_demo: bool` (default `True`) como mecanismo de marcado; `HumanHandoff.status` enum `open|resolved` default `open`, `assigned_to` siempre `NULL` en MVP; algoritmo exacto de `search_database()` documentado como filtros duros (status='available', location substring case-insensitive, price<=budget_max, bedrooms>=solicitado, purpose exacto) ordenados por precio ascendente, sin ranking por grado de match.
- Construido en 6 tareas de `engineer` (turnos separados): modelos `Property`/`HumanHandoff` + migración; seed de catálogo demo (`scripts/seed_properties.py`, 141 propiedades ficticias en 6 ciudades colombianas, is_demo=True); tools `create_lead`/`update_lead` (`app/tools/`, Pydantic, rechazan `stage`/`score` en `update_lead` en vez de ignorarlos en silencio); tool `search_database` (filtros duros en un solo `select()` de SQLAlchemy, nunca lanza excepción en caso vacío); tool `handoff_human` (única tool con permiso de escribir `Lead.stage` directamente, log WARNING como notificación MVP); conexión de las 4 tools al orquestador vía nueva función `handle_message()` en `app/agent_engine/orchestrator.py`, sin romper los 201 tests de Fase 2.
- `test-writer` (turno separado) agregó 76 tests: unit tests de las 4 tools, tests de `handle_message()`, golden conversations reales para las ramas nuevas que ejecutan tools (property_search con resultados/vacío, human_request→handoff con tool real, not_interested→LOST). Total: 277 tests.
- Durante la implementación, `engineer` encontró un bug real heredado de Fase 2 (ya aprobada): la rama de SPEC.md sección 2 "2 búsquedas vacías consecutivas → HANDOFF" era inalcanzable desde una conversación real, porque `_EMPTY_SEARCH_RESET_EVENTS` en `state_machine.py` reseteaba `empty_search_count` en cualquier evento `ENOUGH_DATA` (no solo cuando el usuario cambiaba de criterio, como exige SPEC.md sección 1). No lo arregló por su cuenta — lo documentó explícitamente para que QA lo evaluara, en vez de dejarlo pasar en silencio.
- `qa-reviewer` dio veredicto **RECHAZADO parcial** en la primera pasada: confirmó que el bug de `empty_search_count` sí bloqueaba la fase (afirmación falsa en el propio docstring de `handle_message()`, criterio de aceptación de sección 11 "hace handoff" incumplido en la práctica, sin golden conversation real que cubriera esa rama), más 3 inconsistencias de documentación (SPEC.md sección 5 no incluía `bedrooms`/`purpose` en los campos editables de `update_lead()` pese a que el modelo sí los tiene; SPEC.md sección 4 todavía decía "ordenadas por relevancia" pese al algoritmo exacto ya definido 4 líneas más abajo; CLAUDE.md no advertía que `pytest` corre `drop_all()` contra la misma DB de desarrollo local, borrando el catálogo demo en cada corrida). Señaló que es la tercera vez que el proyecto repite el patrón de "contrato resuelto pero no propagado de vuelta a SPEC.md/CLAUDE.md".
- Los 4 puntos se cerraron: fix real en `state_machine.py` (el reset de `empty_search_count` ya no depende de `ENOUGH_DATA`, solo de `RESULTS_FOUND`) + `orchestrator.py` (nueva comparación de criterios contra los slots previos del `Lead`, antes de que `update_lead()` los sobreescriba, para decidir si el contador se resetea o sigue acumulando); 3 correcciones de documentación en SPEC.md/CLAUDE.md. Se agregaron tests reales de 2 turnos (`handle_message()` invocado de verdad, no la función interna con contador manipulado a mano) para la rama antes inalcanzable, y un caso de control confirmando que el reset legítimo por cambio de criterio sigue funcionando. Total final: 279 tests.
- `qa-reviewer` re-revisó y dio veredicto **APROBADO**, verificando empíricamente cada punto (no solo lectura de código): corrió `pytest`/`ruff` desde cero, confirmó que los tests nuevos ejercitan el camino real de `handle_message()` con efectos verificados en DB (fila de `HumanHandoff`, `Lead.stage`), y revisó los casos borde del fix (primer intento de búsqueda sin criterio anterior, cambio parcial de solo 1 de los 4 criterios).
- Deuda técnica anotada, no bloqueante: `tests/conftest.py` corre contra la misma DB de desarrollo local y hace `drop_all()`/`create_all()` en cada corrida de pytest — ahora documentado en CLAUDE.md con el procedimiento de recuperación, pero sigue siendo un riesgo real de perder el catálogo demo la noche antes de una demo si no se recuerda re-sembrar.
- Pendiente para el resto del sprint: Fase 4 (RAG — upload de documentos, chunking, embeddings pgvector, retrieval + citación) todavía no arranca. Fase 5 (Calendar) tampoco — `get_availability`/`book_meeting`/`cancel_meeting` quedaron explícitamente fuera del alcance de esta fase.
- **Revisión de cierre de sesión** (`qa-reviewer`, veredicto explícito por funcionalidad, no solo global): las 11 piezas tocadas hoy — modelos `Property`/`HumanHandoff`, seed de catálogo, las 4 tools, conexión al orquestador, el fix de `empty_search_count`, la suite de tests nueva, y la consistencia final SPEC.md/CLAUDE.md — **APROBADAS individualmente**. Encontró 2 hallazgos nuevos en esta segunda mirada (no vistos en las dos pasadas anteriores del mismo día), ambos cerrados en el momento:
  - `ToolExecution` (SPEC.md sección 5) nunca se construyó y no tenía nota de diferimiento explícita (a diferencia de `Appointment`, cuyo diferimiento a Fase 5/Calendar es evidente por estar atado a los tools de esa sección). Cerrado agregando una nota explícita en SPEC.md sección 5: se difiere indefinidamente, los logs estructurados de DoD sección 10 ítem 5 ya cubren la trazabilidad necesaria en MVP, la tabla de auditoría persistida se construye si un cliente real la pide.
  - El comando documentado en el propio docstring de `scripts/seed_properties.py` (`python scripts/seed_properties.py`) falla con `ModuleNotFoundError: No module named 'app'` — corregido a `python -m scripts.seed_properties` en el docstring del script y en CLAUDE.md.
  - Confirmado explícitamente por QA: los 3 patrones recurrentes de "doc drift" señalados en revisiones anteriores del sprint (contrato resuelto pero no propagado a SPEC.md/CLAUDE.md) **no se repitieron** en esta pasada — las correcciones pedidas se verificaron cerradas línea por línea.
- Veredicto global de la sesión: **APROBADO**. 279 tests en verde, `ruff` limpio, `alembic heads` con un solo head consistente. DB local dejada limpia y sembrada (141 propiedades demo) al cierre.

### Sprint 2 — [pendiente]
_A completar cuando arranque._

---

## 11. Métricas que importan

Pipeline por etapa (Prospectos → Contactados → Discovery → Propuestas → Cierres), tasa de respuesta por canal y vertical, CPC/CPL real vs. estimado, discovery→propuesta→cierre, **cash collected** (la única que manda al final de cada sprint).
