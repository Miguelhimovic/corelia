---
name: project-fase3-property-handoff-models
description: Fase 3 Tarea 1 — modelos Property y HumanHandoff, decisiones de tipos no cerrados por SPEC.md, y enum lead_purpose reutilizado otra vez
metadata:
  type: project
---

`app/models/property.py` y `app/models/human_handoff.py` (migracion
`a527a85a6c88_property_y_human_handoff.py`) implementan SPEC.md seccion 5
para Fase 3 (tools). Decisiones no obvias:

- `Property.purpose` reutiliza el enum `LeadPurpose`/`lead_purpose`
  (residential|investment) en vez de crear uno propio — mismo dominio que el
  contrato de extraccion del LLM (seccion 3) y `search_database(purpose:
  str)` (seccion 4). Esto disparo otra vez el gotcha de
  [[gotcha-pg-enum-reuse-in-migrations]]: el autogenerate de Alembic emitio
  `sa.Enum(..., name='lead_purpose')` para la nueva tabla `properties`, hubo
  que editarlo a mano a `postgresql.ENUM(..., create_type=False)` para no
  duplicar el tipo. Cualquier campo nuevo que comparta dominio con un enum ya
  creado (`lead_stage`, `lead_purpose`) va a repetir este patron.
- `PropertyStatus` (`available|reserved|sold|rented|inactive`) y
  `HandoffStatus` (`open|resolved`) son enums nuevos, agregados a
  `app/models/enums.py` — SPEC.md no cerraba su dominio de valores
  explicitamente antes de esta tarea; se documento la decision en el
  docstring de cada modelo en vez de solo en el commit.
- `property_type` y `availability` se dejaron como `String` libre (no enum):
  SPEC.md seccion 5 los lista pero sin dominio cerrado, a diferencia de
  `purpose`/`status` que si tienen contrato conocido en otra parte del
  documento. No inventar un enum ahi sin que SPEC.md lo pida.
- `HumanHandoff` NO usa `TimestampMixin` (solo `created_at`, sin
  `updated_at`) — sigue el mismo patron que `Message`: es un registro de
  evento, no una entidad editable in-place. `assigned_to` es `str | None`
  simple (no FK) porque en MVP no existe tabla de usuarios humanos.
- Mientras esta tarea corria, `spec-guardian` actualizo SPEC.md en paralelo
  (secciones 4, 5, 13) para cerrar huecos de Fase 3 antes de que las tools
  se implementen: algoritmo exacto de `search_database` (filtros duros,
  `status == 'available'`, orden por precio ascendente), aclaracion de que
  `Lead.stage`/`Lead.score` NO son campos aceptados por `update_lead()`, y
  que `is_demo` (no naming convention) es el mecanismo de marcado de demo
  data. Ver [[gotcha-pg-enum-reuse-in-migrations]] y
  [[project-env-docker-db-port]].

**Gotcha nuevo de esta sesion:** al arrancar, `corelia-db-1` otra vez tenia
`alembic_version` stampeado en head sin tablas reales (mismo patron de
[[project-env-docker-db-port]]) — se repitio el fix (`alembic stamp base` +
`alembic upgrade head`). Verificar SIEMPRE con `\dt` antes de generar una
migracion nueva, no confiar en el revision reportado.

**Cuidado con `ruff format .` a nivel de repo:** en esta sesion reformateo
de forma no solicitada 2 archivos de Fase 2 (`orchestrator.py`,
`state_machine.py` — solo colapso lineas que ya cabian en 100 cols, sin
cambio semantico) y un `.md` de memoria. Se revirtieron con `git checkout --`
antes de reportar la tarea terminada, para no ensuciar el diff de una tarea
que no los tocaba. Si `ruff format .` sin scope produce cambios en archivos
que no son parte de la tarea actual, revisar el diff y revertir lo
no-relacionado antes de dar por cerrado.
