"""Schemas Pydantic de entrada/salida de las tools de `app/tools`
(SPEC.md seccion 4, Tool Contracts).

Un modulo separado (en vez de definir los `BaseModel` dentro de cada
`create_lead.py`/`update_lead.py`) porque `UpdateLeadFields` documenta por si
solo el dominio exacto de campos aceptados por `update_lead()` -- es el
contrato mas facil de leer de un vistazo, y evita que quede enterrado entre
la logica de la funcion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import Channel, LeadIntent, LeadPurpose

# E.164-ish, sin sobre-validar: digito opcional '+' inicial + 7 a 15 digitos.
# SPEC.md seccion 4 solo exige que un telefono invalido levante un error de
# validacion, no un dominio exacto de formato -- este es el minimo razonable
# para no crear leads con telefonos evidentemente basura.
_PHONE_PATTERN = re.compile(r"^\+?[0-9]{7,15}$")


class CreateLeadInput(BaseModel):
    """Valida los parametros de `create_lead()` (SPEC.md seccion 4).

    `extra="forbid"`: cualquier campo fuera de los 4 del contrato es un error
    de quien llama a la tool, no algo que se deba ignorar en silencio.
    """

    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1)
    # `Channel` (no `str`) fuerza el dominio cerrado web|whatsapp que pide
    # SPEC.md seccion 4 ("Validacion de channel (enum web|whatsapp)") sin
    # tener que reimplementar el chequeo a mano.
    channel: Channel
    phone: str | None = None
    initial_message: str = Field(min_length=1)

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not _PHONE_PATTERN.fullmatch(normalized):
            raise ValueError(
                "phone invalido: se esperan solo digitos (con '+' inicial "
                "opcional), entre 7 y 15 digitos"
            )
        return normalized


@dataclass(frozen=True)
class CreateLeadResult:
    """SPEC.md seccion 4 dice que `create_lead()` "retorna lead_id" -- se
    devuelve un resultado mas rico que solo `LeadID` porque esta tarea
    tambien crea la `Conversation` y el primer `Message` (instruccion
    explicita de la Tarea 3: "el lead nace junto con su conversacion
    inicial"). `conversation_id`/`message_id` los va a necesitar quien
    conecte esto al orquestador (Fase 3, Tarea 6) para llamar
    `process_incoming_message()` a partir del mismo turno -- no ampliar el
    contrato aqui obligaria a esa tarea a volver a consultar la DB para
    encontrar la conversacion que esta misma llamada acaba de crear.
    `lead_id` se mantiene como primer campo para que siga siendo el valor
    principal del contrato de SPEC.md.
    """

    lead_id: UUID
    conversation_id: UUID
    message_id: UUID


class SearchDatabaseInput(BaseModel):
    """Valida los parametros de `search_database()` (SPEC.md seccion 4).

    Los 4 parametros del contrato son obligatorios ("Precondicion: los 4
    parametros no-null"): no hay campos `Optional` aqui a proposito, a
    diferencia de `UpdateLeadFields`, que si soporta actualizacion parcial.
    `budget_max`/`bedrooms` ademas exigen `> 0` (SPEC.md seccion 4:
    "Validacion: budget_max > 0, bedrooms > 0") -- Pydantic rechaza con
    `ValidationError` antes de tocar la DB, mismo patron fail-safe que
    `CreateLeadInput`.

    `purpose` usa el tipo `LeadPurpose` (no `str`) para que la comparacion
    "purpose == purpose solicitado" del algoritmo (seccion 4) sea una
    comparacion de enum exacta, y para que un valor fuera del dominio cerrado
    levante `ValidationError` en vez de silenciosamente no matchear nada.
    """

    model_config = ConfigDict(extra="forbid")

    location: str = Field(min_length=1)
    budget_max: float = Field(gt=0)
    bedrooms: int = Field(gt=0)
    purpose: LeadPurpose


class HandoffHumanInput(BaseModel):
    """Valida los parametros de `handoff_human()` (SPEC.md seccion 4).

    `lead_id` se valida aqui tambien (no solo como type hint de la funcion)
    para que un `UUID` mal formado en el limite de la tool (p.ej. si algun
    dia se expone via API/tool-calling con strings crudos) levante el mismo
    `ValidationError` fail-fast que el resto de las tools, en vez de fallar
    mas tarde con un error de SQLAlchemy menos claro. `reason`/`summary` son
    obligatorios y no vacios: SPEC.md seccion 7 exige que el humano reciba
    contexto real, un handoff sin motivo ni resumen no cumple el contrato de
    "informacion entregada al humano".
    """

    model_config = ConfigDict(extra="forbid")

    lead_id: UUID
    reason: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class UpdateLeadFields(BaseModel):
    """Dominio exacto de campos que `update_lead()` acepta en `fields`
    (SPEC.md seccion 4 y seccion 5 recien cerrada).

    `extra="forbid"` es la validacion misma que exige el contrato: `stage` y
    `score` (pipeline, no editables via esta tool) y cualquier otro campo que
    no sea del schema de `Lead` quedan fuera de este modelo a proposito, asi
    que Pydantic los rechaza igual que un typo -- "rechazar con error de
    validacion es mas seguro que ignorar en silencio" (instruccion de la
    Tarea 3), sin necesidad de una lista aparte de campos prohibidos.

    `bedrooms`/`purpose` se incluyen aunque el enunciado de la Tarea 3 los
    omite de su lista de campos en prosa: esa lista es la misma que
    `CLAUDE.md` "Modelo de datos (Fase 1)" (previa a que `bedrooms`/`purpose`
    se agregaran al modelo `Lead` en SPEC.md seccion 1 como 2 de los 4 slots
    requeridos). El propio contrato de la Tarea 3 dice, en la misma frase,
    "entities del LLM pasan por el contrato de la seccion 3 antes de llegar
    aqui" -- y esas `entities` son exactamente
    `location/budget_max/bedrooms/purpose` (SPEC.md seccion 3). Sin aceptar
    `bedrooms`/`purpose` aqui, el orquestador (Fase 2, Tarea 5) nunca podria
    persistir 2 de los 4 slots que el mismo ya expone en
    `TurnResult.merged_entities` para pasarselos a esta tool -- se interpreta
    como un vacio de la lista en prosa, no como una exclusion deliberada.

    Cada campo es `Optional` con default `None` para soportar actualizacion
    parcial: `update_lead()` usa `model_dump(exclude_unset=True)`, que en
    Pydantic v2 distingue "no vino en `fields`" de "vino explicitamente en
    `None`" segun si la clave estuvo presente en el dict de entrada.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    phone: str | None = None
    email: str | None = None
    source: str | None = None
    intent: LeadIntent | None = None
    location: str | None = None
    budget_max: float | None = None
    bedrooms: int | None = None
    purpose: LeadPurpose | None = None
    last_contact_at: datetime | None = None
    next_contact_at: datetime | None = None

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not _PHONE_PATTERN.fullmatch(normalized):
            raise ValueError(
                "phone invalido: se esperan solo digitos (con '+' inicial "
                "opcional), entre 7 y 15 digitos"
            )
        return normalized
