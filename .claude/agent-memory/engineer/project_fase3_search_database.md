---
name: project-fase3-search-database
description: Fase 3 Tarea 4 — search_database() en app/tools/, filtros duros via SQLAlchemy, PropertySearchError nueva, smoke test manual no formal
metadata:
  type: project
---

Implementado en `app/tools/search_database.py` +
`SearchDatabaseInput` (`app/tools/schemas.py`) + `PropertySearchError`
(`app/tools/errors.py`). Contrato: SPEC.md seccion 4 (algoritmo exacto de
filtros duros, ya cerrado antes de esta tarea — ver
[[project-fase3-property-handoff-models]]).

**Decisiones no obvias:**
- Filtros implementados como un solo `select()` de SQLAlchemy con `.where()`
  encadenado (tenant_id fijo, status==AVAILABLE, `or_(city.ilike, neighborhood.ilike)`,
  price<=budget_max, bedrooms>=solicitado, purpose==solicitado exacto),
  `.order_by(price.asc()).limit(5)` — todo a nivel de DB, no se trajo el
  catalogo completo a Python para filtrar ahi. `ilike` es especifico de
  Postgres (case-insensitive nativo), consistente con el resto del stack
  (Postgres/pgvector, sin capa de abstraccion de DB).
- Igual que `create_lead`, filtra por `DEFAULT_TENANT_ID` fijo (CLAUDE.md
  principio #3) — NO filtra ademas por `is_demo`: en MVP de tenant unico todo
  el catalogo sembrado por `scripts/seed_properties.py` ya es
  `is_demo=True`, y SPEC.md seccion 4 no menciona `is_demo` en el algoritmo
  de filtros (son 5 filtros duros exactos, cerrados, no se agrega uno mas
  sin que el contrato lo pida).
- `SearchDatabaseInput` (Pydantic, `extra=forbid`) NO tiene campos opcionales
  (a diferencia de `UpdateLeadFields`): los 4 parametros del contrato son
  obligatorios por precondicion ("los 4 parametros no-null"). `purpose` usa
  el tipo `LeadPurpose` para que la comparacion sea de enum, no de string.
- Resultado vacio (`[]`) vs. fallo de DB son dos caminos distintos a
  proposito: `[]` no lanza excepcion (SPEC.md: "el flujo lo maneja como
  results_empty"), mientras que un `SQLAlchemyError` real de Postgres si
  lanza `PropertySearchError` (nueva, sigue el patron de
  `LeadPersistenceError` — ver [[project-fase3-tools-create-update-lead]]).
  Esta distincion no estaba en el enunciado literal de SPEC.md seccion 4
  (que solo dice "Error/vacío: retorna lista vacía (no excepción)") pero es
  consistente con la politica fail-safe de la seccion 7 (PostgreSQL cae ->
  503 logico) aplicada ya en `create_lead`/`update_lead`.
- Retorna `list[Property]` (los objetos ORM), tal cual el literal del
  contrato de SPEC.md seccion 4 — sin envolver en un dataclass propio (a
  diferencia de `CreateLeadResult`), porque aqui el contrato no necesita
  ampliarse: no hay informacion adicional que generar en esta llamada mas
  alla de las propiedades mismas.

**Smoke test manual** (no formal, no quedo commiteado — vive en el
scratchpad de la sesion) corrido contra la DB real con las 141 propiedades
sembradas: caso positivo (Barranquilla/residential, 5 resultados, orden por
precio ascendente confirmado), caso presupuesto absurdamente bajo (0
resultados sin excepcion), caso propiedad `reserved` excluida correctamente,
caso `bedrooms>=solicitado` (propiedad con 4 habitaciones aparece al pedir
3), y validacion `budget_max<=0`/`bedrooms<=0` levantando `ValidationError`.
Los tests formales quedan para `test-writer` en un turno separado.

Se aplico otra vez [[gotcha-pytest-drops-dev-db-tables]]: pytest corrio
primero (201 passed, sin tests nuevos de esta tool todavia), despues
`alembic stamp base` + `upgrade head` + `scripts/seed_properties.py` para
dejar la DB verificable manualmente al cerrar la tarea.
