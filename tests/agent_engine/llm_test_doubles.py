"""Dobles de prueba para `AsyncAnthropic` (SPEC.md seccion 3 y 7).

No se usa la API real de Claude en tests (`ANTHROPIC_API_KEY` vacia en este
entorno) — estos dobles imitan exactamente la superficie que
`app/agent_engine/llm_extraction.py` consume de `client.messages.create()`:
`response.content` (lista de bloques con `.type`/`.name`/`.input`) y
`response.usage` (opcional, via `getattr`).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

_TOOL_NAME = "extract_lead_intent"


def make_tool_use_response(input_payload: dict[str, Any]) -> SimpleNamespace:
    """Respuesta con un unico bloque `tool_use` (el caso feliz del contrato)."""
    block = SimpleNamespace(type="tool_use", name=_TOOL_NAME, input=input_payload)
    usage = SimpleNamespace(input_tokens=42, output_tokens=7)
    return SimpleNamespace(content=[block], usage=usage)


def make_no_tool_use_response() -> SimpleNamespace:
    """Respuesta sin ningun bloque `tool_use` — tratada como salida invalida."""
    block = SimpleNamespace(type="text", text="no deberia pasar con tool_choice forzado")
    return SimpleNamespace(content=[block], usage=None)


class FakeMessagesEndpoint:
    """Doble de `client.messages` que devuelve una respuesta/excepcion por
    llamada, en el orden dado. Cada elemento de `queue` es una respuesta
    (SimpleNamespace) o una excepcion (instancia, no clase) para levantar."""

    def __init__(self, queue: list[Any]) -> None:
        self._queue = list(queue)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if not self._queue:
            raise AssertionError("FakeMessagesEndpoint: mas llamadas de las esperadas")
        item = self._queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class FakeAsyncAnthropic:
    """Doble minimo de `anthropic.AsyncAnthropic` — solo expone `.messages`,
    que es todo lo que `extract_with_llm` toca."""

    def __init__(self, queue: list[Any]) -> None:
        self.messages = FakeMessagesEndpoint(queue)
