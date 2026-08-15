---
name: project-ruff-migrations-not-excluded
description: ruff check . falla con 18 errores en migrations/ (env.py + archivos autogenerados) desde el commit inicial del Día 1 — no bloquea CI porque el workflow no corre ruff
metadata:
  type: project
---

`pyproject.toml` (`[tool.ruff]`) no excluye `migrations/` del linting. `ruff check .` falla consistentemente con 18 errores (import order I001, línea larga E501, UP035) en `migrations/env.py` y en el archivo de migración autogenerado por Alembic. Confirmado con `git stash` que esto existe desde el commit inicial del Día 1 (af65add), no es una regresión introducida en cambios posteriores.

**Por qué importa:** `.github/workflows/test.yml` solo corre `pytest tests/ -q`, no corre `ruff check .` — así que este problema nunca se ve en CI ni bloquea un merge, pero si algún agente reporta "todo en verde" basándose en CI, no está viendo este gap. CLAUDE.md lista `ruff check .` como comando estándar del proyecto.

**Cómo aplicar:** no lo trates como bloqueante de DoD (SPEC.md sección 10 no exige explícitamente "ruff limpio" como ítem), pero mencionarlo como deuda técnica en cada revisión hasta que se resuelva (agregar `exclude = ["migrations/"]` a `[tool.ruff]`, o correr `ruff check . --fix` sobre esos archivos). Si se repite sin resolverse en 2+ revisiones, escalarlo a bloqueante.
