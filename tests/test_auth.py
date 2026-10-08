"""
LATTICE-CORE ISR - QA Unit Tests: WebSocket Authentication
Validación de comparación de tokens en tiempo constante y rechazo de accesos no autorizados.
"""

import pytest
from lattice_isr.config.settings import SystemSettings
from lattice_isr.network.security_auth import WebSocketAuthenticator


def test_auth_valid_token():
    settings = SystemSettings(API_AUTH_TOKEN="SECRET-KEY-ALPHA-99")
    auth = WebSocketAuthenticator(settings)

    assert auth.authenticate_query_token("SECRET-KEY-ALPHA-99", "127.0.0.1") is True


def test_auth_invalid_token():
    settings = SystemSettings(API_AUTH_TOKEN="SECRET-KEY-ALPHA-99")
    auth = WebSocketAuthenticator(settings)

    assert auth.authenticate_query_token("WRONG-KEY-XYZ", "127.0.0.1") is False


def test_auth_missing_or_empty_token():
    settings = SystemSettings(API_AUTH_TOKEN="SECRET-KEY-ALPHA-99")
    auth = WebSocketAuthenticator(settings)

    assert auth.authenticate_query_token(None, "127.0.0.1") is False
    assert auth.authenticate_query_token("", "127.0.0.1") is False


def test_auth_timing_safe_comparison():
    # Verifica que la comparación sea insensible a longitudes distintas sin excepciones
    settings = SystemSettings(API_AUTH_TOKEN="LONG-TOKEN-1234567890")
    auth = WebSocketAuthenticator(settings)

    assert auth.authenticate_query_token("SHORT", "127.0.0.1") is False
    assert auth.authenticate_query_token("LONG-TOKEN-1234567891", "127.0.0.1") is False


def test_auth_default_lattice2026_token():
    settings = SystemSettings()  # Toma default lattice2026
    auth = WebSocketAuthenticator(settings)

    assert auth.authenticate_query_token("lattice2026", "127.0.0.1") is True
    assert auth.authenticate_query_token("wrongtoken", "127.0.0.1") is False
