"""
LATTICE-CORE ISR - QA Unit Tests: Embedded SQLite Database Manager
Validación de persistencia asíncrona por lotes y consultas de After Action Review.
"""

import time
from pathlib import Path
import pytest
from lattice_isr.config.settings import SystemSettings
from lattice_isr.storage.db_manager import EmbeddedDatabaseManager, TelemetryRecord


@pytest.fixture
def temp_db(tmp_path: Path):
    db_file = tmp_path / "test_telemetry.db"
    settings = SystemSettings(DB_PATH=db_file)
    manager = EmbeddedDatabaseManager(settings)
    yield manager
    manager.close()


def test_db_record_and_summary(temp_db: EmbeddedDatabaseManager):
    record1 = TelemetryRecord(
        timestamp=time.time(),
        iso_time="2026-10-07T01:00:00",
        target_id="TRG-TEST-001",
        latitude=-31.624510,
        longitude=-60.485120,
        altitude_m=25.0,
        heading_deg=180.0,
        velocity_px_s=12.5,
        area_px=600,
        threat_level="HIGH",
        geofence_status="PERIMETER_BREACH",
        behavior_intent="APPROACHING",
        mgrs_grid="20J MK 485 624"
    )

    record2 = TelemetryRecord(
        timestamp=time.time() + 1.0,
        iso_time="2026-10-07T01:00:01",
        target_id="TRG-TEST-002",
        latitude=-31.624100,
        longitude=-60.485120,
        altitude_m=25.0,
        heading_deg=90.0,
        velocity_px_s=4.0,
        area_px=280,
        threat_level="LOW",
        geofence_status="SAFE",
        behavior_intent="LOITERING",
        mgrs_grid="20J MK 485 624"
    )

    temp_db.record_event_async(record1)
    temp_db.record_event_async(record2)

    # Volcado determinista para verificación de resumen
    temp_db.flush()

    summary = temp_db.query_mission_summary()
    assert summary["total_telemetry_records"] >= 2
    assert summary["distinct_targets_tracked"] >= 2
    assert summary["perimeter_breaches_logged"] >= 1
    assert "APPROACHING" in summary["intent_distribution"]
    assert "LOITERING" in summary["intent_distribution"]


def test_db_target_history_query(temp_db: EmbeddedDatabaseManager):
    for i in range(5):
        rec = TelemetryRecord(
            timestamp=time.time() + i,
            iso_time=f"2026-10-07T01:00:0{i}",
            target_id="TRG-TRACK-77",
            latitude=-31.624510 + (i * 0.00001),
            longitude=-60.485120,
            altitude_m=25.0,
            heading_deg=0.0,
            velocity_px_s=10.0,
            area_px=400,
            threat_level="MEDIUM",
            geofence_status="SAFE",
            behavior_intent="TRANSITING",
            mgrs_grid="20J MK 485 624"
        )
        temp_db.record_event_async(rec)

    time.sleep(1.2)

    history = temp_db.query_target_history("TRG-TRACK-77")
    assert len(history) == 5
    assert history[0]["behavior_intent"] == "TRANSITING"
