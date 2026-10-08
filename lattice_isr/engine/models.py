"""
LATTICE-CORE ISR - Shared Domain Models & Tactical Types
Desacopla estructuras de datos para prevenir importaciones circulares (Clean Architecture).
"""

from typing import List, Tuple
from pydantic import BaseModel, Field


class TargetDetection(BaseModel):
    """Modelo inmutable de detección de objetivo instantáneo."""
    target_id: str = Field(description="Identificador táctico temporal")
    bbox_x: int = Field(description="Coordenada X superior izquierda")
    bbox_y: int = Field(description="Coordenada Y superior izquierda")
    bbox_w: int = Field(description="Ancho del bounding box")
    bbox_h: int = Field(description="Alto del bounding box")
    centroid_x: int = Field(description="Centroide X del punto caliente")
    centroid_y: int = Field(description="Centroide Y del punto caliente")
    area_px: int = Field(description="Superficie del punto caliente en píxeles")
    mean_intensity: float = Field(description="Nivel medio de radiación/brillo (0-255)")
    threat_level: str = Field(description="Clasificación táctica (LOW, MEDIUM, HIGH, CRITICAL)")
    class_name: str = Field(default="target", description="Nombre de clase semántica clasificada (person, car, etc.)")
    confidence: float = Field(default=1.0, description="Nivel de confianza de la detección neuronal (0.0 - 1.0)")


class TrackedTargetState(BaseModel):
    """Estado persistente e inmutable de un objetivo bajo seguimiento continuo."""
    target_id: str
    centroid_x: int
    centroid_y: int
    bbox_x: int
    bbox_y: int
    bbox_w: int
    bbox_h: int
    area_px: int
    mean_intensity: float
    threat_level: str
    class_name: str = Field(default="target", description="Clase de objeto reconocida")
    confidence: float = Field(default=1.0, description="Confianza de inferencia")
    velocity_px_s: float = Field(default=0.0, description="Velocidad escalar en píxeles por segundo")
    heading_deg: float = Field(default=0.0, description="Rumbo cinemático en grados (0-360°)")
    trajectory: List[Tuple[int, int]] = Field(default_factory=list, description="Historial de centroides recientes")
    disappeared_count: int = 0
    first_seen_timestamp: float
    last_seen_timestamp: float


class TargetBehaviorIntent(BaseModel):
    """Clasificación de conducta e intención táctica de un objetivo."""
    target_id: str
    intent: str = Field(description="'LOITERING', 'APPROACHING' o 'TRANSITING'")
    confidence_score: float = Field(description="Nivel de confianza en la clasificación (0.0-1.0)")
    persistence_seconds: float = Field(description="Tiempo acumulado de seguimiento en segundos")
    details: str = Field(description="Explicación analítica del vector de conducta")
