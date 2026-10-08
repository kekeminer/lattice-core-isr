"""
LATTICE-CORE ISR - Tactical Geolocation & Projection Engine
Calcula la posición estimada en Latitud, Longitud (WGS84), cuadrícula MGRS y UTM
a partir del centro óptico, FOV angular y distancia estimada del sensor Edge.
"""

import math
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field
from loguru import logger

from lattice_isr.config.settings import SystemSettings


class GeolocationBaseException(Exception):
    """Excepción del subsistema de cálculo geoespacial."""
    pass


class TargetGeoPosition(BaseModel):
    """Telemetría geoespacial proyectada de un objetivo táctico."""
    target_id: str
    latitude: float = Field(description="Latitud en grados decimales (WGS84)")
    longitude: float = Field(description="Longitud en grados decimales (WGS84)")
    altitude_m: float = Field(description="Altitud estimada respecto al suelo")
    azimuth_deg: float = Field(description="Azimut respecto al Norte geográfico")
    distance_ground_m: float = Field(description="Distancia proyectada en suelo en metros")
    utm_zone: str = Field(description="Zona UTM proyectada (ej. 20J)")
    mgrs_grid: str = Field(description="Referencia de cuadrícula militar MGRS estimada")
    maps_url: str = Field(description="Enlace directo a Google Maps para navegación")


class SectorInventory(BaseModel):
    """Inventario táctico y análisis de cobertura de terreno en metros cuadrados (m²)."""
    area_m2: float = Field(description="Superficie total proyectada encuadrada en pantalla en m²")
    ground_width_m: float = Field(description="Ancho horizontal de cobertura del terreno en metros")
    ground_height_m: float = Field(description="Alto vertical de cobertura del terreno en metros")
    target_counts: Dict[str, int] = Field(default_factory=dict, description="Conteo de objetivos por clase")
    total_targets: int = Field(default=0, description="Total de objetivos en el sector")
    density_summary: str = Field(description="Ficha descriptiva de densidad para el panel táctico")


class TargetGeocoder:
    """
    Motor de proyección pinhole y trigonometría esférica táctica.
    Mapea el vector (x, y) de píxeles del sensor óptico al elipsoide terrestre WGS84.
    """

    EARTH_RADIUS_METERS = 6378137.0  # Semieje mayor WGS84

    def __init__(self, settings: SystemSettings):
        self._settings = settings
        self._base_lat = settings.BASE_SENSOR_LAT
        self._base_lon = settings.BASE_SENSOR_LON
        self._sensor_alt = settings.BASE_SENSOR_ALT_M
        self._fov_h_rad = math.radians(settings.CAMERA_FOV_HORIZONTAL_DEG)
        self._fov_v_rad = math.radians(settings.CAMERA_FOV_VERTICAL_DEG)
        self._cam_azimuth_deg = settings.CAMERA_HEADING_AZIMUTH_DEG
        self._ground_dist_base = settings.GROUND_DISTANCE_ESTIMATE_M

    def estimate_target_position(
        self,
        target_id: str,
        centroid_x: int,
        centroid_y: int,
        frame_width: int,
        frame_height: int
    ) -> TargetGeoPosition:
        """
        Calcula las coordenadas geográficas proyectadas del objetivo.
        """
        # 1. Centro óptico del plano focal
        center_x = frame_width / 2.0
        center_y = frame_height / 2.0

        # 2. Desviación normalizada (-1.0 a +1.0)
        norm_dx = (centroid_x - center_x) / center_x
        norm_dy = (centroid_y - center_y) / center_y

        # 3. Ángulo relativo según el FOV de la lente
        angle_h_rad = norm_dx * (self._fov_h_rad / 2.0)
        angle_v_rad = norm_dy * (self._fov_v_rad / 2.0)

        # 4. Compensación de distancia al suelo basada en pitch/inclinación de píxel
        # Píxeles más abajo en el frame están más cerca; píxeles arriba están más lejos
        dist_factor = 1.0 - (norm_dy * 0.35)
        ground_distance = max(2.0, self._ground_dist_base * dist_factor)

        # 5. Ángulo de azimut geográfico del objetivo (Cámara heading + desviación horizontal)
        angle_h_deg = math.degrees(angle_h_rad)
        target_azimuth_deg = (self._cam_azimuth_deg + angle_h_deg + 360.0) % 360.0
        target_azimuth_rad = math.radians(target_azimuth_deg)

        # 6. Desplazamiento local en coordenadas cartesianas locales (Norte, Este)
        delta_north = ground_distance * math.cos(target_azimuth_rad)
        delta_east = ground_distance * math.sin(target_azimuth_rad)

        # 7. Proyección geodésica a WGS84 (Aproximación esférica de precisión para táctica local < 5km)
        lat_rad = math.radians(self._base_lat)

        delta_lat_deg = (delta_north / self.EARTH_RADIUS_METERS) * (180.0 / math.pi)
        delta_lon_deg = (delta_east / (self.EARTH_RADIUS_METERS * math.cos(lat_rad))) * (180.0 / math.pi)

        target_lat = round(self._base_lat + delta_lat_deg, 6)
        target_lon = round(self._base_lon + delta_lon_deg, 6)

        # 8. Cálculo de cuadrícula UTM y MGRS
        utm_zone_str, mgrs_str = self._calculate_utm_and_mgrs(target_lat, target_lon)

        # 9. Generar enlace a Google Maps
        maps_link = f"https://maps.google.com/?q={target_lat:.6f},{target_lon:.6f}"

        return TargetGeoPosition(
            target_id=target_id,
            latitude=target_lat,
            longitude=target_lon,
            altitude_m=round(self._sensor_alt, 1),
            azimuth_deg=round(target_azimuth_deg, 1),
            distance_ground_m=round(ground_distance, 1),
            utm_zone=utm_zone_str,
            mgrs_grid=mgrs_str,
            maps_url=maps_link
        )

    @staticmethod
    def _calculate_utm_and_mgrs(lat: float, lon: float) -> Tuple[str, str]:
        """
        Transforma latitud y longitud a Zona UTM y cuadrícula estándar militar MGRS.
        """
        # Zona UTM (1-60)
        zone_number = int((lon + 180) / 6) + 1

        # Letra de latitud UTM (C a X, excluyendo I y O)
        letters = "CDEFGHJKLMNPQRSTUVWX"
        lat_index = int((lat + 80) / 8)
        lat_index = max(0, min(lat_index, len(letters) - 1))
        zone_letter = letters[lat_index]

        zone_str = f"{zone_number:02d}{zone_letter}"

        # Cálculo aproximado de coordenadas UTM métricas (Easting, Northing)
        # Fórmulas de proyección transversa simplificada para uso táctico
        lat_rad = math.radians(lat)
        lon_rad = math.radians(lon)
        central_lon_rad = math.radians((zone_number - 1) * 6 - 180 + 3)

        delta_lambda = lon_rad - central_lon_rad
        easting = 500000 + (6378137.0 * delta_lambda * math.cos(lat_rad))
        northing = (10000000 if lat < 0 else 0) + (6378137.0 * lat_rad)

        easting_100k = int((easting % 100000) / 100)
        northing_100k = int((northing % 100000) / 100)

        # Construcción de designación MGRS (Zona + Cuadrícula + Coordenadas Este/Norte)
        col_letters = "ABCDEFGHJKLMNPQRSTUVWXYZ"
        row_letters = "ABCDEFGHJKLMNPQRSTUV"

        col_char = col_letters[int(easting / 100000) % len(col_letters)]
        row_char = row_letters[int(northing / 100000) % len(row_letters)]

        mgrs_formatted = f"{zone_str} {col_char}{row_char} {easting_100k:03d} {northing_100k:03d}"

        return zone_str, mgrs_formatted

    def calculate_fov_coverage_m2(self, ground_distance: Optional[float] = None) -> Tuple[float, float, float]:
        """
        Calcula la cobertura del terreno (ancho m, alto m, área m²) del sector encuadrado
        a partir del FOV angular y la distancia de la cámara al suelo.
        """
        dist = ground_distance if ground_distance is not None else self._ground_dist_base
        dist = max(0.5, float(dist))
        w_m = round(2.0 * dist * math.tan(self._fov_h_rad / 2.0), 2)
        h_m = round(2.0 * dist * math.tan(self._fov_v_rad / 2.0), 2)
        area_m2 = round(w_m * h_m, 2)
        return w_m, h_m, area_m2

    def calculate_sector_inventory(
        self,
        tracked_targets: List[Any],
        ground_distance: Optional[float] = None
    ) -> SectorInventory:
        """
        Genera la ficha de inventario táctico y densidad del sector encuadrado.
        Ejemplo: 'Área encuadrada: 42.5 m² | Densidad: 2 personas, 1 bicicleta'
        """
        w_m, h_m, area_m2 = self.calculate_fov_coverage_m2(ground_distance)

        class_counts: Dict[str, int] = {}
        for trg in tracked_targets:
            cls_name = getattr(trg, "class_name", "target").lower()
            class_counts[cls_name] = class_counts.get(cls_name, 0) + 1

        plural_map = {
            "person": ("persona", "personas"),
            "bicycle": ("bicicleta", "bicicletas"),
            "car": ("auto", "autos"),
            "truck": ("camión", "camiones"),
            "bus": ("autobús", "autobuses"),
            "motorcycle": ("motocicleta", "motocicletas"),
            "backpack": ("mochila", "mochilas"),
            "handbag": ("bolso", "bolsos"),
            "tv": ("tv", "tv"),
            "laptop": ("laptop", "laptops"),
            "chair": ("silla", "sillas"),
        }

        density_parts = []
        for cls_name, count in sorted(class_counts.items(), key=lambda item: item[1], reverse=True):
            sg, pl = plural_map.get(cls_name, (cls_name, f"{cls_name}s"))
            lbl = pl if count > 1 else sg
            density_parts.append(f"{count} {lbl}")

        if density_parts:
            density_str = ", ".join(density_parts)
        else:
            density_str = "0 objetivos detectados"

        summary = f"Área encuadrada: {area_m2:.1f} m² | Densidad: {density_str}"

        return SectorInventory(
            area_m2=area_m2,
            ground_width_m=w_m,
            ground_height_m=h_m,
            target_counts=class_counts,
            total_targets=len(tracked_targets),
            density_summary=summary
        )
