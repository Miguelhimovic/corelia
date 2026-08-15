---
name: gotcha-pg-enum-reuse-in-migrations
description: How to correctly reuse an existing Postgres ENUM type across two SQLAlchemy models/tables in an Alembic migration without a DuplicateObject error
metadata:
  type: project
---

When a second table's column reuses a Postgres ENUM type already created for a
first table (e.g. `ConversationState.current_state` reusing the `lead_stage`
type originally created for `Lead.stage` — both represent the same 10-state
machine from SPEC.md section 2), Alembic's autogenerate will emit a bare
`sa.Enum(..., name='lead_stage')` in the new migration's `op.create_table`.
Running that migration fails with `psycopg2.errors.DuplicateObject: type
"lead_stage" already exists`.

**Fix:** the migration must reference `sqlalchemy.dialects.postgresql.ENUM`
(not generic `sa.Enum`) with `create_type=False` explicitly:
```python
from sqlalchemy.dialects import postgresql
lead_stage_enum = postgresql.ENUM(
    'NEW', 'DISCOVERING', ..., name='lead_stage', create_type=False,
)
```
Generic `sa.Enum(..., create_type=False)` does NOT work — when SQLAlchemy
adapts a generic `Enum` to the Postgres-native `ENUM` at DDL-emit time, it only
propagates `create_type` from the impl if `type_api._is_native_for_emulated
(impl.__class__)` is true, which is false for plain `sa.Enum`. So the
`create_type=False` you pass on `sa.Enum` is silently dropped and the type
gets created again anyway. You must construct `postgresql.ENUM` directly in
the migration file for `create_type=False` to actually take effect.

**Why this matters:** SPEC.md section 5's data model reuses the same 10-state
enum in more than one place (Lead.stage and ConversationState.current_state),
so this pattern will recur any time a future model needs the same enum.

**How to apply:** whenever autogenerate produces a `create_table` for a model
whose column type is an enum already owned by another table's migration,
manually edit the generated migration to use `postgresql.ENUM(..., create_type
=False)` for that column before considering the migration done. Also verify
with `alembic downgrade -1 && alembic upgrade head` that it round-trips
cleanly, and `alembic check` reports no diff against the models.
