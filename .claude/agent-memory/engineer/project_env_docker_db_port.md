---
name: project-env-docker-db-port
description: Local dev Postgres runs via docker-compose on port 5544 (not 5432/5433); Docker Desktop issue from Day 1 was resolved by Day 2
metadata:
  type: project
---

Docker Desktop (which failed to start on Day 1, per BITACORA.md) was fixed
before Day 2 work. Local Postgres now runs as the `corelia-db-1` container
(pgvector/pgvector:pg16) exposed on **port 5544**, per `.env`'s
`DATABASE_URL`. Port 5433 (originally planned in CLAUDE.md/docker-compose)
was changed to 5544 because this machine already has two native Postgres
instances occupying 5432 and 5433. Two other unrelated containers
(`heritage_postgres` on 5432, `heritage_redis` on 6379) also run on this
machine from a different project — not part of CorelIA, ignore them.

**Gotcha found 2026-08-14:** at the start of a session the `corelia-db-1` DB
had its `alembic_version` table stamped at the head revision
(`108f0dd0d579`) but none of the actual tables/enum types existed — likely
from a prior `docker compose down -v` or volume reset that didn't get
followed by a fresh `alembic upgrade head`. Symptom: `alembic upgrade head`
reports "already at head" / does nothing, but `\dt` shows only
`alembic_version`. Fix used: `alembic stamp base` then `alembic upgrade
head` to force real re-creation of tables. Always verify actual table
existence in the DB (not just alembic's reported revision) before trusting
`alembic upgrade head` silently doing nothing — especially after any
docker-compose volume changes.

**How to apply:** before generating a new autogenerate migration, confirm the
DB truly has the tables the previous migrations claim to have created (e.g.
query `information_schema.tables`), not just that `alembic_version` matches
head — otherwise autogenerate will (correctly, from its perspective) propose
recreating the entire schema from scratch.
