"""
Pruebas unitarias de la canalización de visión térmica y detección de hotspots.
"""

import numpy as np
import pytest
from lattice_isr.config.settings import SystemSettings, ThermalColormapEnum
from lattice_isr.engine.thermal_processor import ThermalProcessor
from lattice_isr.engine.object_detector import ThermalObjectDetector


def test_thermal_processor_valid_frame():
    processor = ThermalProcessor(colormap=ThermalColormapEnum.INFERNO)
    dummy_bgr = np.zeros((480, 640, 3), dtype=np.uint8)
    dummy_bgr[200:250, 200:250] = (255, 255, 255)  # Punto brillante/caliente

    thermal_colored, gray = processor.process_frame(dummy_bgr)
    assert thermal_colored.shape == (480, 640, 3)
    assert gray.shape == (480, 640)


def test_object_detector_hotspot_detection():
    settings = SystemSettings(
        HOTSPOT_MIN_AREA=50,
        HOTSPOT_BRIGHTNESS_THRESHOLD=200,
        THREAT_TRIGGER_AREA=500
    )
    detector = ThermalObjectDetector(settings)

    # Frame gris con una firma caliente sintética de 30x30 = 900 px
    gray_frame = np.zeros((480, 640), dtype=np.uint8)
    gray_frame[100:130, 100:130] = 255

    targets = detector.detect_hotspots(gray_frame, "20261007-0001")
    assert len(targets) >= 1
    t = targets[0]
    assert t.area_px >= 50
    assert t.threat_level in ("MEDIUM", "HIGH", "CRITICAL")


def test_object_detector_top_n_filtering():
    settings = SystemSettings(
        HOTSPOT_MIN_AREA=20,
        HOTSPOT_BRIGHTNESS_THRESHOLD=150,
        MAX_TARGETS_PER_FRAME=5
    )
    detector = ThermalObjectDetector(settings)

    # Crear frame con 8 fuentes de luz distintas
    gray_frame = np.zeros((480, 640), dtype=np.uint8)
    for i in range(8):
        x = 50 + (i * 60)
        size = 10 + i * 2  # Tamaños crecientes
        gray_frame[100:100+size, x:x+size] = 255

    targets = detector.detect_hotspots(gray_frame, "20261007-0002")
    # Debe limitar estrictamente a los 5 más prominentes
    assert len(targets) <= 5


def test_object_detector_hybrid_detect_objects():
    settings = SystemSettings(
        YOLO_ENABLED=False,  # Probar fallback directo
        HOTSPOT_MIN_AREA=30,
        HOTSPOT_BRIGHTNESS_THRESHOLD=180
    )
    detector = ThermalObjectDetector(settings)

    dummy_rgb = np.zeros((360, 640, 3), dtype=np.uint8)
    dummy_rgb[50:100, 50:100] = (255, 255, 255)

    targets = detector.detect_objects(frame_rgb=dummy_rgb, base_timestamp_id="20261007-0003")
    assert len(targets) >= 1
    assert targets[0].area_px >= 30
    assert hasattr(targets[0], "class_name")
    assert hasattr(targets[0], "confidence")


def test_extract_dominant_color_hsv():
    from lattice_isr.engine.object_detector import extract_dominant_color_hsv

    # 1. ROI predominantemente amarillo (BGR: 0, 255, 255)
    yellow_roi = np.zeros((60, 40, 3), dtype=np.uint8)
    yellow_roi[:, :] = (0, 255, 255)
    result_person = extract_dominant_color_hsv(yellow_roi, class_name="person")
    assert "Amarillo" in result_person
    assert "Vestimenta" in result_person

    # 2. ROI predominantemente oscuro / negro (BGR: 10, 10, 10)
    dark_roi = np.zeros((50, 50, 3), dtype=np.uint8)
    dark_roi[:, :] = (10, 10, 10)
    result_vehicle = extract_dominant_color_hsv(dark_roi, class_name="car")
    assert "Oscuro" in result_vehicle
    assert "Carrocería" in result_vehicle

    # 3. ROI inválido
    assert extract_dominant_color_hsv(np.zeros((2, 2, 3), dtype=np.uint8)) == "Indeterminado"


def test_async_inference_pipeline():
    import time
    settings = SystemSettings(
        YOLO_ENABLED=False,  # Probar pipeline asíncrono con fallback
        HOTSPOT_MIN_AREA=20,
        HOTSPOT_BRIGHTNESS_THRESHOLD=150
    )
    detector = ThermalObjectDetector(settings)
    detector.start_async_worker()

    try:
        # Generar frame sintético
        frame = np.zeros((384, 640, 3), dtype=np.uint8)
        frame[50:100, 50:100] = 255
        gray = frame[:, :, 0]

        # Enviar frame en modo asíncrono
        dets_initial = detector.detect_objects(frame, "ASYNC-001", gray_fallback=gray, async_mode=True)
        assert isinstance(dets_initial, list)

        # Dar breve momento al worker para procesar
        time.sleep(0.15)
        latest = detector.get_latest_detections()
        assert len(latest) >= 1
        assert latest[0].area_px >= 20

    finally:
        detector.stop_async_worker()


def test_tactical_hud_with_side_inspector_panel():
    from lattice_isr.engine.models import TrackedTargetState
    from lattice_isr.engine.geolocation_engine import SectorInventory
    settings = SystemSettings(YOLO_ENABLED=False)
    detector = ThermalObjectDetector(settings)

    canvas = np.zeros((720, 1280, 3), dtype=np.uint8)
    dummy_target = TrackedTargetState(
        target_id="TRG-001",
        bbox_x=100, bbox_y=100, bbox_w=60, bbox_h=120,
        centroid_x=130, centroid_y=160,
        area_px=7200, threat_level="HIGH",
        class_name="person", confidence=0.94,
        velocity_px_s=14.0, heading_deg=45.0,
        mean_intensity=220.0,
        first_seen_timestamp=10.0,
        last_seen_timestamp=11.0
    )

    inventory = SectorInventory(
        area_m2=42.5,
        ground_width_m=7.5,
        ground_height_m=5.7,
        target_counts={"person": 1},
        total_targets=1,
        density_summary="Área encuadrada: 42.5 m² | Densidad: 1 persona"
    )

    hud_rendered = detector.render_tactical_hud(
        canvas=canvas,
        tracked_targets=[dummy_target],
        geo_positions={},
        geofence_statuses={},
        behaviors={},
        fps=60.0,
        source_name="TEST_DEVICE",
        thermal_mode_name="WHITE_HOT",
        sector_inventory=inventory,
        attach_side_panel=True
    )

    # El HUD con panel lateral debe medir 1280 + 300 = 1580 px de ancho
    assert hud_rendered.shape[0] == 720
    assert hud_rendered.shape[1] == 1280 + 300
    assert hud_rendered.shape[2] == 3
