"""
LATTICE-CORE ISR - Tactical Target Behavior & Intent Analyzer
Clasificación cinemática y probabilística de conducta: LOITERING, APPROACHING, TRANSITING.
"""

import math
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from loguru import logger

from lattice_isr.config.settings import SystemSettings
from lattice_isr.engine.models import TrackedTargetState, TargetBehaviorIntent
from lattice_isr.engine.geolocation_engine import TargetGeoPosition


class BehaviorAnalysisError(Exception):
    """Excepción del subsistema de análisis de intenciones."""
    pass


class BehaviorAnalyzer:
    """
    Analizador de intenciones basado en patrones cinemáticos y geodésicos:
    - LOITERING: Merodeo en una ventana de dispersión estrecha durante más de N segundos.
    - APPROACHING: Movimiento dirigido con vector de velocidad hacia la estación/sensor base.
    - TRANSITING: Trayectoria predominantemente lineal sin aproximación hostil.
    """

    def __init__(self, settings: SystemSettings):
        self._settings = settings
        self._loiter_radius_px = settings.BEHAVIOR_LOITER_RADIUS_PX
        self._loiter_sec_threshold = settings.BEHAVIOR_LOITER_SECONDS_THRESHOLD
        self._approaching_min_speed = settings.BEHAVIOR_APPROACHING_MIN_SPEED_PX_S

    def analyze_target(
        self,
        target: TrackedTargetState,
        geo_pos: Optional[TargetGeoPosition] = None,
        frame_width: int = 1280,
        frame_height: int = 720
    ) -> TargetBehaviorIntent:
        """
        Clasifica la conducta de un objetivo individual.
        """
        duration = max(0.1, target.last_seen_timestamp - target.first_seen_timestamp)
        trajectory = target.trajectory

        # Si recién inicia la observación
        if len(trajectory) < 3 or duration < 1.0:
            return TargetBehaviorIntent(
                target_id=target.target_id,
                intent="TRANSITING",
                confidence_score=0.5,
                persistence_seconds=round(duration, 1),
                details="Observación preliminar insuficiente"
            )

        # 1. Evaluación de Merodeo (LOITERING)
        # Calcula la dispersión espacial máxima dentro de la trayectoria
        xs = [p[0] for p in trajectory]
        ys = [p[1] for p in trajectory]
        max_span = math.hypot(max(xs) - min(xs), max(ys) - min(ys))

        if duration >= self._loiter_sec_threshold and max_span <= self._loiter_radius_px:
            conf = min(0.95, 0.6 + (duration / 10.0))
            return TargetBehaviorIntent(
                target_id=target.target_id,
                intent="LOITERING",
                confidence_score=round(conf, 2),
                persistence_seconds=round(duration, 1),
                details=f"Permanencia estática: dispersión {max_span:.1f}px en {duration:.1f}s"
            )

        # 2. Evaluación de Aproximación (APPROACHING)
        # En coordenadas de pantalla o geodésicas:
        # El sensor está en la base (en pantalla, la parte inferior representa proximidad al sensor)
        # O si el vector de movimiento tiene dirección hacia el centro óptico / base
        center_x = frame_width / 2.0
        center_y = frame_height  # Base del sensor en plano de tierra

        # Vector hacia el sensor
        dx_to_sensor = center_x - target.centroid_x
        dy_to_sensor = center_y - target.centroid_y
        dist_to_sensor = math.hypot(dx_to_sensor, dy_to_sensor)

        # Vector de movimiento actual del objetivo
        if len(trajectory) >= 4 and target.velocity_px_s >= self._approaching_min_speed:
            p_old = trajectory[0]
            p_now = trajectory[-1]
            move_dx = p_now[0] - p_old[0]
            move_dy = p_now[1] - p_old[1]
            move_len = math.hypot(move_dx, move_dy)

            if move_len > 5.0 and dist_to_sensor > 5.0:
                # Producto escalar normalizado (coseno del ángulo entre movimiento y vector hacia la base)
                dot = (move_dx * dx_to_sensor + move_dy * dy_to_sensor) / (move_len * dist_to_sensor)

                # Si el ángulo es agudo (coseno > 0.5 -> ángulo < 60°), se dirige hacia el sensor
                if dot > 0.45:
                    conf = min(0.98, 0.7 + (dot * 0.25))
                    return TargetBehaviorIntent(
                        target_id=target.target_id,
                        intent="APPROACHING",
                        confidence_score=round(conf, 2),
                        persistence_seconds=round(duration, 1),
                        details=f"Vector de avance hacia la base a {target.velocity_px_s:.1f}px/s (cos: {dot:.2f})"
                    )

        # 3. Clasificación por defecto: Desplazamiento lineal (TRANSITING)
        return TargetBehaviorIntent(
            target_id=target.target_id,
            intent="TRANSITING",
            confidence_score=0.75,
            persistence_seconds=round(duration, 1),
            details="Desplazamiento regular fuera de vectores críticos"
        )

    def analyze_batch(
        self,
        targets: List[TrackedTargetState],
        geo_positions: Optional[Dict[str, TargetGeoPosition]] = None,
        frame_width: int = 1280,
        frame_height: int = 720
    ) -> Dict[str, TargetBehaviorIntent]:
        """Clasifica un lote de objetivos en tiempo real."""
        results: Dict[str, TargetBehaviorIntent] = {}
        for trg in targets:
            g = geo_positions.get(trg.target_id) if geo_positions else None
            results[trg.target_id] = self.analyze_target(trg, g, frame_width, frame_height)
        return results
