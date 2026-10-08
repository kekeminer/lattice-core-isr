"""
LATTICE-CORE ISR - Security & Operational Configuration
Valida variables de entorno y parámetros tácticos usando Pydantic v2.
"""

from enum import Enum
from pathlib import Path
from typing import List, Literal
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ThermalPaletteEnum(str, Enum):
    WHITE_HOT = "WHITE_HOT"
    BLACK_HOT = "BLACK_HOT"
    BONE = "BONE"
    INFERNO = "INFERNO"
    JET = "JET"


# Alias de compatibilidad retroactiva
ThermalColormapEnum = ThermalPaletteEnum


class SystemSettings(BaseSettings):
    """
    Configuración global con tipado estricto y validaciones de rango.
    Garantiza robustez antes de inicializar buffers de video, sockets y modelos de proyección.
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="LATTICE_",
        extra="ignore"
    )

    # Ingesta de Video Edge
    STREAM_URL: str = Field(
        default="http://192.168.1.50:8080/video",
        description="URL del streaming IP Webcam / RTSP / HTTP"
    )
    STREAM_TIMEOUT_SECONDS: float = Field(
        default=5.0,
        ge=1.0,
        le=30.0,
        description="Tiempo límite de inactividad de frames antes de forzar reconexión"
    )
    RECONNECT_INITIAL_DELAY: float = Field(default=1.0, ge=0.1, le=10.0)
    RECONNECT_MAX_DELAY: float = Field(default=30.0, ge=5.0, le=120.0)
    RECONNECT_BACKOFF_FACTOR: float = Field(default=2.0, ge=1.1, le=5.0)

    # Memory Optimization (< 100 MB RAM Hard Boundary - Drop Oldest FIFO)
    FRAME_BUFFER_SIZE: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Capacidad de cola circular FIFO para prevenir consumo desbordado de memoria"
    )
    FRAME_WIDTH: int = Field(default=1280, ge=320, le=3840)
    FRAME_HEIGHT: int = Field(default=720, ge=240, le=2160)
    INFERENCE_WIDTH: int = Field(default=640, ge=320, le=1920, description="Ancho de frame para inferencia de visión a 60 FPS")
    INFERENCE_HEIGHT: int = Field(default=384, ge=192, le=1080, description="Alto de frame para inferencia (múltiplo de stride 32)")

    # Motor de Detección e Inferencia Neuronal (YOLOv8 & Respaldo Térmico)
    YOLO_ENABLED: bool = Field(default=True, description="Habilitar inferencia por red neuronal YOLOv8")
    YOLO_MODEL_NAME: str = Field(default="yolov8n.pt", description="Modelo YOLOv8 preentrenado (yolov8n.pt, yolov8s.pt o export ONNX)")
    YOLO_CONFIDENCE_THRESHOLD: float = Field(default=0.40, ge=0.05, le=0.99, description="Umbral mínimo de confianza de clasificación")
    YOLO_TARGET_CLASSES: List[str] = Field(
        default=["person", "car", "truck", "bus", "motorcycle", "bicycle", "backpack", "handbag", "tv", "laptop", "chair"],
        description="Clases tácticas a detectar e identificar por la red neuronal"
    )

    # Motor Térmico & Reconocimiento
    THERMAL_PALETTE: ThermalPaletteEnum = Field(default=ThermalPaletteEnum.WHITE_HOT)
    HOTSPOT_MIN_AREA: int = Field(
        default=450,
        ge=10,
        le=50000,
        description="Área mínima en píxeles para filtrar ruido y parpadeo de pantallas de TV"
    )
    HOTSPOT_BRIGHTNESS_THRESHOLD: int = Field(
        default=215,
        ge=100,
        le=254,
        description="Umbral de luminancia/intensidad (0-255) para aislar regiones críticas"
    )
    MAX_TARGETS_PER_FRAME: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Límite estricto de los N objetivos más prominentes por cuadro para evitar proliferación de IDs"
    )
    THREAT_TRIGGER_AREA: int = Field(
        default=1200,
        ge=100,
        le=100000,
        description="Umbral de área en px para clasificar la amenaza como HIGH"
    )

    # Motor de Seguimiento (Tracker & Persistence)
    TRACKER_MAX_DISAPPEARED_FRAMES: int = Field(
        default=5,
        ge=1,
        le=120,
        description="Frames consecutivos sin detección antes de purgar un objetivo (Purga rápida para <80MB RAM)"
    )
    LOG_ALERT_THROTTLE_SECONDS: float = Field(
        default=2.0,
        ge=0.1,
        le=30.0,
        description="Ventana de tiempo mínima entre alertas consecutivas del mismo objetivo para evitar spam"
    )
    TRACKER_MAX_DISTANCE_PX: float = Field(
        default=85.0,
        ge=10.0,
        le=500.0,
        description="Distancia euclidiana máxima para asociar centroides entre frames consecutivos"
    )
    TRACKER_TRAJECTORY_MAX_POINTS: int = Field(
        default=25,
        ge=5,
        le=100,
        description="Número máximo de puntos históricos retenidos en la trayectoria"
    )

    # Telemetría y Geolocalización Táctica
    BASE_SENSOR_LAT: float = Field(default=-31.624510, ge=-90.0, le=90.0)
    BASE_SENSOR_LON: float = Field(default=-60.485120, ge=-180.0, le=180.0)
    BASE_SENSOR_ALT_M: float = Field(default=25.0, ge=0.0, le=10000.0)
    CAMERA_FOV_HORIZONTAL_DEG: float = Field(default=65.0, ge=10.0, le=170.0)
    CAMERA_FOV_VERTICAL_DEG: float = Field(default=45.0, ge=10.0, le=170.0)
    CAMERA_HEADING_AZIMUTH_DEG: float = Field(default=0.0, ge=0.0, le=360.0)
    GROUND_DISTANCE_ESTIMATE_M: float = Field(default=35.0, ge=1.0, le=10000.0)

    # Geofence & Perímetro de Seguridad (Filtro Semántico)
    GEOFENCE_RADIUS_METERS: float = Field(
        default=15.0,
        ge=1.0,
        le=50000.0,
        description="Radio en metros del perímetro de exclusión táctica respecto a la base"
    )
    CRITICAL_CLASSES: List[str] = Field(
        default=["person", "car", "truck", "motorcycle", "bicycle", "bus"],
        description="Clases semánticas que activan alertas de Geofence y persistencia en Obsidian"
    )
    GEOFENCE_ALERT_AUTO_EXPORT: bool = Field(
        default=True,
        description="Disparar exportación automática a Obsidian ante PERIMETER_BREACH sostenido de clase crítica"
    )
    GEOFENCE_MIN_BREACH_SECONDS: float = Field(
        default=3.0,
        ge=0.0,
        le=60.0,
        description="Tiempo continuo en segundos dentro de la zona restringida antes de disparar reporte en Obsidian"
    )
    HEALTH_RAM_WARNING_LIMIT_MB: float = Field(
        default=250.0,
        ge=50.0,
        le=16384.0,
        description="Límite operativo de advertencia de consumo de memoria RAM del proceso en MB"
    )

    # Alertas de Voz Sintetizada & Grabador de Videoclips de Evidencia
    AUDIO_ALERTS_ENABLED: bool = Field(default=True, description="Emisión de alertas por voz sintetizada en tiempo real")
    AUDIO_COOLDOWN_SECONDS: float = Field(default=5.0, ge=1.0, le=30.0, description="Cooldown entre avisos de voz")
    VIDEO_CLIP_ENABLED: bool = Field(default=True, description="Grabación automática de clips MP4 de evidencia")
    VIDEO_CLIP_PRE_BUFFER_SECONDS: float = Field(default=3.0, ge=1.0, le=10.0, description="Segundos en buffer previo a la brecha")
    VIDEO_CLIP_POST_DURATION_SECONDS: float = Field(default=2.0, ge=1.0, le=10.0, description="Segundos posteriores para completar clip de 5s")

    # Monitoreo de Recursos de Hardware (System Health)
    HARD_RAM_LIMIT_MB: float = Field(default=900.0, ge=100.0, le=4096.0, description="Límite operacional de memoria RAM (PyTorch/YOLO)")
    WARNING_RAM_THRESHOLD_MB: float = Field(default=850.0, ge=50.0, le=4096.0, description="Umbral de advertencia de memoria RAM")

    # Análisis de Conducta (Behavior Analyzer)
    BEHAVIOR_LOITER_RADIUS_PX: float = Field(default=40.0, ge=5.0, le=200.0)
    BEHAVIOR_LOITER_SECONDS_THRESHOLD: float = Field(default=3.0, ge=1.0, le=30.0)
    BEHAVIOR_APPROACHING_MIN_SPEED_PX_S: float = Field(default=8.0, ge=1.0, le=200.0)

    # Servidor Web Bridge & Seguridad de Autenticación
    WEB_ENABLED: bool = Field(default=True)
    WEB_HOST: str = Field(default="127.0.0.1")
    WEB_PORT: int = Field(default=8000, ge=1024, le=65535)
    WEB_TELEMETRY_RATE_HZ: float = Field(default=10.0, ge=1.0, le=30.0)
    API_AUTH_TOKEN: str = Field(
        default="lattice2026",
        min_length=4,
        description="Token precompartido (PSK) por defecto para el WebSocket y Dashboard Web C2"
    )

    # Base de Datos de Borde Embebida (SQLite)
    DB_PATH: Path = Field(
        default=Path("./lattice_telemetry.db"),
        description="Ruta del archivo de base de datos relacional SQLite embebida"
    )

    # Almacenamiento Táctico (Obsidian Vault)
    VAULT_PATH: Path = Field(
        default=Path("./obsidian_vault"),
        description="Ruta local hacia la bóveda de Obsidian"
    )
    SOURCE_DEVICE_NAME: str = Field(
        default="Xiaomi Redmi Note 13 Pro",
        min_length=3,
        max_length=80
    )

    # Seguridad de Red
    ALLOW_LOCAL_NETWORK_ONLY: bool = Field(default=True)

    # Logging
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(default="INFO")
    LOG_JSON_FORMAT: bool = Field(default=True)

    @field_validator("VAULT_PATH")
    @classmethod
    def resolve_and_prepare_vault(cls, path_value: Path) -> Path:
        resolved = path_value.resolve()
        resolved.mkdir(parents=True, exist_ok=True)
        (resolved / "evidence").mkdir(parents=True, exist_ok=True)
        (resolved / "recon_reports").mkdir(parents=True, exist_ok=True)
        return resolved

    @field_validator("DB_PATH")
    @classmethod
    def resolve_db_path(cls, path_value: Path) -> Path:
        return path_value.resolve()


def get_settings() -> SystemSettings:
    """Instancia singleton de configuración validada."""
    return SystemSettings()
