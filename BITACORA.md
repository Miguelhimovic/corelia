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

### Sprint 2 — [pendiente]
_A completar cuando arranque._

---

## 11. Métricas que importan

Pipeline por etapa (Prospectos → Contactados → Discovery → Propuestas → Cierres), tasa de respuesta por canal y vertical, CPC/CPL real vs. estimado, discovery→propuesta→cierre, **cash collected** (la única que manda al final de cada sprint).
