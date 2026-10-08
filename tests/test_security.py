"""
Pruebas de validación y robustez de seguridad (SSRF, CRLF, Path Traversal & XSS)
"""

from pathlib import Path
import pytest
from lattice_isr.core.security import (
    StreamSecurityValidator,
    InvalidStreamProtocolError,
    SSRFProhibitedError,
    PathTraversalAttemptError,
    SecurityBaseException
)


def test_valid_local_http_stream():
    url = "http://192.168.1.50:8080/video"
    sanitized = StreamSecurityValidator.sanitize_and_validate_stream_url(url, allow_local_only=True)
    assert sanitized == url


def test_valid_rtsp_stream():
    url = "rtsp://10.0.0.15:554/live/ch0"
    sanitized = StreamSecurityValidator.sanitize_and_validate_stream_url(url, allow_local_only=True)
    assert sanitized == url


def test_prohibited_protocol():
    with pytest.raises(InvalidStreamProtocolError):
        StreamSecurityValidator.sanitize_and_validate_stream_url("file:///etc/passwd")


def test_ssrf_metadata_ip_blocked():
    with pytest.raises(SSRFProhibitedError):
        StreamSecurityValidator.sanitize_and_validate_stream_url("http://169.254.169.254/latest/meta-data/")


def test_ssrf_link_local_subnet_blocked():
    # Cualquier IP en 169.254.0.0/16 debe ser bloqueada
    with pytest.raises(SSRFProhibitedError):
        StreamSecurityValidator.sanitize_and_validate_stream_url("http://169.254.20.10:8080/video")


def test_ssrf_metadata_hostname_blocked():
    with pytest.raises(SSRFProhibitedError):
        StreamSecurityValidator.sanitize_and_validate_stream_url("http://metadata.google.internal/computeMetadata/v1/")


def test_crlf_injection_blocked():
    with pytest.raises(SecurityBaseException):
        StreamSecurityValidator.sanitize_and_validate_stream_url("http://192.168.1.50:8080/video\r\nHost: evil.com")


def test_public_ip_blocked_in_local_only_mode():
    with pytest.raises(SSRFProhibitedError):
        StreamSecurityValidator.sanitize_and_validate_stream_url("http://8.8.8.8:8080/video", allow_local_only=True)


def test_path_traversal_prevention():
    base = Path("./obsidian_vault").resolve()
    target_unsafe = base / ".." / "evil.txt"
    with pytest.raises(PathTraversalAttemptError):
        StreamSecurityValidator.validate_safe_storage_path(base, target_unsafe)


def test_sanitize_filename():
    unsafe_name = "../../etc/passwd..//evil:file*name?.md"
    safe = StreamSecurityValidator.sanitize_filename(unsafe_name)
    assert ".." not in safe
    assert "/" not in safe
    assert "\\" not in safe
    assert ":" not in safe
    assert "*" not in safe
    assert "?" not in safe


def test_sanitize_html_xss():
    malicious = '<script>alert("XSS")</script>'
    cleaned = StreamSecurityValidator.sanitize_html_text(malicious)
    assert "<script>" not in cleaned
    assert "&lt;script&gt;" in cleaned
