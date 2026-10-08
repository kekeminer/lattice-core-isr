"""
LATTICE-CORE ISR - Security & Input Hardening Layer
Prevención rigurosa de SSRF, inyecciones CRLF, XSS y Path Traversal en bóvedas tácticas.
"""

import html
import ipaddress
import re
import socket
from urllib.parse import urlparse
from pathlib import Path


class SecurityBaseException(Exception):
    """Excepción base para violaciones de seguridad en LATTICE-CORE."""
    pass


class InvalidStreamProtocolError(SecurityBaseException):
    """Se disparó un protocolo de red no admitido."""
    pass


class SSRFProhibitedError(SecurityBaseException):
    """Se detectó un destino no seguro, enlace local o metadatos de nube (SSRF)."""
    pass


class PathTraversalAttemptError(SecurityBaseException):
    """Intento de acceso a directorios fuera de la raíz autorizada."""
    pass


class StreamSecurityValidator:
    """
    Motor de inspección y sanitización defensiva.
    Mitiga vectores de ataque OWASP/CWE:
    - CWE-918: Server-Side Request Forgery (SSRF)
    - CWE-93: CRLF Injection
    - CWE-22: Path Traversal
    - CWE-79: Cross-Site Scripting (XSS)
    """

    ALLOWED_SCHEMES = {"rtsp", "http", "https"}

    # Bloqueo explícito de endpoints de metadatos de infraestructura cloud
    DANGEROUS_METADATA_HOSTS = {
        "metadata.google.internal",
        "metadata.internal",
        "instance-data",
        "169.254.169.254",  # AWS / GCP / Azure Instance Metadata
        "169.254.170.2",    # AWS ECS Task Metadata
        "fd00:ec2::254"     # AWS IPv6 Metadata
    }

    # Redes reservadas prohibidas para SSRF táctico
    PROHIBITED_NETWORKS = [
        ipaddress.ip_network("169.254.0.0/16"),   # Link-Local (APIPA / Cloud Metadata)
        ipaddress.ip_network("224.0.0.0/4"),      # Multicast
        ipaddress.ip_network("240.0.0.0/4"),      # Reservado
        ipaddress.ip_network("0.0.0.0/8"),        # Red local "este host"
        ipaddress.ip_network("fe80::/10"),        # IPv6 Link-Local
        ipaddress.ip_network("ff00::/8"),         # IPv6 Multicast
    ]

    @classmethod
    def sanitize_and_validate_stream_url(cls, raw_url: str, allow_local_only: bool = True) -> str:
        """
        Valida y sanitiza la URL del stream para prevenir SSRF y CRLF.
        """
        if not raw_url or not isinstance(raw_url, str):
            raise SecurityBaseException("La URL del stream debe ser una cadena no vacía.")

        # 1. Detección de inyección CRLF y caracteres nulos o de control
        if re.search(r"[\r\n\t\x00-\x1f\x7f]", raw_url):
            raise SecurityBaseException("Se detectaron caracteres de control prohibidos (CRLF) en la URL.")

        stripped_url = raw_url.strip()

        # 2. Análisis sintáctico del esquema
        parsed = urlparse(stripped_url)
        if not parsed.scheme or parsed.scheme.lower() not in cls.ALLOWED_SCHEMES:
            raise InvalidStreamProtocolError(
                f"Protocolo '{parsed.scheme}' no autorizado. Permitidos: {cls.ALLOWED_SCHEMES}"
            )

        hostname = parsed.hostname
        if not hostname:
            raise SecurityBaseException("La URL del stream no contiene un nombre de host o dirección IP válido.")

        # 3. Comprobación de nombres de host peligrosos de metadatos
        if hostname.lower() in cls.DANGEROUS_METADATA_HOSTS:
            raise SSRFProhibitedError(f"Intento de conexión a servicio de metadatos prohibido: {hostname}")

        # 4. Resolución de IP y mitigación de SSRF
        try:
            ip_obj = ipaddress.ip_address(hostname)
        except ValueError:
            try:
                resolved_ip_str = socket.gethostbyname(hostname)
                ip_obj = ipaddress.ip_address(resolved_ip_str)
            except (socket.gaierror, socket.herror, OSError) as err:
                raise SecurityBaseException(f"No fue posible resolver el host '{hostname}': {err}") from err

        # 5. Bloqueo de rangos prohibidos (Link-local, APIPA, Multicast)
        for net in cls.PROHIBITED_NETWORKS:
            if ip_obj in net:
                raise SSRFProhibitedError(
                    f"Conexión denegada a la IP '{ip_obj}' perteneciente a la red reservada/link-local {net}."
                )

        # 6. Restricción a redes privadas RFC 1918 / Loopback si está en modo táctico
        if allow_local_only:
            is_private = ip_obj.is_private
            is_loopback = ip_obj.is_loopback

            if not (is_private or is_loopback):
                raise SSRFProhibitedError(
                    f"Conexión denegada a la IP pública '{ip_obj}'. "
                    "El modo táctico restringe el tráfico a redes privadas RFC 1918."
                )

        # 7. Validación de puerto
        if parsed.port is not None and not (1 <= parsed.port <= 65535):
            raise SecurityBaseException(f"Puerto fuera de rango válido: {parsed.port}")

        return stripped_url

    @staticmethod
    def sanitize_filename(raw_name: str) -> str:
        """
        Sanitiza un nombre de archivo para prevenir Path Traversal y caracteres inválidos en SO.
        Elimina secuencias '..', separadores de ruta y caracteres prohibidos.
        """
        # Reemplazar separadores de ruta por guiones bajos
        cleaned = re.sub(r"[\\/]", "_", raw_name)
        # Eliminar caracteres ilegales en Windows y Linux: < > : " / \ | ? * y caracteres de control
        cleaned = re.sub(r'[\x00-\x1f<>:"|?*]', "", cleaned)
        # Reemplazar secuencias repetidas de puntos o guiones
        cleaned = re.sub(r"\.{2,}", ".", cleaned)
        cleaned = cleaned.strip(". ")
        if not cleaned:
            cleaned = "unnamed_artifact"
        return cleaned

    @classmethod
    def validate_safe_storage_path(cls, base_dir: Path, target_path: Path) -> Path:
        """
        Previene vulnerabilidades de Path Traversal (CWE-22).
        Verifica mediante Path.resolve() que el destino esté estrictamente contenido en base_dir.
        """
        resolved_base = base_dir.resolve()
        resolved_target = target_path.resolve()

        try:
            # Comprueba si resolved_target es hijo o igual a resolved_base
            resolved_target.relative_to(resolved_base)
        except ValueError as err:
            raise PathTraversalAttemptError(
                f"Ruta de almacenamiento no segura fuera del Vault autorizado: {resolved_target}"
            ) from err

        return resolved_target

    @staticmethod
    def sanitize_html_text(text: str) -> str:
        """
        Sanitiza entradas para prevenir Cross-Site Scripting (XSS, CWE-79)
        al renderizar texto en popups y tablas del visor táctico Leaflet.
        """
        if not isinstance(text, str):
            return ""
        return html.escape(text, quote=True)
