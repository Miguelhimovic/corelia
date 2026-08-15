---
name: gotcha-qa-rechazo-dod-fase2
description: Los 5 gotchas que qa-reviewer encontro en el cierre de Fase 2 (Agent Engine) por incumplir Definition of Done, y como se resolvieron
metadata:
  type: feedback
---

Cierre de la revision de Fase 2 (Agent Engine) de `qa-reviewer`: veredicto
"RECHAZADO parcial" con logica de negocio aprobada pero 5 huecos de
Definition of Done (SPEC.md seccion 10). Relevante para no repetir estos
gotchas en fases futuras (RAG, Calendar, WhatsApp).

1. **Logging estructurado sin configurar = logs que nunca se emiten.**
   Tener `logger.info(..., extra={...})` en el codigo NO es suficiente para
   cumplir DoD item 5 -- si nadie llama `logging.basicConfig`/`dictConfig`
   en el entrypoint de la app, el root logger queda en WARNING por defecto
   y los `.info()` se descartan en silencio, y sin un formatter que
   referencie los campos de `extra=`, esos campos tampoco se ven aunque el
   log si se emita. **Fix:** `app/logging_config.py` (nuevo) con
   `StructuredJsonFormatter` (vuelca timestamp/level/logger/message + TODOS
   los campos de `extra=` sin filtrar) y `configure_logging(level=INFO)`,
   llamado una sola vez desde `app/main.py` al importar el modulo (antes de
   `get_settings()`). Verificar esto SIEMPRE con una prueba empirica (correr
   la app o un smoke test que capture stdout), no asumir que "hay logger.info
   en el codigo" == "el log se ve en produccion".

2. **`request_id` explicito en SPEC.md seccion 10 no se puede omitir.**
   No existe request_id real de HTTP en Fase 2 (no hay router/middleware
   todavia) -- se resolvio generando `uuid4()` una vez por turno dentro de
   `process_incoming_message()` (orchestrator.py) y pasandolo explicitamente
   a `extract_with_llm(..., request_id=request_id)` para que tambien
   aparezca en los logs de `llm_extraction.py`. Cuando llegue un
   router/middleware real de FastAPI (Fase 6, WhatsApp/webchat), ese
   request_id de HTTP deberia reemplazar/complementar este generado a mano.

3. **Decisiones de diseno que contradicen "la lectura obvia de SPEC.md"
   deben escribirse DE VUELTA en SPEC.md, no solo en la memoria del agente.**
   La decision de tratar `cancel` sin cita agendada como HANDOFF (no como
   `not_interested`/LOST, que es la lectura mas literal de SPEC.md seccion 1)
   se documento en memoria de agente pero nunca se reflejo en SPEC.md ni se
   corrigio el docstring de `map_intent_to_event()` en `state_machine.py`,
   que seguia diciendo lo contrario de lo que el codigo realmente hace. QA
   lo detecto como contradiccion de documentacion. **Regla:** cualquier
   desviacion deliberada de la lectura obvia de un contrato necesita (a) el
   docstring del codigo actualizado, y (b) un bullet nuevo en SPEC.md
   (seccion correspondiente) con la justificacion -- la memoria de agente no
   sustituye la actualizacion del contrato versionado.

4. **Comentarios "hallazgo pendiente" en tests quedan obsoletos apenas se
   arregla el hallazgo -- hay que barrerlos en el mismo turno del fix, no
   despues.** Dos casos en este cierre: (a) un comentario decia que
   `NURTURE -> DISCOVERING` era "extra, no documentado en SPEC.md" cuando SI
   esta documentado (SPEC.md seccion 1, bullet "Salida de NURTURE") -- solo
   no esta en la tabla de transiciones formal de la seccion 2; (b) un
   comentario en `TestPersistenceFailure` describia un workaround
   (`db_session.autoflush = False`) que el fix del bug de
   `orchestrator.py` (bloque unico try/except cubriendo lecturas + flush)
   ya habia vuelto innecesario, pero nadie quito la linea ni actualizo el
   comentario. Ver [[project-agent-engine-orchestrator]] para el detalle del
   fix que volvio obsoleto ese workaround.

5. **`ruff check .` sin excluir `migrations/` acumula errores autogenerados
   por Alembic entre revision y revision (18->24 en este caso) y QA lo
   escala a bloqueante si se repite.** Fix de una linea en
   `[tool.ruff]` de `pyproject.toml`: `exclude = ["migrations/"]`. Aplicar
   esto DESDE el Dia 1 de cualquier proyecto nuevo con Alembic, no esperar a
   que QA lo marque dos veces.

**Why:** estos 5 puntos son precisamente lo que golpea la seccion 10 de
SPEC.md (Definition of Done) cuando la logica de negocio ya esta bien --
QA revisa DoD como checklist literal, no solo "funciona".

**How to apply:** antes de reportar cualquier tarea de `agent_engine`/`rag`/
`tools` como terminada, verificar explicitamente cada item de SPEC.md
seccion 10 (no solo correr pytest): logging configurado y probado
empiricamente (no solo `logger.info` en el codigo), campos de contrato
(`request_id` etc.) presentes, cualquier desviacion de la lectura obvia de
un contrato reflejada en SPEC.md, comentarios de tests actualizados junto
con el fix que los volvio obsoletos, y `pyproject.toml` excluyendo
`migrations/` desde el principio.
