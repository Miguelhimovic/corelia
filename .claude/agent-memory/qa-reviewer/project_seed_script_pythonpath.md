---
name: project-seed-script-pythonpath
description: "RESUELTO 2026-08-14 -- docstring del script y CLAUDE.md ya corregidos a `python -m scripts.seed_properties`. Ver fix abajo."
metadata:
  type: project
---

Detectado en el cierre de sesion de Fase 3, 2026-08-14, al re-sembrar el catalogo demo despues de
correr `pytest tests/ -q` (que hace `drop_all()`, ver [[feedback-doc-drift-en-cambios-infra]]).

**Sintoma:** `python scripts/seed_properties.py` (el comando literal que el propio docstring del
script documenta como forma de uso, linea 26-27 de `scripts/seed_properties.py`) falla con
`ModuleNotFoundError: No module named 'app'`. Causa: `pytest` funciona porque
`pyproject.toml` tiene `[tool.pytest.ini_options] pythonpath = ["."]`, pero eso NO aplica cuando
se ejecuta el script directamente con `python archivo.py` (no hay `__init__.py` en `scripts/`,
tampoco hay instalacion editable del paquete `app`).

**Fix que si funciona (verificado empiricamente):**
- `python -m scripts.seed_properties` desde la raiz del repo (namespace package implicito de
  Python 3, agrega la raiz al `sys.path` automaticamente vs `-m`).
- o `PYTHONPATH=. python scripts/seed_properties.py`.

**Por que no bloquea la aprobacion de la tool/seed en si:** el contenido logico del script
(filtros, marcado `is_demo`, idempotencia borrar-e-insertar) es correcto y fue verificado
corriendo con exito via `-m`. Es puramente un problema de invocacion/documentacion, DoD item 6.

**Como aplicar:** al revisar cualquier script nuevo en `scripts/`, probar el comando EXACTO que su
propio docstring o `CLAUDE.md` documentan, no solo una variante que funcione. Si hace falta
`PYTHONPATH=.`/`python -m`, dejarlo explicito en el docstring del script (y en `CLAUDE.md` si el
script se menciona ahi) para que quien prepare una demo no pierda tiempo con este mismo error.

**RESUELTO 2026-08-14 (cierre de sesion, mismo dia).** `scripts/seed_properties.py` (docstring,
lineas 26-31) y `CLAUDE.md` (seccion Comandos > Tests) actualizados para documentar
`python -m scripts.seed_properties` como el comando correcto, con nota explicita de por que
`python scripts/seed_properties.py` falla.
