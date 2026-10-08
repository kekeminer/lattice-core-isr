"""
LATTICE-CORE ISR - Persistent Centroid Target Tracker
Asignación de IDs persistentes, vectores de velocidad relativa, cálculo de rumbo (Heading)
y purga automática de objetivos inactivos para prevenir fugas de memoria.
"""

import math
import time
from collections import deque
from typing import Dict, List, Optional, Tuple
import numpy as np
from pydantic import BaseModel, Field
from loguru import logger

from lattice_isr.config.settings import SystemSettings
from lattice_isr.engine.models import TargetDetection, TrackedTargetState


class TrackerBaseException(Exception):
    """Excepción base del motor de seguimiento de objetivos."""
    pass


class TargetTrackerManager:
    """
    Administrador táctico de seguimiento continuo de centroides.
    Asocia detecciones de contornos térmicos con entidades persistentes,
    calcula la derivada temporal de posición (vectores) y purga objetivos perdidos.
    """

    def __init__(self, settings: SystemSettings):
        self._settings = settings
        self._next_target_numeric_id = 1
        self._tracked_targets: Dict[str, TrackedTargetState] = {}
        self._trajectories: Dict[str, deque] = {}
        self._target_history: Dict[str, TrackedTargetState] = {}

    @property
    def active_targets_count(self) -> int:
        return len(self._tracked_targets)

    def update(
        self,
        raw_detections: List[TargetDetection],
        frame_timestamp: Optional[float] = None
    ) -> List[TrackedTargetState]:
        """
        Actualiza el estado de los objetivos rastreados mediante distancia euclidiana de centroides.
        """
        now = frame_timestamp if frame_timestamp is not None else time.monotonic()

        # Si no hay objetivos rastreados actualmente, registrar todas las detecciones como nuevos
        if len(self._tracked_targets) == 0:
            for det in raw_detections:
                self._register_new_target(det, now)
            return list(self._tracked_targets.values())

        # Si no hay detecciones en este frame, incrementar contador de desaparición en todos
        if len(raw_detections) == 0:
            targets_to_purge = []
            for target_id, target in self._tracked_targets.items():
                target.disappeared_count += 1
                if target.disappeared_count >= self._settings.TRACKER_MAX_DISAPPEARED_FRAMES:
                    targets_to_purge.append(target_id)
            for tid in targets_to_purge:
                self._deregister_target(tid)
            return list(self._tracked_targets.values())

        # Matriz de asociación: Distancia euclidiana entre centroides existentes y nuevas detecciones
        target_ids = list(self._tracked_targets.keys())
        existing_centroids = np.array([
            (self._tracked_targets[tid].centroid_x, self._tracked_targets[tid].centroid_y)
            for tid in target_ids
        ])

        input_centroids = np.array([
            (det.centroid_x, det.centroid_y)
            for det in raw_detections
        ])

        # Distancia euclidiana NxM
        dists = np.linalg.norm(existing_centroids[:, np.newaxis] - input_centroids, axis=2)

        # Emparejamiento voraz por distancia mínima
        rows = dists.min(axis=1).argsort()
        cols = dists.argmin(axis=1)[rows]

        used_rows = set()
        used_cols = set()

        for row, col in zip(rows, cols):
            if row in used_rows or col in used_cols:
                continue

            # Validar umbral de distancia máxima permitida para considerar continuidad
            dist_val = dists[row, col]
            if dist_val > self._settings.TRACKER_MAX_DISTANCE_PX:
                continue

            target_id = target_ids[row]
            detection = raw_detections[col]

            # Actualizar cinemática del objetivo emparejado
            self._update_existing_target(target_id, detection, now)

            used_rows.add(row)
            used_cols.add(col)

        # Tratar filas no emparejadas como objetivos desaparecidos
        unused_rows = set(range(len(existing_centroids))).difference(used_rows)
        for row in unused_rows:
            target_id = target_ids[row]
            self._tracked_targets[target_id].disappeared_count += 1
            if self._tracked_targets[target_id].disappeared_count >= self._settings.TRACKER_MAX_DISAPPEARED_FRAMES:
                self._deregister_target(target_id)

        # Tratar columnas no emparejadas como nuevos objetivos
        unused_cols = set(range(len(input_centroids))).difference(used_cols)
        for col in unused_cols:
            self._register_new_target(raw_detections[col], now)

        return list(self._tracked_targets.values())

    def extrapolate_kinematics(self, frame_timestamp: float) -> List[TrackedTargetState]:
        """
        Interpola y extrapola cinemáticamente las coordenadas de los objetivos rastreados
        entre fotogramas de inferencia (Inference Frame-Skipping a 60 FPS).
        Preserva en pantalla las cajas delimitadoras, clases y etiquetas del último análisis válido.
        """
        for tid, target in self._tracked_targets.items():
            dt = frame_timestamp - target.last_seen_timestamp
            if dt > 0.001 and target.velocity_px_s > 0.5 and target.heading_deg > 0:
                rad = math.radians(target.heading_deg)
                dx = target.velocity_px_s * math.sin(rad) * dt
                dy = -target.velocity_px_s * math.cos(rad) * dt

                target.centroid_x = int(round(target.centroid_x + dx))
                target.centroid_y = int(round(target.centroid_y + dy))
                target.bbox_x = int(round(target.centroid_x - (target.bbox_w / 2.0)))
                target.bbox_y = int(round(target.centroid_y - (target.bbox_h / 2.0)))
                target.last_seen_timestamp = frame_timestamp

                if tid in self._trajectories:
                    self._trajectories[tid].append((target.centroid_x, target.centroid_y))
                    target.trajectory = list(self._trajectories[tid])
            else:
                target.last_seen_timestamp = frame_timestamp

            # Mantener sincronizado el historial persistente para evitar parpadeos
            self._target_history[tid] = target.model_copy()

        return list(self._tracked_targets.values())

    def _register_new_target(self, detection: TargetDetection, timestamp: float) -> None:
        """Registra una nueva entidad táctica asignando un ID único secuencial."""
        tid = f"TRG-{self._next_target_numeric_id:03d}"
        self._next_target_numeric_id += 1

        trajectory = deque(maxlen=self._settings.TRACKER_TRAJECTORY_MAX_POINTS)
        trajectory.append((detection.centroid_x, detection.centroid_y))
        self._trajectories[tid] = trajectory

        new_state = TrackedTargetState(
            target_id=tid,
            centroid_x=detection.centroid_x,
            centroid_y=detection.centroid_y,
            bbox_x=detection.bbox_x,
            bbox_y=detection.bbox_y,
            bbox_w=detection.bbox_w,
            bbox_h=detection.bbox_h,
            area_px=detection.area_px,
            mean_intensity=detection.mean_intensity,
            threat_level=detection.threat_level,
            class_name=getattr(detection, "class_name", "target"),
            confidence=getattr(detection, "confidence", 1.0),
            velocity_px_s=0.0,
            heading_deg=0.0,
            trajectory=[(detection.centroid_x, detection.centroid_y)],
            disappeared_count=0,
            first_seen_timestamp=timestamp,
            last_seen_timestamp=timestamp
        )

        self._tracked_targets[tid] = new_state
        self._target_history[tid] = new_state.model_copy()
        logger.info(f"[TRACKER] Nuevo objetivo táctico fijado: {tid} ({new_state.class_name}) en ({detection.centroid_x}, {detection.centroid_y})")

    def _update_existing_target(
        self,
        target_id: str,
        detection: TargetDetection,
        timestamp: float
    ) -> None:
        """Calcula vectores cinemáticos y actualiza la posición del objetivo."""
        target = self._tracked_targets[target_id]
        dt = timestamp - target.last_seen_timestamp

        dx = detection.centroid_x - target.centroid_x
        dy = detection.centroid_y - target.centroid_y
        dist = math.hypot(dx, dy)

        # Velocidad en píxeles/segundo con filtro
        if dt > 0.001:
            instant_speed = dist / dt
            # Suavizado exponencial de velocidad
            target.velocity_px_s = round(0.7 * instant_speed + 0.3 * target.velocity_px_s, 1)

        # Cálculo de rumbo/heading en grados (0° Norte / Arriba, 90° Este / Derecha)
        if dist > 2.0:
            # En plano de pantalla OpenCV: eje Y es hacia abajo, X hacia la derecha
            angle_rad = math.atan2(dx, -dy)
            heading = (math.degrees(angle_rad) + 360.0) % 360.0
            target.heading_deg = round(heading, 1)

        # Actualizar posición y metadatos
        target.centroid_x = detection.centroid_x
        target.centroid_y = detection.centroid_y
        target.bbox_x = detection.bbox_x
        target.bbox_y = detection.bbox_y
        target.bbox_w = detection.bbox_w
        target.bbox_h = detection.bbox_h
        target.area_px = detection.area_px
        target.mean_intensity = detection.mean_intensity
        target.threat_level = detection.threat_level
        target.class_name = getattr(detection, "class_name", target.class_name)
        target.confidence = getattr(detection, "confidence", target.confidence)
        target.disappeared_count = 0
        target.last_seen_timestamp = timestamp

        # Historial de trayectoria acotado
        self._trajectories[target_id].append((detection.centroid_x, detection.centroid_y))
        target.trajectory = list(self._trajectories[target_id])

        # Actualizar copia en historial persistente
        self._target_history[target_id] = target.model_copy()

    def get_target(self, target_id: str) -> Optional[TrackedTargetState]:
        """Obtiene un objetivo por su ID desde los activos o desde el historial persistente."""
        if target_id in self._tracked_targets:
            return self._tracked_targets[target_id]
        return self._target_history.get(target_id)

    def get_all_known_targets(self) -> List[TrackedTargetState]:
        """
        Retorna la lista de objetivos conocidos: primero los activos y luego los retenidos
        en el historial persistente (sin duplicados) para interacción fluida en panel.
        """
        seen = set()
        result: List[TrackedTargetState] = []
        for t in self._tracked_targets.values():
            result.append(t)
            seen.add(t.target_id)
        for tid, t in self._target_history.items():
            if tid not in seen:
                result.append(t)
                seen.add(tid)
        return result

    def get_target_history(self) -> Dict[str, TrackedTargetState]:
        """Retorna el diccionario de historial persistente de objetivos."""
        return dict(self._target_history)

    def _deregister_target(self, target_id: str) -> None:
        """Elimina de forma segura un objetivo de los activos para liberar tracking."""
        if target_id in self._tracked_targets:
            del self._tracked_targets[target_id]
        if target_id in self._trajectories:
            del self._trajectories[target_id]
        logger.debug(f"[TRACKER] Objetivo {target_id} purgado de tracking activo (retenido en historial).")

    def reset(self) -> None:
        """Reinicia el tracking y libera todas las colecciones."""
        self._tracked_targets.clear()
        self._trajectories.clear()
        self._target_history.clear()
        self._next_target_numeric_id = 1
