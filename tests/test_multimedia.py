"""
LATTICE-CORE ISR - QA Unit Tests: Audio Alerts & Evidence Video Recorder
Validación de síntesis de voz con cooldown y buffer circular de video.
"""

import time
import numpy as np
import pytest
from pathlib import Path
from lattice_isr.config.settings import SystemSettings
from lattice_isr.utils.audio_alert import AudioAlertManager
from lattice_isr.storage.video_recorder import VideoClipRecorder


def test_audio_alert_cooldown():
    settings = SystemSettings(
        AUDIO_ALERTS_ENABLED=True,
        AUDIO_COOLDOWN_SECONDS=2.0
    )
    audio = AudioAlertManager(settings)

    # Primer disparo debe ser aceptado
    triggered1 = audio.trigger_perimeter_alert(class_name="car", target_id="TRG-001")
    assert triggered1 is True

    # Segundo disparo inmediato debe ser bloqueado por cooldown
    triggered2 = audio.trigger_perimeter_alert(class_name="car", target_id="TRG-001")
    assert triggered2 is False

    audio.close()


def test_video_clip_recorder_buffer_and_export(tmp_path: Path):
    vault_dir = tmp_path / "obsidian_vault"
    evidence_dir = vault_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    settings = SystemSettings(
        VAULT_PATH=vault_dir,
        VIDEO_CLIP_PRE_BUFFER_SECONDS=2.0,
        VIDEO_CLIP_POST_DURATION_SECONDS=1.0
    )
    recorder = VideoClipRecorder(settings)

    # Inyectar 10 frames dummy de 640x360
    for i in range(10):
        dummy = np.zeros((360, 640, 3), dtype=np.uint8)
        dummy[100:150, 100:150] = (i * 20, 255, 0)
        recorder.push_frame(dummy, fps=30.0)

    # Exportar clip
    clip_path = recorder.record_evidence_clip(target_id="TRG-EVIDENCE-TEST")
    assert clip_path is not None
    assert clip_path.exists()
    assert clip_path.suffix == ".mp4"
    assert clip_path.stat().st_size > 0
