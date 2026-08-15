---
name: project-ruff-migrations-not-excluded
description: RESUELTO 2026-08-14 (re-revisión Fase 2) — pyproject.toml ahora excluye migrations/; ruff check . limpio. Conservar como referencia de vigilancia (regresión posible si alguien quita el exclude o corre ruff pasando migrations/ explícito como path)
metadata:
  type: project
---

**Estado: RESUELTO.** `pyproject.toml` (`[tool.ruff]`) ahora tiene `exclude = ["migrations/"]`. Verificado empíricamente en la re-revisión de Fase 2 (2026-08-14): `ruff check .` desde la raíz del repo → "All checks passed!", 0 errores.

**Nota de verificación importante:** `ruff check migrations/` (pasando el directorio explícito como argumento) SIGUE mostrando los 24 errores de siempre — es comportamiento esperado de ruff, `exclude` en `pyproject.toml` no aplica cuando el path se pasa explícito en el CLI (solo aplica durante el recorrido normal de `.` o de directorios no listados explícitamente). No confundir esto con que el fix no funcionó: el comando documentado en CLAUDE.md es `ruff check .`, y ese es el que importa.

**Historial (antes de resolverse):**
- Revisión Día 1-2 (QA Fase 1 Core): 18 errores.
- Revisión Fase 2 primera vuelta (2026-08-14): 24 errores — escalado a motivo de rechazo tras persistir 2 revisiones.
- Re-revisión Fase 2 (2026-08-14, mismo día): resuelto en el turno siguiente de engineer.

**Cómo aplicar en el futuro:** al revisar cualquier fase nueva que agregue una migración de Alembic, correr `ruff check .` (no `ruff check migrations/`) para confirmar que el exclude sigue vigente. Si `pyproject.toml` pierde la línea `exclude = ["migrations/"]` en algún merge/refactor futuro, este problema puede reaparecer — volver a escalar si se repite.
