from functools import lru_cache
from uuid import UUID

from pydantic_settings import BaseSettings, SettingsConfigDict

# Tenant unico y hardcodeado para el MVP (CLAUDE.md principio #3, SPEC.md
# seccion 5 y 12). No se lee de entorno ni de base de datos a proposito:
# implementar seleccion de tenant aqui seria empezar a construir
# multi-tenancy, que esta explicitamente fuera de alcance en esta fase.
DEFAULT_TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "CorelIA API"
    environment: str = "local"
    database_url: str = "postgresql+psycopg2://corelia:corelia@localhost:5544/corelia"
    anthropic_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
