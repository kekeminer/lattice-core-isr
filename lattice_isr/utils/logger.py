"""
LATTICE-CORE ISR - Enterprise Structured Logger
Manejo de logs con rotación automática, serialización JSON y contexto forense.
"""

import sys
from pathlib import Path
from loguru import logger


def setup_logger(log_level: str = "INFO", json_format: bool = True, log_dir: str = "logs") -> None:
    """
    Configura Loguru con sumideros optimizados para bajo consumo de I/O
    y rotación defensiva de archivos de auditoría.
    """
    logger.remove()

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # 1. Salida para terminal (Human Readable, alto contraste táctico)
    console_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level> "
        "{extra}"
    )
    logger.add(
        sys.stderr,
        level=log_level,
        format=console_format,
        colorize=True,
        enqueue=True,  # No bloquea el hilo principal
        backtrace=True,
        diagnose=False  # No filtrar secretos en diagnósticos de producción
    )

    # 2. Salida en disco estructurada (JSON / Rotación por tamaño y tiempo)
    if json_format:
        logger.add(
            str(log_path / "lattice_audit_{time:YYYY-MM-DD}.json.log"),
            level=log_level,
            serialize=True,
            rotation="10 MB",
            retention="14 days",
            compression="zip",
            enqueue=True,
            encoding="utf-8"
        )
    else:
        logger.add(
            str(log_path / "lattice_events_{time:YYYY-MM-DD}.log"),
            level=log_level,
            format=console_format,
            rotation="10 MB",
            retention="14 days",
            compression="zip",
            enqueue=True,
            encoding="utf-8"
        )


__all__ = ["logger", "setup_logger"]
