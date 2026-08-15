from fastapi import FastAPI

from app.api.health import router as health_router
from app.config import get_settings
from app.logging_config import configure_logging

# Se llama al importar el modulo (entrypoint de la app), antes de crear
# cualquier logger de negocio -- ver docstring de `configure_logging` para
# el porque (SPEC.md seccion 10 item 5, hallazgo de QA en Fase 2).
configure_logging()

settings = get_settings()

app = FastAPI(title=settings.app_name)
app.include_router(health_router)
