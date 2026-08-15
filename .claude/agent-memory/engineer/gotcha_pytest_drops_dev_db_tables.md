---
name: gotcha-pytest-drops-dev-db-tables
description: pytest tests/ -q ejecuta Base.metadata.drop_all() contra la misma DATABASE_URL del .env local al terminar la sesion de tests, borrando cualquier dato sembrado (seed de properties, tenant, etc.)
metadata:
  type: project
---

`tests/conftest.py` tiene un fixture `engine` de scope `session` que hace
`Base.metadata.create_all(test_engine)` al inicio y `Base.metadata.drop_all(test_engine)`
al terminar — y `test_engine` se crea con `get_settings().database_url`, la
MISMA base de datos de desarrollo local (Docker, puerto 5544), no una DB de
test separada (asi lo documenta CLAUDE.md seccion Comandos: "Tests: requiere
Postgres arriba — usan la misma DATABASE_URL del .env").

**Consecuencia practica:** correr `pytest tests/ -q` localmente borra TODAS
las tablas de la app (incluido el tenant fijo sembrado por la migracion
inicial y cualquier seed de demo data como `scripts/seed_properties.py`) en
cuanto termina la sesion de tests. `alembic_version` no forma parte de
`Base.metadata`, asi que queda stampeado en head con las tablas reales
ausentes — mismo sintoma que [[project-env-docker-db-port]] pero con causa
raiz distinta (no es un problema de arranque de Docker, es el propio test
suite).

**Como recuperarse:** `alembic stamp base` + `alembic upgrade head` para
reconstruir el schema (la migracion inicial reinserta el tenant fijo via
`op.execute("INSERT INTO tenants ...")`), y volver a correr cualquier script
de seed (`scripts/seed_properties.py`) despues.

**Orden recomendado de aqui en adelante:** si en la misma sesion hay que
correr tests Y dejar datos sembrados para verificacion manual/demo, correr
pytest PRIMERO y sembrar/verificar DESPUES — nunca al reves, porque el
sembrado se pierde en cuanto pytest corre. Esto no es un bug a arreglar sin
que lo pida el usuario (cambiar a una DB de test separada seria una decision
de infraestructura fuera del scope de una tarea de seed) — documentarlo es
suficiente por ahora. Ver tambien [[project-fase3-property-handoff-models]].

**Sintoma adicional observado (2026-08-14, ciclo de correccion Fase 3):** si
al arrancar `pytest tests/ -q` las tablas YA existen con datos sembrados de
una corrida previa (p.ej. alguien corrio `alembic upgrade head` +
`scripts/seed_properties.py` manualmente entre sesiones), `create_all()` no
las toca (ya existen) y el fixture `default_tenant` (id fijo
`DEFAULT_TENANT_ID`) choca con la fila de Tenant ya sembrada por la
migracion —
`sqlalchemy.exc.IntegrityError: duplicate key value violates unique
constraint "tenants_pkey"` en decenas de tests aparentemente no relacionados
entre si (create_lead, search_database, update_lead, handoff_human,
handle_message, golden conversations — cualquiera que use `default_tenant`).
No es un bug del cambio que se este implementando en ese momento: se
diagnostica confirmando que la tabla `tenants` NO existe post-run (el
`drop_all()` de teardown si corrio) y simplemente corriendo `pytest` de
nuevo una vez limpio el estado resuelve el falso positivo.
