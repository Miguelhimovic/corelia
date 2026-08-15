"""Unit tests del classifier determinista (SPEC.md seccion 1).

Cubre las 3 reglas (human_request, cancel, not_interested), normalizacion de
texto (tildes/mayusculas/espacios) y el caso negativo central: cualquier
mensaje que requiera extraer slots (location/budget_max/bedrooms/purpose) de
lenguaje natural debe devolver None para que el orquestador delegue al LLM.
"""

import pytest

from app.agent_engine.classifier import classify_deterministic, normalize_text
from app.agent_engine.schemas import ExtractionResult
from app.models.enums import LeadIntent


class TestNormalizeText:
    def test_lowercases(self) -> None:
        assert normalize_text("HABLAR con un ASESOR") == "hablar con un asesor"

    def test_strips_accents(self) -> None:
        assert normalize_text("informacion") == "informacion"
        assert normalize_text("razón") == "razon"

    def test_collapses_whitespace_and_strips_borders(self) -> None:
        assert normalize_text("  quiero   cancelar   la cita  ") == "quiero cancelar la cita"

    def test_combined_accents_and_case(self) -> None:
        assert normalize_text("Ya NO me INTERÉSA") == "ya no me interesa"

    def test_empty_string_stays_empty(self) -> None:
        assert normalize_text("") == ""
        assert normalize_text("   ") == ""


class TestHumanRequestRule:
    @pytest.mark.parametrize(
        "message",
        [
            "Quiero hablar con una persona",
            "Necesito hablar con un asesor",
            "¿Puedo hablar con alguien?",
            "Pásame con un agente humano",
            "quiero un asesor",
        ],
    )
    def test_matches_human_request_variants(self, message: str) -> None:
        result = classify_deterministic(message)
        assert result is not None
        assert result.intent == LeadIntent.HUMAN_REQUEST

    def test_matches_regardless_of_case_and_accents(self) -> None:
        result = classify_deterministic("QUIERO HABLAR CON UN ASESOR")
        assert result is not None
        assert result.intent == LeadIntent.HUMAN_REQUEST

    def test_result_shape_is_deterministic_confidence_and_null_entities(self) -> None:
        result = classify_deterministic("Quiero hablar con una persona")
        assert isinstance(result, ExtractionResult)
        assert result.confidence == 1.0
        assert result.requires_clarification is False
        assert result.entities.location is None
        assert result.entities.budget_max is None
        assert result.entities.bedrooms is None
        assert result.entities.purpose is None

    def test_human_request_evaluated_before_other_rules_on_same_message(self) -> None:
        # Frase que combina "asesor" (human_request) y "cancelar" (cancel) —
        # el classifier debe resolver human_request primero (SPEC.md seccion
        # 1: es la transicion de mayor prioridad).
        result = classify_deterministic("Quiero cancelar pero antes hablar con un asesor")
        assert result is not None
        assert result.intent == LeadIntent.HUMAN_REQUEST


class TestCancelRule:
    @pytest.mark.parametrize(
        "message",
        [
            "Quiero cancelar mi cita",
            "Necesito cancelar la reunion",
            "Quiero reagendar",
            "Necesito reprogramar",
            "No puedo asistir a la cita",
            "Quiero cambiar mi cita",
        ],
    )
    def test_matches_cancel_variants(self, message: str) -> None:
        result = classify_deterministic(message)
        assert result is not None
        assert result.intent == LeadIntent.CANCEL

    def test_matches_with_accents_and_uppercase(self) -> None:
        result = classify_deterministic("QUIERO CANCELAR MI CITA")
        assert result is not None
        assert result.intent == LeadIntent.CANCEL


class TestNotInterestedRule:
    @pytest.mark.parametrize(
        "message",
        [
            "Ya no me interesa",
            "No me interesa",
            "No, gracias",
            "No quiero continuar",
            "Ya no quiero",
            "Dejalo asi",
        ],
    )
    def test_matches_not_interested_variants(self, message: str) -> None:
        result = classify_deterministic(message)
        assert result is not None
        assert result.intent == LeadIntent.NOT_INTERESTED

    def test_matches_with_accent_variant(self) -> None:
        result = classify_deterministic("Ya no me interésa, gracias")
        assert result is not None
        assert result.intent == LeadIntent.NOT_INTERESTED


class TestFallsThroughToLLM:
    @pytest.mark.parametrize(
        "message",
        [
            "Busco apartamento en Pinares, maximo 450 millones, 3 habitaciones, para vivir",
            "Estoy buscando un apartamento en el poblado",
            "¿Tienen financiacion con el banco?",
            "Hola, buenos dias",
            "Quiero un apartamento de 2 habitaciones para invertir",
            "Cuanto cuesta el apartamento en Laureles",
        ],
    )
    def test_slot_bearing_or_unmatched_messages_return_none(self, message: str) -> None:
        assert classify_deterministic(message) is None

    def test_empty_message_returns_none(self) -> None:
        assert classify_deterministic("") is None
        assert classify_deterministic("   ") is None

    def test_partial_keyword_without_full_pattern_returns_none(self) -> None:
        # "asesor" aislado sin el patron completo ("hablar con.../quiero un
        # asesor") no deberia disparar una regla por accidente de substring.
        message = "El asesor comercial de la inmobiliaria me llamo ayer"
        assert classify_deterministic(message) is None
