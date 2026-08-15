"""Seed de catalogo de propiedades demo. SPEC.md secciones 5, 13 y 4.

Inserta un catalogo ficticio de inmuebles colombianos, todos marcados
`is_demo=True` (SPEC.md seccion 13), contra el tenant fijo del MVP
(`app.config.DEFAULT_TENANT_ID`, CLAUDE.md principio #3).

Variedad generada a proposito para que `search_database()` (SPEC.md seccion 4,
filtros: status=='available', location substring en city/neighborhood,
price<=budget_max, bedrooms>=solicitado, purpose exacto) tenga resultados
realistas al probarse despues, incluyendo combinaciones que deben dar 0
resultados (ej. budget_max muy bajo, o mas de 5 habitaciones):
- 6 ciudades colombianas, varios barrios por ciudad.
- bedrooms de 1 a 5.
- purpose mezclando residential/investment.
- status mayormente 'available', con una porcion de 'reserved'/'sold'/'rented'
  para que search_database las excluya correctamente cuando se implemente.
- precios amplios y creibles para el mercado colombiano (~120M-1.300M COP).

Idempotencia: el catalogo demo no tiene una clave natural para hacer upsert
(los inmuebles son ficticios, no vienen de un sistema externo con id propio).
La estrategia mas simple y segura en desarrollo es borrar-y-reinsertar: cada
corrida borra unicamente las filas `is_demo=True` del tenant fijo y siembra
un set nuevo. Nunca toca filas `is_demo=False` (inventario real futuro de un
cliente), por lo que es seguro re-ejecutar cuantas veces haga falta.

Uso: `python -m scripts.seed_properties` desde la raiz del repo (requiere Postgres
arriba y migraciones aplicadas -- ver CLAUDE.md seccion Comandos). Correrlo como
`python scripts/seed_properties.py` falla con `ModuleNotFoundError: No module
named 'app'` porque Python antepone el directorio del script (no la raiz del
repo) a `sys.path`; `-m` evita ese problema.
"""

from __future__ import annotations

import random
from decimal import Decimal

from app.config import DEFAULT_TENANT_ID
from app.database import SessionLocal
from app.models.enums import LeadPurpose, PropertyStatus
from app.models.property import Property

# Semilla fija: catalogo reproducible entre corridas (mas facil de razonar en
# demos y en tests futuros), no afecta idempotencia porque igual se borra y
# reinserta cada vez.
_RANDOM_SEED = 42

_CITIES: dict[str, list[str]] = {
    "Bogotá": ["Chapinero", "Usaquén", "Cedritos", "Suba", "Chicó", "Kennedy", "La Candelaria"],
    "Medellín": ["El Poblado", "Laureles", "Envigado", "Belén", "Sabaneta"],
    "Cali": ["San Fernando", "Ciudad Jardín", "Granada", "El Peñón"],
    "Pereira": ["Pinares", "Álamos", "Cuba", "El Jardín"],
    "Barranquilla": ["El Prado", "Alto Prado", "Villa Country", "Riomar"],
    "Cartagena": ["Bocagrande", "Manga", "Castillogrande"],
}

# Multiplicador de precio por ciudad -- Bogota/Cartagena/Medellin mas caras
# que Pereira/Cali, coherente con el mercado real (no es un dato preciso,
# solo suficientemente creible para demo comercial, ver BITACORA.md 1-3).
_CITY_PRICE_MULTIPLIER: dict[str, float] = {
    "Bogotá": 1.3,
    "Medellín": 1.2,
    "Cali": 1.0,
    "Pereira": 0.8,
    "Barranquilla": 0.95,
    "Cartagena": 1.4,
}

_PROPERTY_TYPES = ["Apartamento", "Casa", "Apartaestudio", "Penthouse", "Casa campestre"]

_FEATURE_POOL = [
    "piscina",
    "gimnasio",
    "parqueadero",
    "terraza",
    "balcón",
    "seguridad 24h",
    "zona bbq",
    "ascensor",
    "aire acondicionado",
    "closets",
    "conjunto cerrado",
    "vista panorámica",
]

_AVAILABILITY_OPTIONS = ["Inmediata", "30 días", "60 días", "Bajo contrato"]

# Distribucion de status: mayormente disponible, con una porcion vendida/
# reservada/arrendada para que search_database (status=='available') las
# excluya correctamente en pruebas de results_empty.
_STATUS_WEIGHTS: list[tuple[PropertyStatus, int]] = [
    (PropertyStatus.AVAILABLE, 82),
    (PropertyStatus.RESERVED, 8),
    (PropertyStatus.SOLD, 6),
    (PropertyStatus.RENTED, 4),
]

_PURPOSE_WEIGHTS: list[tuple[LeadPurpose, int]] = [
    (LeadPurpose.RESIDENTIAL, 60),
    (LeadPurpose.INVESTMENT, 40),
]

_MIN_PROPERTIES_PER_NEIGHBORHOOD = 4
_MAX_PROPERTIES_PER_NEIGHBORHOOD = 6

# Precio minimo/maximo absoluto (COP) al que se recorta cualquier resultado
# generado, para no producir outliers pocos creibles en la demo.
_PRICE_FLOOR = Decimal("120000000")
_PRICE_CEILING = Decimal("1300000000")


def _weighted_choice(rng: random.Random, weighted: list[tuple]) -> object:
    values = [value for value, _weight in weighted]
    weights = [weight for _value, weight in weighted]
    return rng.choices(values, weights=weights, k=1)[0]


def _generate_price(rng: random.Random, city: str, bedrooms: int) -> Decimal:
    base = 70_000_000 + bedrooms * rng.randint(60_000_000, 140_000_000)
    price = Decimal(base) * Decimal(str(_CITY_PRICE_MULTIPLIER[city]))
    price = price.quantize(Decimal("1"))
    return max(_PRICE_FLOOR, min(_PRICE_CEILING, price))


def generate_properties(tenant_id=DEFAULT_TENANT_ID, seed: int = _RANDOM_SEED) -> list[Property]:
    """Genera instancias `Property` (no persistidas) para el catalogo demo.

    Separado de `seed_properties()` para poder inspeccionar/testear la
    distribucion generada sin tocar la base de datos.
    """
    rng = random.Random(seed)
    properties: list[Property] = []

    for city, neighborhoods in _CITIES.items():
        for neighborhood in neighborhoods:
            count = rng.randint(_MIN_PROPERTIES_PER_NEIGHBORHOOD, _MAX_PROPERTIES_PER_NEIGHBORHOOD)
            for _ in range(count):
                bedrooms = rng.randint(1, 5)
                bathrooms = max(1, bedrooms - rng.choice([0, 0, 1]))
                area = Decimal(35 + bedrooms * 18 + rng.randint(-10, 30))
                property_type = rng.choice(_PROPERTY_TYPES)
                purpose = _weighted_choice(rng, _PURPOSE_WEIGHTS)
                status = _weighted_choice(rng, _STATUS_WEIGHTS)
                price = _generate_price(rng, city, bedrooms)
                features = rng.sample(_FEATURE_POOL, k=rng.randint(2, 5))
                availability = rng.choice(_AVAILABILITY_OPTIONS)
                title = f"{property_type} de {bedrooms} habitaciones en {neighborhood}, {city}"
                purpose_label = "residencial" if purpose == LeadPurpose.RESIDENTIAL else "inversión"
                description = (
                    f"{property_type} ubicado en {neighborhood}, {city}. "
                    f"{bedrooms} habitaciones, {bathrooms} baños, {area} m². "
                    f"Ideal para uso {purpose_label}. "
                    f"[DEMO DATA]"
                )

                properties.append(
                    Property(
                        tenant_id=tenant_id,
                        title=title,
                        property_type=property_type,
                        city=city,
                        neighborhood=neighborhood,
                        price=price,
                        bedrooms=bedrooms,
                        bathrooms=bathrooms,
                        area=area,
                        purpose=purpose,
                        status=status,
                        description=description,
                        features=features,
                        images=[],
                        availability=availability,
                        is_demo=True,
                    )
                )

    return properties


def seed_properties() -> int:
    """Borra el catalogo demo previo del tenant fijo y siembra uno nuevo.

    Solo afecta filas `is_demo=True` del tenant fijo -- seguro de re-ejecutar
    en desarrollo cuantas veces haga falta (ver docstring del modulo).
    Retorna la cantidad de propiedades insertadas.
    """
    session = SessionLocal()
    try:
        deleted = (
            session.query(Property)
            .filter(Property.tenant_id == DEFAULT_TENANT_ID, Property.is_demo.is_(True))
            .delete(synchronize_session=False)
        )
        properties = generate_properties(tenant_id=DEFAULT_TENANT_ID)
        session.add_all(properties)
        session.commit()
        print(f"Borradas {deleted} propiedades demo previas.")
        print(f"Insertadas {len(properties)} propiedades demo nuevas.")
        return len(properties)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    seed_properties()
