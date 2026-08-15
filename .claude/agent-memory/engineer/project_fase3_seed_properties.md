---
name: project-fase3-seed-properties
description: Fase 3 Tarea 2 — script de seed del catalogo demo de Property, decision de delete-then-reinsert, ubicacion en scripts/ no app/
metadata:
  type: project
---

`scripts/seed_properties.py` (SPEC.md secciones 4, 5, 13). Genera ~140-150
propiedades demo (colombianas, 6 ciudades) contra `Property`, todas
`is_demo=True` y `tenant_id=app.config.DEFAULT_TENANT_ID`. Decisiones no
obvias:

- Vive en `scripts/`, no en `app/seed/` — ya existia `scripts/` en el repo
  (con `test_on_change.sh`) y un script de seed no es codigo de runtime de
  la app (no lo importa `app/main.py` ni ningun router), asi que no
  correspondia meterlo dentro de `app/`.
- Idempotencia via **delete-then-reinsert**, no upsert: el catalogo demo no
  tiene clave natural (son inmuebles ficticios). Cada corrida borra solo las
  filas `is_demo=True` del tenant fijo y siembra un set nuevo generado con
  `random.Random(seed_fijo)` (reproducible). Nunca toca `is_demo=False`
  (inventario real futuro).
- Requiere `PYTHONPATH=.` para correr standalone (`python scripts/seed_properties.py`
  falla con `ModuleNotFoundError: No module named 'app'` sin eso) — pytest ya
  lo resuelve via `pythonpath = ["."]` en `pyproject.toml`, pero un script
  fuera de pytest no hereda eso.
- Distribucion verificada empiricamente contra la DB real (no solo leida del
  codigo): 141 propiedades, 6 ciudades, status ~82/8/6/4
  (available/reserved/sold/rented), purpose ~60/40 (residential/investment),
  bedrooms 1-5 con buena dispersion, precios 120M-1.3B COP.

**Gotcha descubierto en esta tarea:** [[gotcha-pytest-drops-dev-db-tables]] —
correr `pytest tests/ -q` borra el catalogo sembrado porque los tests usan
la misma DB de desarrollo. Hubo que reconstruir el schema (`alembic stamp
base` + `upgrade head`, mismo patron que [[project-env-docker-db-port]]) y
re-sembrar despues de cada corrida de tests para dejar la verificacion final
correcta.
