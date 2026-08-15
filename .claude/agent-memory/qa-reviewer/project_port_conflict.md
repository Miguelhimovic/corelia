---
name: project-port-conflict
description: Esta máquina de desarrollo tiene múltiples PostgreSQL nativos que chocan con los puertos default de docker-compose para CorelIA
metadata:
  type: project
---

La máquina de desarrollo de este proyecto tiene DOS instancias nativas de PostgreSQL instaladas como servicios de Windows (`postgresql-x64-17` y `postgresql-x64-18`) que entre las dos ocupan tanto el puerto 5432 como el 5433. Docker Compose para CorelIA usa ahora el puerto **5544** en el host (`docker-compose.yml`, servicio `db`, mapea `5544:5432`) para evitar el choque.

**Síntoma que causó esto:** fallos intermitentes de "password authentication failed" al pegarle a `:5433` — no error de "puerto en uso", sino dos procesos distintos respondiendo en el mismo puerto en Windows, indistinguibles hasta que se investigó a fondo (descubierto Día 2 del sprint, 2026-08-14).

**Por qué importa:** cualquier cambio futuro de puerto en `docker-compose.yml` debe propagarse a TRES lugares o el problema se repite en otra forma: `.env.example`, `.env` local, y el default hardcodeado en `app/config.py` (`Settings.database_url`). Además, `CLAUDE.md` sección "Comandos" documenta explícitamente el puerto expuesto por `docker compose up -d` — si no se actualiza ahí también, la documentación operativa queda mintiendo sobre el estado real del entorno.

**Cómo aplicar:** al revisar cualquier PR que toque `docker-compose.yml` en la parte de puertos, verificar los 4 lugares (compose, .env.example, app/config.py default, CLAUDE.md) antes de aprobar. Ver también [[feedback-doc-drift-en-cambios-infra]].
