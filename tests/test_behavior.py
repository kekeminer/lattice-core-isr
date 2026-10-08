"""
LATTICE-CORE ISR - QA Unit Tests: Behavior Analyzer
Validación de clasificación de intención: LOITERING, APPROACHING, TRANSITING.
"""

import pytest
from lattice_isr.config.settings import SystemSettings
from lattice_isr.engine.target_tracker import TrackedTargetState
from lattice_isr.engine.behavior_analyzer import BehaviorAnalyzer


def test_behavior_loitering():
    settings = SystemSettings(
        BEHAVIOR_LOITER_RADIUS_PX=30.0,
        BEHAVIOR_LOITER_SECONDS_THRESHOLD=2.0
    )
    analyzer = BehaviorAnalyzer(settings)

    # Trayectoria con dispersión mínima en un periodo de 3.0s
    traj = [(200, 200), (202, 201), (199, 202), (201, 198), (200, 200)]
    target = TrackedTargetState(
        target_id="TRG-LOITER",
        centroid_x=200,
        centroid_y=200,
        bbox_x=190,
        bbox_y=190,
        bbox_w=20,
        bbox_h=20,
        area_px=400,
        mean_intensity=230.0,
        threat_level="MEDIUM",
        velocity_px_s=1.5,
        heading_deg=45.0,
        trajectory=traj,
        first_seen_timestamp=10.0,
        last_seen_timestamp=13.5
    )

    result = analyzer.analyze_target(target)
    assert result.intent == "LOITERING"
    assert result.confidence_score >= 0.6


def test_behavior_approaching():
    settings = SystemSettings(
        BEHAVIOR_APPROACHING_MIN_SPEED_PX_S=5.0
    )
    analyzer = BehaviorAnalyzer(settings)

    # Objetivo moviéndose desde la parte superior (Y=100) hacia la base del sensor en la parte inferior (Y=700)
    traj = [(640, 100), (640, 200), (640, 350), (640, 500)]
    target = TrackedTargetState(
        target_id="TRG-APPROACH",
        centroid_x=640,
        centroid_y=500,
        bbox_x=630,
        bbox_y=490,
        bbox_w=20,
        bbox_h=20,
        area_px=500,
        mean_intensity=240.0,
        threat_level="HIGH",
        velocity_px_s=15.0,
        heading_deg=180.0,
        trajectory=traj,
        first_seen_timestamp=10.0,
        last_seen_timestamp=13.0
    )

    result = analyzer.analyze_target(target, frame_width=1280, frame_height=720)
    assert result.intent == "APPROACHING"
    assert result.confidence_score >= 0.7
