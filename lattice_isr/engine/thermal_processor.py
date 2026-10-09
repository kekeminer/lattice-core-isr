"""
LATTICE-CORE ISR - High-Contrast Monochromatic Thermal Vision Pipeline
Implementación militar de modos térmicos "White Hot" y "Black Hot" con ecualización adaptativa CLAHE.
"""

from typing import Any, Optional, Tuple
import cv2
import numpy as np
from loguru import logger

from lattice_isr.config.settings import ThermalPaletteEnum


class ThermalProcessingError(Exception):
    """Excepción generada ante fallos en la canalización de procesamiento térmico."""
    pass


class ThermalProcessor:
    """
    Motor térmico sintético monocromático de alta visibilidad.
    Transforma el espectro visual en una simulación radiométrica pura:
    - WHITE_HOT: Objetivos calientes en blanco puro brillante, fondo en gris/negro.
    - BLACK_HOT: Objetivos calientes en negro puro, fondo en gris claro/blanco.
    """

    def __init__(self, palette: ThermalPaletteEnum = ThermalPaletteEnum.WHITE_HOT, colormap: Optional[Any] = None):
        self._palette = colormap if colormap is not None else palette
        # CLAHE adaptativo para máxima discriminación de gradientes de calor
        self._clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        # Reutilización de buffers de matrices preasignados para mitigar OOM
        self._cached_shape: Optional[Tuple[int, int]] = None
        self._preallocated_gray: Optional[np.ndarray] = None
        self._preallocated_enhanced: Optional[np.ndarray] = None
        self._preallocated_thermal: Optional[np.ndarray] = None

    @property
    def current_palette(self) -> ThermalPaletteEnum:
        return self._palette

    def set_palette(self, palette: ThermalPaletteEnum) -> None:
        """Establece la paleta térmica activa."""
        self._palette = palette
        logger.info(f"[THERMAL] Modo térmico asignado a: {palette.value}")

    def toggle_white_black_hot(self) -> ThermalPaletteEnum:
        """Alterna rápidamente entre White Hot y Black Hot con la tecla 'B'."""
        if self._palette == ThermalPaletteEnum.WHITE_HOT:
            self._palette = ThermalPaletteEnum.BLACK_HOT
        elif self._palette == ThermalPaletteEnum.BLACK_HOT:
            self._palette = ThermalPaletteEnum.BONE
        else:
            self._palette = ThermalPaletteEnum.WHITE_HOT

        logger.info(f"[THERMAL] Paleta alternada por operador a: {self._palette.value}")
        return self._palette

    def process_frame(self, frame_bgr: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Procesa el frame BGR original produciendo:
        1. `thermal_rendered`: Imagen monocromática de 3 canales para visualización táctica.
        2. `normalized_gray`: Matriz de 1 canal de intensidades para segmentación de hotspots.
        Reutiliza buffers preasignados para evitar asignaciones continuas de RAM en bucle a 60 FPS.
        """
        if frame_bgr is None or frame_bgr.size == 0:
            raise ThermalProcessingError("Frame de entrada nulo recibido por el procesador térmico.")

        h, w = frame_bgr.shape[:2]

        # Verificar o crear buffers preasignados para las dimensiones actuales
        if self._cached_shape != (h, w):
            self._cached_shape = (h, w)
            self._preallocated_gray = np.empty((h, w), dtype=np.uint8)
            self._preallocated_enhanced = np.empty((h, w), dtype=np.uint8)
            self._preallocated_thermal = np.empty((h, w, 3), dtype=np.uint8)

        try:
            # 1. Transformación a dominio de radiancia monocromática en buffer preasignado
            gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY, dst=self._preallocated_gray)

            # 2. Filtrado Gaussiano para atenuación de ruido de sensor
            blurred = cv2.GaussianBlur(gray, (5, 5), 0, dst=self._preallocated_gray)

            # 3. Ecualización adaptativa de histograma local (CLAHE) en buffer preasignado
            enhanced_gray = self._clahe.apply(blurred)

            # 4. Renderizado según la paleta táctica seleccionada utilizando buffer dst
            if self._palette == ThermalPaletteEnum.WHITE_HOT:
                # White Hot: calor = blanco puro brillante
                thermal_rendered = cv2.applyColorMap(enhanced_gray, cv2.COLORMAP_BONE, dst=self._preallocated_thermal)
                detection_matrix = enhanced_gray

            elif self._palette == ThermalPaletteEnum.BLACK_HOT:
                # Black Hot: calor = negro puro, fondo = blanco/gris
                inverted_gray = cv2.bitwise_not(enhanced_gray)
                thermal_rendered = cv2.applyColorMap(inverted_gray, cv2.COLORMAP_BONE, dst=self._preallocated_thermal)
                detection_matrix = enhanced_gray

            elif self._palette == ThermalPaletteEnum.INFERNO or str(self._palette) == "INFERNO":
                thermal_rendered = cv2.applyColorMap(enhanced_gray, cv2.COLORMAP_INFERNO, dst=self._preallocated_thermal)
                detection_matrix = enhanced_gray

            elif self._palette == ThermalPaletteEnum.JET or str(self._palette) == "JET":
                thermal_rendered = cv2.applyColorMap(enhanced_gray, cv2.COLORMAP_JET, dst=self._preallocated_thermal)
                detection_matrix = enhanced_gray

            else:
                thermal_rendered = cv2.cvtColor(enhanced_gray, cv2.COLOR_GRAY2BGR, dst=self._preallocated_thermal)
                detection_matrix = enhanced_gray

            return thermal_rendered, detection_matrix

        except (cv2.error, MemoryError) as err:
            logger.error(f"[THERMAL-MEM-ALERT] Alerta de memoria o fallo OpenCV en pipeline térmico: {err}")
            # Fallback seguro sin interrupción ante presión de memoria RAM
            fallback_gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY) if frame_bgr.ndim == 3 else frame_bgr
            fallback_bgr = frame_bgr if frame_bgr.ndim == 3 else cv2.cvtColor(fallback_gray, cv2.COLOR_GRAY2BGR)
            return fallback_bgr, fallback_gray
