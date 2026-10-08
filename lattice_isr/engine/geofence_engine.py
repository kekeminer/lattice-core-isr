"""
LATTICE-CORE ISR - Tactical Geofence & Perimeter Defense Engine
Evaluación de violaciones de perímetro (PERIMETER_BREACH) mediante cálculo geodésico Haversine.
"""

import math
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from loguru import logger

from lattice_isr.config.settings import SystemSettings
from lattice_isr.engine.geolocation_engine import TargetGeoPosition


class GeofenceBaseException(Exception):
    """Excepción del subsistema de geofencing."""
    pass


class TargetGeofenceStatus(BaseModel):
    """Estado de evaluación de perímetro de un objetivo."""
    target_id: str
    status: str = Field(description="'PERIMETER_BREACH' o 'SAFE'")
    distance_to_base_m: float = Field(description="Distancia geodésica al nodo base en metros")
    is_breaching: bool = Field(description="True si violó la zona de exclusión")
    is_critical_threat: bool = Field(default=True, description="True si la clase semántica está en la lista de amenazas críticas")
    breach_duration_seconds: float = Field(default=0.0, description="Segundos continuos dentro del perímetro de exclusión")
    qualifies_for_export: bool = Field(default=False, description="True si supera el umbral continuo requerido y es amenaza crítica")


class GeofenceManager:
    """
    Administrador de perímetros tácticos y zonas de exclusión con filtro semántico de clases críticas.
    Evalúa la proximidad de los objetivos rastreados respecto a la zona protegida.
    """

    EARTH_RADIUS_METERS = 6378137.0

    def __init__(self, settings: SystemSettings):
        self._settings = settings
        self._base_lat = settings.BASE_SENSOR_LAT
        self._base_lon = settings.BASE_SENSOR_LON
        self._radius_limit_m = settings.GEOFENCE_RADIUS_METERS
        self._throttle_seconds = getattr(settings, "LOG_ALERT_THROTTLE_SECONDS", 2.0)
        self._min_breach_seconds = getattr(settings, "GEOFENCE_MIN_BREACH_SECONDS", 3.0)
        self._critical_classes = set(getattr(settings, "CRITICAL_CLASSES", ["person", "car", "truck", "motorcycle", "bicycle"]))
        self._last_alert_timestamps: Dict[str, float] = {}
        self._breach_start_timestamps: Dict[str, float] = {}

    def evaluate_target(self, geo_pos: TargetGeoPosition, class_name: str = "target") -> TargetGeofenceStatus:
        """
        Calcula la distancia geodésica exacta desde el objetivo hasta la base,
        aplica el filtro semántico de clases críticas y determina si califica para alerta y persistencia.
        """
        import time
        now = time.monotonic()

        dist_m = self._calculate_haversine_distance(
            self._base_lat,
            self._base_lon,
            geo_pos.latitude,
            geo_pos.longitude
        )

        is_breach = dist_m <= self._radius_limit_m
        status_str = "PERIMETER_BREACH" if is_breach else "SAFE"
        breach_duration = 0.0
        qualifies_export = False
        is_critical = (class_name.lower() in self._critical_classes) or (class_name.lower() == "target")

        if is_breach:
            if geo_pos.target_id not in self._breach_start_timestamps:
                self._breach_start_timestamps[geo_pos.target_id] = now
            breach_duration = now - self._breach_start_timestamps[geo_pos.target_id]

            if breach_duration >= self._min_breach_seconds and is_critical:
                qualifies_export = True

            last_logged = self._last_alert_timestamps.get(geo_pos.target_id, 0.0)
            if (now - last_logged) >= self._throttle_seconds and is_critical:
                self._last_alert_timestamps[geo_pos.target_id] = now
                logger.warning(
                    f"[GEOFENCE-ALERT] ¡Invasión de perímetro detectada! Objetivo {geo_pos.target_id} [{class_name}] "
                    f"a {dist_m:.1f}m de la base (Límite: {self._radius_limit_m}m, Duración: {breach_duration:.1f}s)"
                )
        else:
            self._breach_start_timestamps.pop(geo_pos.target_id, None)

        return TargetGeofenceStatus(
            target_id=geo_pos.target_id,
            status=status_str,
            distance_to_base_m=round(dist_m, 1),
            is_breaching=is_breach,
            is_critical_threat=is_critical,
            breach_duration_seconds=round(breach_duration, 2),
            qualifies_for_export=qualifies_export
        )

    def evaluate_batch(
        self,
        geo_positions: Dict[str, TargetGeoPosition],
        tracked_targets: Optional[List[Any]] = None
    ) -> Dict[str, TargetGeofenceStatus]:
        """Evalúa un conjunto de objetivos simultáneamente con sus clases semánticas asociadas."""
        class_map = {}
        if tracked_targets:
            for t in tracked_targets:
                class_map[t.target_id] = getattr(t, "class_name", "target")

        results: Dict[str, TargetGeofenceStatus] = {}
        for target_id, geo_pos in geo_positions.items():
            cls_name = class_map.get(target_id, "target")
            results[target_id] = self.evaluate_target(geo_pos, class_name=cls_name)
        return results

    @classmethod
    def _calculate_haversine_distance(
        cls,
        lat1: float,
        lon1: float,
        lat2: float,
        lon2: float
    ) -> float:
        """Fórmula geodésica de Haversine para distancia en metros sobre el elipsoide WGS84."""
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = (
            math.sin(delta_phi / 2.0) ** 2
            + math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2)
        )
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

        return cls.EARTH_RADIUS_METERS * c
