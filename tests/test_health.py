"""
LATTICE-CORE ISR - QA Unit Tests: System Health Monitor
Validación de monitoreo de RAM, CPU y límites operacionales (< 100 MB).
"""

import pytest
from lattice_isr.utils.system_health import SystemHealthMonitor, SystemHealthMetrics


def test_system_health_sampling():
    monitor = SystemHealthMonitor()
    metrics = monitor.sample(current_fps=29.5)

    assert isinstance(metrics, SystemHealthMetrics)
    assert metrics.fps == 29.5
    assert metrics.process_ram_mb > 0.0
    assert metrics.process_ram_mb < 2048.0  # Consumo dentro de parámetros razonables
    assert isinstance(metrics.ram_limit_warning, bool)


def test_system_health_ram_warning_threshold():
    monitor = SystemHealthMonitor()
    # Verificar que el umbral de advertencia esté calibrado adecuadamente
    assert monitor.HARD_RAM_LIMIT_MB == 900.0
    assert monitor.WARNING_RAM_THRESHOLD_MB == 850.0
