"""
LATTICE-CORE ISR - QA Unit Tests: Target Geocoder
Validación de proyecciones geodésicas, cuadrícula MGRS, zona UTM y enlaces Google Maps.
"""

import pytest
from lattice_isr.config.settings import SystemSettings
from lattice_isr.engine.geolocation_engine import TargetGeocoder


def test_geocoder_center_projection():
    settings = SystemSettings(
        BASE_SENSOR_LAT=-31.624510,
        BASE_SENSOR_LON=-60.485120,
        BASE_SENSOR_ALT_M=25.0,
        CAMERA_HEADING_AZIMUTH_DEG=0.0,  # Apuntando al Norte
        GROUND_DISTANCE_ESTIMATE_M=50.0
    )
    geocoder = TargetGeocoder(settings)

    # Centro óptico (640, 360 en resolución 1280x720)
    geo_pos = geocoder.estimate_target_position(
        target_id="TRG-TEST-001",
        centroid_x=640,
        centroid_y=360,
        frame_width=1280,
        frame_height=720
    )

    assert geo_pos.target_id == "TRG-TEST-001"
    # El objetivo proyectado al norte debe tener latitud ligeramente mayor (más cerca del polo norte o menos negativa)
    assert geo_pos.latitude > settings.BASE_SENSOR_LAT
    assert abs(geo_pos.longitude - settings.BASE_SENSOR_LON) < 0.0001
    assert "https://maps.google.com/?q=" in geo_pos.maps_url
    assert f"{geo_pos.latitude:.4f}"[:7] in geo_pos.maps_url
    assert len(geo_pos.utm_zone) >= 2
    assert len(geo_pos.mgrs_grid) >= 5


def test_geocoder_lateral_offset():
    settings = SystemSettings(
        BASE_SENSOR_LAT=-31.624510,
        BASE_SENSOR_LON=-60.485120,
        CAMERA_HEADING_AZIMUTH_DEG=0.0
    )
    geocoder = TargetGeocoder(settings)

    # Centroide desplazado a la derecha de la pantalla (Este)
    geo_pos = geocoder.estimate_target_position(
        target_id="TRG-TEST-002",
        centroid_x=1200,  # Muy a la derecha
        centroid_y=360,
        frame_width=1280,
        frame_height=720
    )

    # Longitud hacia el Este debe incrementarse
    assert geo_pos.longitude > settings.BASE_SENSOR_LON
    assert geo_pos.azimuth_deg > 0.0


def test_geocoder_fov_coverage_and_sector_inventory():
    from lattice_isr.engine.models import TrackedTargetState
    settings = SystemSettings(
        CAMERA_FOV_HORIZONTAL_DEG=65.0,
        CAMERA_FOV_VERTICAL_DEG=45.0,
        GROUND_DISTANCE_ESTIMATE_M=35.0
    )
    geocoder = TargetGeocoder(settings)

    w_m, h_m, area_m2 = geocoder.calculate_fov_coverage_m2()
    assert w_m > 0.0
    assert h_m > 0.0
    assert area_m2 > 0.0
    assert area_m2 == round(w_m * h_m, 2)

    # Crear lista de objetivos mock
    targets = [
        TrackedTargetState(
            target_id="TRG-001",
            bbox_x=10, bbox_y=10, bbox_w=50, bbox_h=100,
            centroid_x=35, centroid_y=60,
            area_px=5000, threat_level="HIGH",
            class_name="person", confidence=0.92,
            mean_intensity=200.0,
            first_seen_timestamp=1.0,
            last_seen_timestamp=2.0
        ),
        TrackedTargetState(
            target_id="TRG-002",
            bbox_x=100, bbox_y=10, bbox_w=50, bbox_h=100,
            centroid_x=125, centroid_y=60,
            area_px=5000, threat_level="HIGH",
            class_name="person", confidence=0.88,
            mean_intensity=210.0,
            first_seen_timestamp=1.0,
            last_seen_timestamp=2.0
        ),
        TrackedTargetState(
            target_id="TRG-003",
            bbox_x=200, bbox_y=50, bbox_w=60, bbox_h=60,
            centroid_x=230, centroid_y=80,
            area_px=3600, threat_level="MEDIUM",
            class_name="bicycle", confidence=0.85,
            mean_intensity=190.0,
            first_seen_timestamp=1.0,
            last_seen_timestamp=2.0
        )
    ]

    inventory = geocoder.calculate_sector_inventory(targets)
    assert inventory.total_targets == 3
    assert inventory.target_counts["person"] == 2
    assert inventory.target_counts["bicycle"] == 1
    assert "Área encuadrada:" in inventory.density_summary
    assert "2 personas" in inventory.density_summary
    assert "1 bicicleta" in inventory.density_summary
