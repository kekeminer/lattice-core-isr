"""
LATTICE-CORE ISR - WebSocket Security & Constant-Time Token Authentication
Mecanismo de autorización precompartida (PSK) con mitigación de Timing Attacks (CWE-208).
"""

import hmac
from typing import Optional
from fastapi import WebSocket, status
from loguru import logger

from lattice_isr.config.settings import SystemSettings


class AuthenticationError(Exception):
    """Excepción generada ante intentos de acceso no autorizados al flujo táctico."""
    pass


class WebSocketAuthenticator:
    """
    Autenticador de sesiones WebSocket tácticas.
    Valida tokens de acceso usando comparación criptográfica de tiempo constante.
    """

    # Códigos de cierre estándar de seguridad para WebSocket
    WS_CLOSE_UNAUTHORIZED = 4001  # Token no suministrado o inválido
    WS_CLOSE_FORBIDDEN = 4003     # Acceso denegado

    def __init__(self, settings: SystemSettings):
        self._settings = settings
        self._expected_token = settings.API_AUTH_TOKEN

    def authenticate_query_token(self, provided_token: Optional[str], client_ip: str = "Unknown") -> bool:
        """
        Comprueba la validez del token recibido mediante comparación de tiempo constante.
        Previene ataques de canal lateral basados en temporización (Timing Attacks).
        """
        if not provided_token or not isinstance(provided_token, str):
            logger.warning(f"[SEC-AUTH] Intento de conexión WebSocket sin token desde {client_ip}.")
            return False

        # Comparación de tiempo constante (Constant-time string comparison)
        is_valid = hmac.compare_digest(
            provided_token.encode("utf-8"),
            self._expected_token.encode("utf-8")
        )

        if not is_valid:
            logger.warning(f"[SEC-AUTH-REJECT] Token inválido rechazado desde {client_ip}.")
            return False

        logger.info(f"[SEC-AUTH-OK] Conexión WebSocket autorizada desde {client_ip}.")
        return True

    async def verify_websocket_handshake(self, websocket: WebSocket) -> bool:
        """
        Verifica el handshake de la conexión entrante antes de aceptar la sesión.
        Si la autenticación falla, cierra el socket con código de error de seguridad.
        """
        token = websocket.query_params.get("token")
        client_host = websocket.client.host if websocket.client else "Unknown"

        if not self.authenticate_query_token(token, client_host):
            await websocket.close(
                code=self.WS_CLOSE_UNAUTHORIZED,
                reason="Acceso denegado: Token de autenticacion invalido o ausente."
            )
            return False

        return True
