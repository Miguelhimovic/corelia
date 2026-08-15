"""Excepciones compartidas de las tools de `app/tools` (SPEC.md secciones 4 y 7).

Mismo patron que `app/agent_engine/orchestrator.py`: una jerarquia propia por
modulo/capa en vez de reutilizar excepciones genericas, para que el llamador
(orquestador o, mas adelante, la capa API) pueda distinguir "no se pudo
validar la entrada", "el recurso no existe" y "PostgreSQL fallo" sin parsear
mensajes de texto.
"""

from __future__ import annotations

from uuid import UUID


class ToolError(Exception):
    """Base de las excepciones de `app/tools`."""


class LeadNotFoundError(ToolError):
    """`lead_id` no existe. SPEC.md seccion 4 (`update_lead`): "lead_id no
    existe -> 404 logico, se loguea y se responde con handoff" -- el logueo y
    la decision de handoff son responsabilidad de quien llama a la tool
    (orquestador / capa API), esta excepcion solo senaliza la precondicion
    incumplida.
    """

    def __init__(self, lead_id: UUID) -> None:
        self.lead_id = lead_id
        super().__init__(f"Lead {lead_id} no existe")


class LeadPersistenceError(ToolError):
    """PostgreSQL fallo durante la persistencia (SPEC.md seccion 7:
    "PostgreSQL cae -> 503 logico, no se pierde el mensaje entrante ... no se
    inventa respuesta"). Mismo principio que
    `orchestrator.OrchestratorPersistenceError`.
    """


class PropertySearchError(ToolError):
    """PostgreSQL fallo durante `search_database()` (SPEC.md seccion 7).

    Distinta de una busqueda que simplemente no encuentra resultados (esa
    devuelve `[]`, no levanta excepcion -- ver `search_database.py`): esta
    excepcion es solo para el caso de fallo real de la base de datos, para no
    confundir "no hay propiedades que cumplan los criterios" con "no se pudo
    ni siquiera consultar el catalogo".
    """
