"""Tool `search_database()` para el vertical Real Estate (SPEC.md seccion 4,
Tool Contracts).

Catalogo de propiedades demo (SPEC.md secciones 5 y 13). Para el vertical
Legal, `search_database` se reemplaza por el contrato de RAG (seccion 6) -- no
comparte implementacion con esta funcion.

Algoritmo exacto (SPEC.md seccion 4, recien cerrado -- todos son filtros
duros, deben cumplirse TODOS, sin ranking por "grado de match"):
    - status == 'available' (excluye propiedades no disponibles)
    - location: substring case-insensitive contra city O neighborhood
    - price <= budget_max
    - bedrooms >= bedrooms solicitado (mas habitaciones de las pedidas es
      valido; menos, no)
    - purpose == purpose solicitado (comparacion exacta del enum)
Ordenamiento del resultado filtrado: precio ascendente. Retorna hasta 5. Si
el filtrado da 0 resultados, retorna lista vacia -- no hay segundo intento de
"relajar" criterios dentro de la misma llamada; esa relajacion la maneja el
state machine via `PROPERTY_SEARCH -> DISCOVERING` (SPEC.md seccion 2).
"""

from __future__ import annotations

import logging
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import DEFAULT_TENANT_ID
from app.models.enums import PropertyStatus
from app.models.property import Property
from app.tools.errors import PropertySearchError
from app.tools.schemas import SearchDatabaseInput

logger = logging.getLogger(__name__)

_MAX_RESULTS = 5


def search_database(
    db: Session,
    *,
    location: str,
    budget_max: float,
    bedrooms: int,
    purpose: str,
    request_id: str | None = None,
) -> list[Property]:
    """Busca propiedades del catalogo demo que cumplan TODOS los criterios.

    Se usa para poblar el estado `PRESENTING` del state machine
    (`QUALIFYING -> PROPERTY_SEARCH -> PRESENTING`, SPEC.md seccion 2). Es una
    tool de solo lectura: nunca modifica el catalogo.

    Regla dura (CLAUDE.md, SPEC.md seccion 14): el LLM presenta SOLO lo que
    devuelve esta funcion. Nunca inventa propiedades -- por eso una busqueda
    sin resultados retorna `[]` en vez de lanzar una excepcion: el flujo lo
    maneja como el evento `results_empty` (seccion 2), no como un error.

    Args:
        db: sesion SQLAlchemy inyectada (mismo patron que `app.database.get_db`).
        location: texto a buscar como substring case-insensitive contra
            `city` o `neighborhood` de cada propiedad. No puede estar vacio.
        budget_max: presupuesto maximo del lead. Debe ser `> 0`.
        bedrooms: numero minimo de habitaciones deseado. Debe ser `> 0`. Una
            propiedad con MAS habitaciones de las pedidas si es valida.
        purpose: `"residential"` o `"investment"` (SPEC.md seccion 3). Se
            compara exacto contra `Property.purpose`, sin flexibilidad.
        request_id: opcional, solo para logging (SPEC.md seccion 10 item 5).
            Si no se provee se genera uno nuevo, mismo patron que
            `create_lead`/`update_lead`.

    Returns:
        Hasta 5 `Property` que cumplen todos los filtros duros, ordenadas por
        `price` ascendente. Lista vacia si ninguna cumple -- nunca una
        excepcion por resultado vacio.

    Raises:
        pydantic.ValidationError: `location` vacio, `budget_max`/`bedrooms`
            no positivos, o `purpose` fuera del dominio cerrado (SPEC.md
            seccion 4: "Validacion: budget_max > 0, bedrooms > 0").
        PropertySearchError: PostgreSQL fallo durante la consulta (SPEC.md
            seccion 7).
    """
    request_id = request_id or str(uuid4())

    try:
        validated = SearchDatabaseInput.model_validate(
            {
                "location": location,
                "budget_max": budget_max,
                "bedrooms": bedrooms,
                "purpose": purpose,
            }
        )
    except ValidationError as exc:
        logger.warning(
            "search_database_validation_failed",
            extra={
                "request_id": request_id,
                "tool": "search_database",
                "tool_result": "error",
                "error": str(exc),
            },
        )
        raise

    location_pattern = f"%{validated.location}%"

    try:
        stmt = (
            select(Property)
            .where(
                Property.tenant_id == DEFAULT_TENANT_ID,
                Property.status == PropertyStatus.AVAILABLE,
                or_(
                    Property.city.ilike(location_pattern),
                    Property.neighborhood.ilike(location_pattern),
                ),
                Property.price <= validated.budget_max,
                Property.bedrooms >= validated.bedrooms,
                Property.purpose == validated.purpose,
            )
            .order_by(Property.price.asc())
            .limit(_MAX_RESULTS)
        )
        results = list(db.execute(stmt).scalars().all())
    except SQLAlchemyError as exc:
        logger.error(
            "search_database_query_failed",
            extra={
                "request_id": request_id,
                "tool": "search_database",
                "tool_result": "error",
                "error": str(exc),
            },
        )
        raise PropertySearchError(
            "No se pudo consultar el catalogo (SPEC.md seccion 7): PostgreSQL fallo"
        ) from exc

    logger.info(
        "search_database_succeeded",
        extra={
            "request_id": request_id,
            "tool": "search_database",
            "tool_result": "success" if results else "empty",
            "location": validated.location,
            "budget_max": validated.budget_max,
            "bedrooms": validated.bedrooms,
            "purpose": validated.purpose.value,
            "result_count": len(results),
        },
    )

    return results
