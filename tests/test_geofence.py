"""
LATTICE-CORE ISR - QA Unit Tests: Geofence Manager
Validación de cálculo Haversine y detección de PERIMETER_BREACH.
"""

import pytest
from lattice_isr.config.settings import SystemSettings
from lattice_isr.engine.geolocation_engine import TargetGeoPosition
from lattice_isr.engine.geofence_engine import GeofenceManager


def test_geofence_perimeter_breach():
    settings = SystemSettings(
        BASE_SENSOR_LAT=-31.624510,
        BASE_SENSOR_LON=-60.485120,
        GEOFENCE_RADIUS_METERS=50.0
    )
    manager = GeofenceManager(settings)

    # Coordenada muy cercana a la base (aprox 15m al norte)
    pos_inside = TargetGeoPosition(
        target_id="TRG-BREACH",
        latitude=-31.624370,
        longitude=-60.485120,
        altitude_m=25.0,
        azimuth_deg=0.0,
        distance_ground_m=15.0,
        utm_zone="20J",
        mgrs_grid="20J MK 100 200",
        maps_url="https://maps.google.com"
    )

    status = manager.evaluate_target(pos_inside)
    assert status.is_breaching is True
    assert status.status == "PERIMETER_BREACH"
    assert status.distance_to_base_m < 50.0


def test_geofence_perimeter_safe():
    settings = SystemSettings(
        BASE_SENSOR_LAT=-31.624510,
        BASE_SENSOR_LON=-60.485120,
        GEOFENCE_RADIUS_METERS=30.0
    )
    manager = GeofenceManager(settings)

    # Coordenada lejana (aprox 200m)
    pos_outside = TargetGeoPosition(
        target_id="TRG-FAR",
        latitude=-31.622500,
        longitude=-60.485120,
        altitude_m=25.0,
        azimuth_deg=0.0,
        distance_ground_m=200.0,
        utm_zone="20J",
        mgrs_grid="20J MK 100 200",
        maps_url="https://maps.google.com"
    )

    status = manager.evaluate_target(pos_outside)
    assert status.is_breaching is False
    assert status.status == "SAFE"
    assert status.distance_to_base_m > 30.0


def test_geofence_alert_throttling():
    import time
    settings = SystemSettings(
        BASE_SENSOR_LAT=-31.624510,
        BASE_SENSOR_LON=-60.485120,
        GEOFENCE_RADIUS_METERS=50.0,
        LOG_ALERT_THROTTLE_SECONDS=2.0
    )
    manager = GeofenceManager(settings)

    pos = TargetGeoPosition(
        target_id="TRG-THROTTLE",
        latitude=-31.624510,
        longitude=-60.485120,
        altitude_m=25.0,
        azimuth_deg=0.0,
        distance_ground_m=0.0,
        utm_zone="20J",
        mgrs_grid="20J MK 100 200",
        maps_url="https://maps.google.com"
    )

    # Primera evaluación registra timestamp en _last_alert_timestamps
    s1 = manager.evaluate_target(pos)
    assert s1.is_breaching is True
    assert "TRG-THROTTLE" in manager._last_alert_timestamps
    t1 = manager._last_alert_timestamps["TRG-THROTTLE"]

    # Segunda evaluación inmediata no debe actualizar timestamp por estar throttled
    s2 = manager.evaluate_target(pos)
    assert s2.is_breaching is True
    assert manager._last_alert_timestamps["TRG-THROTTLE"] == t1


def test_geofence_sustained_breach_for_export():
    import time
    settings = SystemSettings(
        BASE_SENSOR_LAT=-31.624510,
        BASE_SENSOR_LON=-60.485120,
        GEOFENCE_RADIUS_METERS=15.0,
        GEOFENCE_MIN_BREACH_SECONDS=3.0
    )
    manager = GeofenceManager(settings)

    pos = TargetGeoPosition(
        target_id="TRG-DWELL",
        latitude=-31.624510,
        longitude=-60.485120,
        altitude_m=25.0,
        azimuth_deg=0.0,
        distance_ground_m=0.0,
        utm_zone="20J",
        mgrs_grid="20J MK 100 200",
        maps_url="https://maps.google.com"
    )

    # Incursión inicial: no califica de inmediato para reporte
    s1 = manager.evaluate_target(pos)
    assert s1.is_breaching is True
    assert s1.qualifies_for_export is False

    # Simular paso del tiempo > 3s manipulando el timestamp de inicio
    manager._breach_start_timestamps["TRG-DWELL"] = time.monotonic() - 3.5

    s2 = manager.evaluate_target(pos)
    assert s2.is_breaching is True
    assert s2.qualifies_for_export is True
    assert s2.breach_duration_seconds >= 3.0


def test_geofence_semantic_class_filter():
    import time
    settings = SystemSettings(
        BASE_SENSOR_LAT=-31.624510,
        BASE_SENSOR_LON=-60.485120,
        GEOFENCE_RADIUS_METERS=15.0,
        GEOFENCE_MIN_BREACH_SECONDS=3.0,
        CRITICAL_CLASSES=["person", "car", "truck"]
    )
    manager = GeofenceManager(settings)

    pos = TargetGeoPosition(
        target_id="TRG-CHAIR",
        latitude=-31.624510,
        longitude=-60.485120,
        altitude_m=25.0,
        azimuth_deg=0.0,
        distance_ground_m=0.0,
        utm_zone="20J",
        mgrs_grid="20J MK 100 200",
        maps_url="https://maps.google.com"
    )

    # Objeto no crítico que supera 3s en la zona
    manager._breach_start_timestamps["TRG-CHAIR"] = time.monotonic() - 4.0
    status_chair = manager.evaluate_target(pos, class_name="chair")
    assert status_chair.is_breaching is True
    assert status_chair.is_critical_threat is False
    assert status_chair.qualifies_for_export is False

    # Objeto crítico (car) sí califica
    pos_car = pos.model_copy(update={"target_id": "TRG-CAR"})
    manager._breach_start_timestamps["TRG-CAR"] = time.monotonic() - 4.0
    status_car = manager.evaluate_target(pos_car, class_name="car")
    assert status_car.is_breaching is True
    assert status_car.is_critical_threat is True
    assert status_car.qualifies_for_export is True
