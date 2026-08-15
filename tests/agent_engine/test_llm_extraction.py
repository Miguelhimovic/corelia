"""Unit tests de la extraccion via LLM (SPEC.md seccion 3 y 7).

`ANTHROPIC_API_KEY` esta vacia en este entorno (ver .env / memoria de
engineer) — nunca se llama a la API real. Se inyecta un doble de
`AsyncAnthropic` (`tests/agent_engine/llm_test_doubles.py`) via el parametro
`client` de `extract_with_llm`, exactamente el mecanismo que el modulo
documenta como pensado para tests.
"""

import asyncio
import logging

import anthropic
import httpx
import pytest

from app.agent_engine.llm_extraction import LLMExtractionFailed, extract_with_llm
from app.models.enums import LeadIntent, LeadPurpose
from tests.agent_engine.llm_test_doubles import (
    FakeAsyncAnthropic,
    make_no_tool_use_response,
    make_tool_use_response,
)

_VALID_PAYLOAD = {
    "intent": "property_search",
    "entities": {
        "location": "Pinares",
        "budget_max": 450_000_000,
        "bedrooms": 3,
        "purpose": "residential",
    },
    "confidence": 0.92,
    "requires_clarification": False,
}


def _fake_request(*, request_url: str = "https://api.anthropic.com/v1/messages") -> httpx.Request:
    return httpx.Request("POST", request_url)


class TestValidExtraction:
    def test_valid_payload_returns_matching_extraction_result(self) -> None:
        client = FakeAsyncAnthropic([make_tool_use_response(_VALID_PAYLOAD)])

        result = asyncio.run(extract_with_llm("Busco apto en Pinares", client=client))

        assert result.intent == LeadIntent.PROPERTY_SEARCH
        assert result.entities.location == "Pinares"
        assert result.entities.budget_max == 450_000_000
        assert result.entities.bedrooms == 3
        assert result.entities.purpose == LeadPurpose.RESIDENTIAL
        assert result.confidence == pytest.approx(0.92)
        assert result.requires_clarification is False
        assert len(client.messages.calls) == 1

    def test_single_call_uses_non_strict_system_prompt(self) -> None:
        client = FakeAsyncAnthropic([make_tool_use_response(_VALID_PAYLOAD)])
        asyncio.run(extract_with_llm("Busco apto", client=client))
        assert "IMPORTANTE" not in client.messages.calls[0]["system"]

    def test_null_entities_are_preserved_as_explicit_none(self) -> None:
        payload = {
            "intent": "question",
            "entities": {
                "location": None,
                "budget_max": None,
                "bedrooms": None,
                "purpose": None,
            },
            "confidence": 0.8,
            "requires_clarification": False,
        }
        client = FakeAsyncAnthropic([make_tool_use_response(payload)])
        result = asyncio.run(extract_with_llm("Hola", client=client))
        assert result.intent == LeadIntent.QUESTION
        assert result.entities.location is None
        assert result.entities.budget_max is None


class TestEnumViolationsDegrade:
    def test_invalid_intent_degrades_to_other(self) -> None:
        payload = {**_VALID_PAYLOAD, "intent": "buy_now_please"}
        client = FakeAsyncAnthropic([make_tool_use_response(payload)])
        result = asyncio.run(extract_with_llm("mensaje raro", client=client))
        assert result.intent == LeadIntent.OTHER

    def test_invalid_purpose_degrades_to_null(self) -> None:
        payload = {
            **_VALID_PAYLOAD,
            "entities": {**_VALID_PAYLOAD["entities"], "purpose": "vacation_home"},
        }
        client = FakeAsyncAnthropic([make_tool_use_response(payload)])
        result = asyncio.run(extract_with_llm("mensaje raro", client=client))
        assert result.entities.purpose is None

    def test_enum_violation_does_not_raise_and_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        payload = {**_VALID_PAYLOAD, "intent": "not_a_real_intent"}
        client = FakeAsyncAnthropic([make_tool_use_response(payload)])
        with caplog.at_level(logging.WARNING, logger="app.agent_engine.llm_extraction"):
            result = asyncio.run(extract_with_llm("mensaje raro", client=client))
        assert result.intent == LeadIntent.OTHER
        assert any("llm_schema_violation_intent" in record.message for record in caplog.records)


class TestConfidenceForcesClarification:
    def test_confidence_below_threshold_forces_requires_clarification_true(self) -> None:
        payload = {**_VALID_PAYLOAD, "confidence": 0.3, "requires_clarification": False}
        client = FakeAsyncAnthropic([make_tool_use_response(payload)])
        result = asyncio.run(extract_with_llm("mensaje ambiguo", client=client))
        assert result.confidence == pytest.approx(0.3)
        assert result.requires_clarification is True

    def test_confidence_at_or_above_threshold_respects_llm_flag(self) -> None:
        payload = {**_VALID_PAYLOAD, "confidence": 0.7, "requires_clarification": False}
        client = FakeAsyncAnthropic([make_tool_use_response(payload)])
        result = asyncio.run(extract_with_llm("mensaje claro", client=client))
        assert result.requires_clarification is False

    def test_confidence_exactly_at_boundary_0_5_does_not_force_clarification(self) -> None:
        payload = {**_VALID_PAYLOAD, "confidence": 0.5, "requires_clarification": False}
        client = FakeAsyncAnthropic([make_tool_use_response(payload)])
        result = asyncio.run(extract_with_llm("mensaje limite", client=client))
        assert result.requires_clarification is False


class TestRetryOnMalformedOutput:
    def test_no_tool_use_first_then_valid_on_retry_succeeds(self) -> None:
        client = FakeAsyncAnthropic(
            [make_no_tool_use_response(), make_tool_use_response(_VALID_PAYLOAD)]
        )
        result = asyncio.run(extract_with_llm("mensaje", client=client))
        assert result.intent == LeadIntent.PROPERTY_SEARCH
        assert len(client.messages.calls) == 2

    def test_retry_uses_strict_system_prompt(self) -> None:
        client = FakeAsyncAnthropic(
            [make_no_tool_use_response(), make_tool_use_response(_VALID_PAYLOAD)]
        )
        asyncio.run(extract_with_llm("mensaje", client=client))
        assert "IMPORTANTE" in client.messages.calls[1]["system"]

    def test_schema_invalid_first_then_valid_on_retry_succeeds(self) -> None:
        invalid_payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "confidence"}
        client = FakeAsyncAnthropic(
            [make_tool_use_response(invalid_payload), make_tool_use_response(_VALID_PAYLOAD)]
        )
        result = asyncio.run(extract_with_llm("mensaje", client=client))
        assert result.intent == LeadIntent.PROPERTY_SEARCH
        assert len(client.messages.calls) == 2

    def test_persistent_no_tool_use_raises_llm_extraction_failed(self) -> None:
        client = FakeAsyncAnthropic([make_no_tool_use_response(), make_no_tool_use_response()])
        with pytest.raises(LLMExtractionFailed):
            asyncio.run(extract_with_llm("mensaje", client=client))
        assert len(client.messages.calls) == 2

    def test_persistent_schema_invalid_raises_llm_extraction_failed(self) -> None:
        invalid_payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "confidence"}
        client = FakeAsyncAnthropic(
            [make_tool_use_response(invalid_payload), make_tool_use_response(invalid_payload)]
        )
        with pytest.raises(LLMExtractionFailed):
            asyncio.run(extract_with_llm("mensaje", client=client))
        assert len(client.messages.calls) == 2


class TestApiFailure:
    def test_api_connection_error_raises_llm_extraction_failed_without_second_attempt(self) -> None:
        error = anthropic.APIConnectionError(request=_fake_request())
        client = FakeAsyncAnthropic([error])
        with pytest.raises(LLMExtractionFailed):
            asyncio.run(extract_with_llm("mensaje", client=client))
        # Fallo de API -> escala de inmediato, no reintenta con prompt distinto.
        assert len(client.messages.calls) == 1

    def test_api_status_error_raises_llm_extraction_failed(self) -> None:
        response = httpx.Response(status_code=500, request=_fake_request())
        error = anthropic.APIStatusError("server error", response=response, body=None)
        client = FakeAsyncAnthropic([error])
        with pytest.raises(LLMExtractionFailed):
            asyncio.run(extract_with_llm("mensaje", client=client))
        assert len(client.messages.calls) == 1
