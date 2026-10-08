"""
LATTICE-CORE ISR - Rolling Video Clip Evidence Recorder
Buffer circular en RAM para los últimos N segundos de video.
Ante un evento táctico crítico (PERIMETER_BREACH), guarda un clip MP4 (5s) en obsidian_vault/evidence/.
"""

import time
from collections import deque
from pathlib import Path
from typing import Optional, Tuple
import cv2
import numpy as np
from loguru import logger

from lattice_isr.config.settings import SystemSettings
from lattice_isr.core.security import StreamSecurityValidator


class VideoClipRecorder:
    """
    Grabador de evidencia forense mediante buffer circular continuo.
    Garantiza bajo consumo de RAM manteniendo un número acotado de frames (3s pre-evento).
    """

    def __init__(self, settings: SystemSettings):
        self._settings = settings
        self._fps_est = 30.0
        self._pre_buffer_seconds = getattr(settings, "VIDEO_CLIP_PRE_BUFFER_SECONDS", 3.0)
        self._post_duration_seconds = getattr(settings, "VIDEO_CLIP_POST_DURATION_SECONDS", 2.0)
        self._vault_evidence_dir = settings.VAULT_PATH.resolve() / "evidence"

        # Capacidad del buffer circular: aprox 3 segundos a 30 FPS
        self._max_buffer_frames = int(self._pre_buffer_seconds * 30)
        self._rolling_buffer = deque(maxlen=self._max_buffer_frames)

        self._active_recordings = {}

    def push_frame(self, frame: np.ndarray, fps: float = 30.0) -> None:
        """Almacena el frame actual en el buffer circular de baja huella."""
        if frame is None or frame.size == 0:
            return
        if fps > 5.0:
            self._fps_est = fps

        now = time.monotonic()
        # Para optimizar memoria y codificación, guardar copia ligera
        self._rolling_buffer.append((now, frame.copy()))

    def record_evidence_clip(
        self,
        target_id: str,
        additional_frames: Optional[list] = None
    ) -> Optional[Path]:
        """
        Exporta los fotogramas del buffer previo (3s) más fotogramas recientes a un clip MP4.
        Devuelve la ruta absoluta del archivo generado dentro de obsidian_vault/evidence/.
        """
        if not self._rolling_buffer:
            logger.warning("[RECORDER] Buffer de video vacío; no se puede generar clip.")
            return None

        clean_id = StreamSecurityValidator.sanitize_filename(target_id)
        timestamp_str = time.strftime("%Y%m%d_%H%M%S")
        filename = f"clip_{clean_id}_{timestamp_str}.mp4"
        out_path = self._vault_evidence_dir / filename

        frames_to_write = [f[1] for f in self._rolling_buffer]
        if additional_frames:
            frames_to_write.extend(additional_frames)

        if not frames_to_write:
            return None

        h, w = frames_to_write[0].shape[:2]
        fps_out = max(15.0, min(60.0, self._fps_est))

        try:
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(str(out_path), fourcc, fps_out, (w, h))

            for frame in frames_to_write:
                # Asegurar dimensiones homogéneas
                if frame.shape[:2] != (h, w):
                    f_res = cv2.resize(frame, (w, h))
                else:
                    f_res = frame
                writer.write(f_res)

            writer.release()
            logger.info(f"[RECORDER] Clip de evidencia guardado: {out_path.name} ({len(frames_to_write)} frames)")
            return out_path
        except Exception as err:
            logger.error(f"[RECORDER-ERR] Fallo al codificar clip de video forense: {err}")
            return None
