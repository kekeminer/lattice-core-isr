"""
LATTICE-CORE ISR - QA Unit Tests: Target Tracker Manager
Validación de asignación de IDs persistentes, cálculo de velocidad/heading y purga por inactividad.
"""

import pytest
from lattice_isr.config.settings import SystemSettings
from lattice_isr.engine.object_detector import TargetDetection
from lattice_isr.engine.target_tracker import TargetTrackerManager


def create_dummy_detection(x: int, y: int, area: int = 300) -> TargetDetection:
    return TargetDetection(
        target_id="RAW-TEMP",
        bbox_x=x - 10,
        bbox_y=y - 10,
        bbox_w=20,
        bbox_h=20,
        centroid_x=x,
        centroid_y=y,
        area_px=area,
        mean_intensity=230.0,
        threat_level="MEDIUM"
    )


def test_tracker_initial_registration():
    settings = SystemSettings()
    tracker = TargetTrackerManager(settings)

    dets = [create_dummy_detection(100, 100), create_dummy_detection(300, 300)]
    tracked = tracker.update(dets, frame_timestamp=1000.0)

    assert len(tracked) == 2
    assert tracked[0].target_id == "TRG-001"
    assert tracked[1].target_id == "TRG-002"
    assert tracker.active_targets_count == 2


def test_tracker_persistent_id_and_motion():
    settings = SystemSettings()
    tracker = TargetTrackerManager(settings)

    # Frame 1 en t = 10.0s
    dets_f1 = [create_dummy_detection(100, 100)]
    tracker.update(dets_f1, frame_timestamp=10.0)

    # Frame 2 en t = 11.0s (El objetivo se mueve hacia la derecha: X+20px, Y constante)
    dets_f2 = [create_dummy_detection(120, 100)]
    tracked_f2 = tracker.update(dets_f2, frame_timestamp=11.0)

    assert len(tracked_f2) == 1
    t = tracked_f2[0]
    assert t.target_id == "TRG-001"  # Mismo ID persistente
    assert t.centroid_x == 120
    assert t.velocity_px_s > 0.0     # Detecta velocidad
    assert abs(t.heading_deg - 90.0) < 5.0  # Hacia la derecha (Este = 90°)
    assert len(t.trajectory) == 2


def test_tracker_purge_inactive_targets():
    settings = SystemSettings(TRACKER_MAX_DISAPPEARED_FRAMES=3)
    tracker = TargetTrackerManager(settings)

    # Frame inicial con objetivo
    tracker.update([create_dummy_detection(100, 100)], frame_timestamp=1.0)
    assert tracker.active_targets_count == 1

    # Frames vacíos consecutivos
    tracker.update([], frame_timestamp=2.0)  # disappeared=1
    tracker.update([], frame_timestamp=3.0)  # disappeared=2
    assert tracker.active_targets_count == 1

    tracker.update([], frame_timestamp=4.0)  # disappeared=3 -> debe purgarse
    assert tracker.active_targets_count == 0
