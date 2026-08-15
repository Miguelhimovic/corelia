---
name: feedback-ambiguedades-resueltas-en-codigo-no-vuelven-a-spec
description: cuando engineer resuelve una ambigüedad de SPEC.md durante la implementación (no vía spec-guardian), esa decisión debe escribirse de vuelta en SPEC.md — si no, queda como doc drift interno (docstrings contradictorios entre módulos)
metadata:
  type: feedback
---

Patrón hermano de [[feedback-doc-drift-en-cambios-infra]], pero para contratos de negocio en
vez de infraestructura. En la revisión de Fase 2 (Agent Engine, 2026-08-14) spec-guardian sí
cerró 7 huecos reales de SPEC.md antes de implementar (ampliando secciones 1, 2, 3, 9). Pero
DURANTE la implementación (Tarea 5, orquestador) apareció una octava ambigüedad — qué hacer con
intent=`cancel` sin cita agendada — y el propio engineer documentó en su memoria que la resolvió
en contra de "la lectura más obvia de SPEC.md sección 1" (que sugería tratarlo como `not_interested`/LOST)
a favor de tratarlo como `question`/`other` sin FAQ (→ HANDOFF). Esa decisión NUNCA se escribió
de vuelta en `SPEC.md` — quedó solo en el código y en un comentario. Peor: el docstring de
`map_intent_to_event()` en `state_machine.py` (escrito en una tarea anterior) sigue afirmando el
comportamiento viejo ("se trata como not_interested"), contradiciendo directamente lo que
`orchestrator.py` implementa de verdad. Confirmado leyendo ambos archivos — no es un caso teórico.

**Por qué importa:** SPEC.md sección 10 ítem 8 exige "actualización de SPEC.md o CLAUDE.md si
cambia un contrato" — esto aplica no solo a cambios de infraestructura sino a cualquier
resolución de ambigüedad de negocio que se tome durante la implementación y que un lector futuro
de SPEC.md no podría deducir. Un docstring contradictorio entre dos módulos del mismo agent
engine es una señal clara de que la resolución no se propagó correctamente.

**Cómo aplicar:** al revisar cualquier fase que toque el agent engine, comparar los docstrings
de decisión de diseño entre módulos relacionados (ej. `state_machine.py` vs `orchestrator.py`)
buscando contradicciones explícitas, no solo verificar que cada uno documente su propia lógica
en aislamiento. Si una decisión de diseño contradice la lectura literal de SPEC.md y no está
reflejada ahí, es motivo de RECHAZO parcial (documentación) aunque el comportamiento implementado
sea razonable y fail-safe.

**RESUELTO 2026-08-14 (re-revisión Fase 2):** el docstring de `map_intent_to_event()` en
`state_machine.py` ya no afirma el comportamiento viejo — ahora describe explícitamente que
`cancel` sin cita agendada va a `HUMAN_REQUEST`/HANDOFF (no `not_interested`/LOST), consistente
con `_resolve_turn()` en `orchestrator.py`. SPEC.md sección 1 ganó el bullet `"Cancelar" sin cita
agendada` que documenta la decisión de negocio. Los tres puntos (docstring, código, SPEC.md)
quedaron alineados — confirmado leyendo los tres a la vez, no solo uno.

**Segunda instancia detectada (patron confirmado recurrente): revision Fase 3 (tools), 2026-08-14.**
spec-guardian/engineer cerraron explicitamente en SPEC.md seccion 5 (linea 164) la lista de campos
que `update_lead()` acepta ("nombre, telefono, email, fuente, intencion, presupuesto, ubicacion,
ultimo_contacto, proximo_contacto") -- pero la lista quedo incompleta: omite `bedrooms`/`purpose`,
que SI son parte del schema de `Lead` (agregados en Fase 2) y que `UpdateLeadFields`
(`app/tools/schemas.py`) SI acepta explicitamente. El propio docstring de `UpdateLeadFields`
reconoce la omision en la prosa de la tarea, pero esa correccion nunca volvio al texto de SPEC.md
seccion 5 -- el mismo hueco que "se cerro" quedo abierto de nuevo, en el mismo archivo, en el mismo
ciclo. Ademas SPEC.md seccion 4 (linea 109, "retorna hasta 5 propiedades ordenadas por relevancia...")
quedo contradiciendo el bloque "Algoritmo exacto" agregado 4 lineas despues en el mismo commit
(linea 113: "sin ranking por grado de match") -- texto viejo no limpiado al cerrar la ambiguedad.

**Como aplicar reforzado:** cuando SPEC.md enumera una lista cerrada de campos/valores para cerrar
una ambiguedad (no solo docstrings de codigo), verificar esa lista contra el modelo SQLAlchemy real
y el BaseModel/schema Pydantic real campo por campo, no solo leerla como prosa razonable. Tambien
revisar que el texto viejo alrededor del parrafo "recien cerrado" no quede contradictorio con la
aclaracion nueva agregada en el mismo edit.

**RESUELTO 2026-08-14 (segunda pasada QA, mismo dia, Fase 3):** ambos huecos de la segunda instancia
se cerraron correctamente en el ciclo de correccion. SPEC.md seccion 5 linea ~145 (arbol del modelo
de datos) y linea ~164 (lista de campos de `update_lead()`) ya incluyen `bedrooms`/`purpose` en las
dos ubicaciones -- verificado leyendo el texto exacto, no solo el diff. `app/tools/schemas.py`
(`UpdateLeadFields`) coincide campo por campo con esa lista y ademas documenta en su propio
docstring por que el enunciado original de la tarea las omitia (`extra="forbid"` + explicacion).
SPEC.md seccion 4 linea 109 tambien se corrigio ("retorna hasta 5 propiedades que cumplen todos los
filtros duros, ordenadas por precio ascendente... no hay ranking por 'grado de match'"), consistente
con el bloque "Algoritmo exacto" 4 lineas mas abajo -- ya no hay contradiccion entre ambos parrafos.
Confirma que el patron, aunque recurrente, SI se corrige de forma completa cuando se senala
explicitamente linea por linea en el rechazo -- seguir exigiendo esa precision en futuras
revisiones en vez de aceptar "ya lo cerramos en SPEC.md" en general.
