"""
LATTICE-CORE ISR - High-Contrast Monochromatic HUD & Asynchronous YOLOv8 Neural Detector
HUD táctico militar en escala de negros, blancos y grises de alta visibilidad.
Integra inferencia neuronal YOLOv8 desacoplada a 60 FPS (Stride 32: 384x640),
Panel Lateral Táctico de Inspección (Side Inspector Panel de 300px) con análisis
de vestimenta por histograma HSV, vector cinemático e inventario de terreno en m².
"""

import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np
from pydantic import BaseModel, Field
from loguru import logger

from lattice_isr.config.settings import SystemSettings
from lattice_isr.engine.geolocation_engine import TargetGeoPosition, SectorInventory
from lattice_isr.engine.geofence_engine import TargetGeofenceStatus
from lattice_isr.engine.models import TargetDetection, TrackedTargetState, TargetBehaviorIntent
from lattice_isr.utils.system_health import SystemHealthMetrics

try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False


class DetectionProcessingError(Exception):
    """Error al ejecutar la inferencia neuronal o segmentación de firmas."""
    pass


# Conjuntos inmutables O(1) para filtrado y categorización de amenazas tácticas
CRITICAL_THREAT_CLASSES: frozenset = frozenset({"car", "truck", "bus"})
HIGH_THREAT_CLASSES: frozenset = frozenset({"person", "motorcycle"})
MEDIUM_THREAT_CLASSES: frozenset = frozenset({"bicycle", "backpack", "handbag", "tv", "laptop", "chair", "bottle", "cup"})
CARDINAL_DIRECTIONS: Tuple[str, ...] = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def extract_dominant_color_hsv(roi: Optional[np.ndarray], class_name: str = "target") -> str:
    """
    Analiza la superficie o vestimenta del objetivo enfocado mediante cuantización
    de histograma en espacio de color HSV.
    Para personas, analiza prioritariamente la región del torso/vestimenta.
    Retorna una descripción táctica (ej. 'Persona - Vestimenta: Amarillo / Oscuro').
    """
    if roi is None or roi.size < 20:
        return "Indeterminado"

    try:
        h_roi, w_roi = roi.shape[:2]
        cls_lower = class_name.lower()

        # Si es una persona, recortar la región central del torso para enfocar ropa
        if cls_lower == "person" and h_roi >= 12 and w_roi >= 8:
            y_start = int(h_roi * 0.22)
            y_end = int(h_roi * 0.82)
            x_start = int(w_roi * 0.15)
            x_end = int(w_roi * 0.85)
            sample = roi[y_start:y_end, x_start:x_end]
            if sample.size < 16:
                sample = roi
        else:
            # Para vehículos/objetos, descartar un 10% del margen exterior
            if h_roi >= 10 and w_roi >= 10:
                sample = roi[int(h_roi * 0.1):int(h_roi * 0.9), int(w_roi * 0.1):int(w_roi * 0.9)]
            else:
                sample = roi

        hsv = cv2.cvtColor(sample, cv2.COLOR_BGR2HSV)
        h = hsv[:, :, 0]
        s = hsv[:, :, 1]
        v = hsv[:, :, 2]

        total_pixels = float(hsv.shape[0] * hsv.shape[1])
        if total_pixels <= 0:
            return "Indeterminado"

        # Bins de color según rangos HSV estándar de OpenCV (H: 0-180, S: 0-255, V: 0-255)
        counts: Dict[str, int] = {
            "Oscuro": int(np.sum(v < 55)),
            "Blanco": int(np.sum((v > 195) & (s < 45))),
            "Gris": int(np.sum((v >= 55) & (v <= 195) & (s < 50))),
            "Rojo": int(np.sum(((h < 10) | (h >= 170)) & (s >= 50) & (v >= 55))),
            "Naranja": int(np.sum((h >= 10) & (h < 25) & (s >= 50) & (v >= 55))),
            "Amarillo": int(np.sum((h >= 25) & (h < 35) & (s >= 50) & (v >= 55))),
            "Verde": int(np.sum((h >= 35) & (h < 85) & (s >= 50) & (v >= 55))),
            "Azul": int(np.sum((h >= 85) & (h < 130) & (s >= 50) & (v >= 55))),
            "Violeta": int(np.sum((h >= 130) & (h < 160) & (s >= 50) & (v >= 55))),
            "Rosa": int(np.sum((h >= 160) & (h < 170) & (s >= 50) & (v >= 55))),
        }

        # Filtrar colores ordenados por predominancia
        sorted_colors = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        top1_name, top1_cnt = sorted_colors[0]
        top1_ratio = top1_cnt / total_pixels

        top2_name, top2_cnt = sorted_colors[1]
        top2_ratio = top2_cnt / total_pixels

        # Componer etiqueta bicolor si el secundario es significativo
        if top2_ratio >= 0.18 and top2_name != top1_name:
            color_summary = f"{top1_name} / {top2_name}"
        else:
            color_summary = top1_name

        # Prefijo según clase
        if cls_lower == "person":
            return f"Persona - Vestimenta: {color_summary}"
        elif cls_lower in ("car", "truck", "bus", "motorcycle", "bicycle"):
            return f"Vehículo - Carrocería: {color_summary}"
        elif cls_lower in ("tv", "laptop", "chair", "backpack", "bottle", "cup"):
            return f"{class_name.capitalize()} - Superficie: {color_summary}"
        else:
            return f"{class_name.capitalize()} - Tono: {color_summary}"

    except Exception as err:
        logger.debug(f"[HSV-ATTR-ERR] Error extrayendo color dominante: {err}")
        return "Indeterminado"


def heading_to_cardinal(heading_deg: float) -> str:
    """Convierte grados de azimut a dirección cardinal táctica O(1)."""
    idx = int((heading_deg + 22.5) // 45) % 8
    return CARDINAL_DIRECTIONS[idx]


class ThermalObjectDetector:
    """
    Detector híbrido de objetivos con soporte de Inferencia Neuronal Asíncrona (Threaded) a 60 FPS:
    1. Primario: Inferencia por red neuronal YOLOv8 para clasificación semántica detallada
       (tv, laptop, chair, person, bicycle, car, truck, bus, motorcycle, backpack, handbag).
       Optimizada a resolución fija Stride 32: (384, 640).
    2. Secundario / Fallback: Detección por contraste térmico morfológico con filtro Gaussiano y top-N.
    3. Panel Lateral Táctico (Side Inspector Panel de 300px) con telemetría espectral e inventario de m².
    """

    _INSPECTOR_CACHE: Dict[str, Any] = {
        "target_id": None,
        "last_analysis_time": 0.0,
        "dominant_attr_str": "Indeterminado",
        "thumbnail": None
    }

    def __init__(self, settings: SystemSettings):
        self._settings = settings
        self._morph_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        self._yolo_model: Optional[Any] = None
        self._yolo_enabled = getattr(settings, "YOLO_ENABLED", True) and YOLO_AVAILABLE
        self._target_classes = set(getattr(
            settings,
            "YOLO_TARGET_CLASSES",
            ["person", "car", "truck", "bus", "motorcycle", "bicycle", "backpack", "handbag", "tv", "laptop", "chair", "bottle", "cup"]
        ))
        self._confidence_threshold = getattr(settings, "YOLO_CONFIDENCE_THRESHOLD", 0.45)
        self._iou_threshold = getattr(settings, "YOLO_IOU_THRESHOLD", 0.45)

        # Dimensiones de inferencia Stride 32
        inf_h = getattr(settings, "INFERENCE_HEIGHT", 384)
        inf_w = getattr(settings, "INFERENCE_WIDTH", 640)
        # Asegurar divisibilidad por 32
        self._inference_imgsz = (
            int(math.ceil(inf_h / 32.0) * 32),
            int(math.ceil(inf_w / 32.0) * 32)
        )

        # Componentes de Pipeline Asíncrono (Threaded Inference a 60 FPS)
        self._worker_thread: Optional[threading.Thread] = None
        self._worker_stop_event = threading.Event()
        self._frame_lock = threading.Lock()
        self._pending_frame: Optional[np.ndarray] = None
        self._pending_gray: Optional[np.ndarray] = None
        self._pending_timestamp_id: str = ""
        self._has_pending_frame = threading.Event()
        self._latest_detections: List[TargetDetection] = []
        self._latest_detections_lock = threading.Lock()
        self._last_inference_fps: float = 0.0
        self._inference_cadence: int = getattr(settings, "INFERENCE_CADENCE", 3)
        self._frame_count: int = 0

        if self._yolo_enabled:
            self._init_yolo_model()

    def _init_yolo_model(self) -> None:
        """Carga en memoria el modelo liviano YOLOv8 nano."""
        try:
            model_name = getattr(self._settings, "YOLO_MODEL_NAME", "yolov8n.pt")
            logger.info(f"[YOLO] Cargando modelo de detección neuronal: {model_name}...")
            self._yolo_model = YOLO(model_name)
            logger.info(f"[YOLO] Red neuronal inicializada (imgsz={self._inference_imgsz}, clases={len(self._target_classes)}).")
        except Exception as err:
            logger.warning(f"[YOLO-WARN] No se pudo cargar el modelo YOLO ({err}). Usando fallback morfológico.")
            self._yolo_model = None

    def start_async_worker(self) -> None:
        """Inicia el hilo en segundo plano para inferencia desacoplada sin bloquear el stream."""
        if self._worker_thread is not None and self._worker_thread.is_alive():
            return
        self._worker_stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._async_inference_loop,
            name="LatticeYOLOInferencer",
            daemon=True
        )
        self._worker_thread.start()
        logger.info("[YOLO] Worker de inferencia asíncrona iniciado (60 FPS visual decoupled).")

    def stop_async_worker(self) -> None:
        """Detiene ordenadamente el worker de inferencia."""
        self._worker_stop_event.set()
        self._has_pending_frame.set()
        if self._worker_thread is not None and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.0)
            self._worker_thread = None

    def submit_frame_async(
        self,
        frame_rgb: np.ndarray,
        base_timestamp_id: str,
        gray_fallback: Optional[np.ndarray] = None
    ) -> None:
        """
        Envía un nuevo frame a la cola de inferencia atómica sin bloquear el hilo visual.
        Reemplaza cualquier frame pendiente previo (Drop-oldest).
        """
        with self._frame_lock:
            self._pending_frame = frame_rgb
            self._pending_gray = gray_fallback
            self._pending_timestamp_id = base_timestamp_id
            self._has_pending_frame.set()

    def get_latest_detections(self) -> List[TargetDetection]:
        """Retorna instantáneamente las últimas detecciones cacheadas (0.0 ms)."""
        with self._latest_detections_lock:
            return list(self._latest_detections)

    def _async_inference_loop(self) -> None:
        """Bucle continuo del hilo de IA ejecutando inferencias sobre el último frame."""
        while not self._worker_stop_event.is_set():
            # Esperar hasta que haya un frame pendiente
            signaled = self._has_pending_frame.wait(timeout=0.04)
            if self._worker_stop_event.is_set():
                break
            if not signaled:
                continue

            with self._frame_lock:
                frame_to_process = self._pending_frame
                gray_to_process = self._pending_gray
                ts_id = self._pending_timestamp_id
                self._pending_frame = None
                self._has_pending_frame.clear()

            if frame_to_process is None or frame_to_process.size == 0:
                continue

            t0 = time.monotonic()
            try:
                # Inferencia síncrona dentro del worker
                results = self.detect_objects(
                    frame_rgb=frame_to_process,
                    base_timestamp_id=ts_id,
                    gray_fallback=gray_to_process,
                    async_mode=False
                )
                with self._latest_detections_lock:
                    self._latest_detections = results

                dt = time.monotonic() - t0
                if dt > 0:
                    self._last_inference_fps = round(1.0 / dt, 1)

            except Exception as err:
                logger.debug(f"[YOLO-WORKER-ERR] Excepción en inferencia asíncrona: {err}")

    def detect_objects(
        self,
        frame_rgb: np.ndarray,
        base_timestamp_id: str,
        gray_fallback: Optional[np.ndarray] = None,
        async_mode: bool = False
    ) -> List[TargetDetection]:
        """
        Inferencia táctica:
        - Si async_mode=True: envía el frame al hilo de inferencia y retorna inmediatamente
          las cajas del último frame procesado (permitiendo 60 FPS ininterrumpidos en visualización).
        - Si async_mode=False: ejecuta la inferencia de forma sincrónica directa.
        """
        if async_mode:
            if self._worker_thread is None or not self._worker_thread.is_alive():
                self.start_async_worker()
            self._frame_count += 1
            # Submuestreo asíncrono (Inference Frame-Skipping a 60 FPS):
            # Iniciar en frame 1 y luego enviar únicamente cada INFERENCE_CADENCE fotogramas
            if self._frame_count == 1 or (self._frame_count % self._inference_cadence) == 0:
                self.submit_frame_async(frame_rgb, base_timestamp_id, gray_fallback)
            return self.get_latest_detections()

        # Inferencia Sincrónica Directa
        if self._yolo_model is not None and frame_rgb is not None and frame_rgb.size > 0:
            try:
                return self._detect_yolo(frame_rgb, base_timestamp_id)
            except Exception as yolo_err:
                logger.debug(f"[YOLO] Excepción durante inferencia: {yolo_err}; usando fallback.")

        # Fallback a detección morfológica
        if gray_fallback is not None and gray_fallback.size > 0:
            return self.detect_hotspots(gray_fallback, base_timestamp_id)
        elif frame_rgb is not None and frame_rgb.size > 0:
            gray = cv2.cvtColor(frame_rgb, cv2.COLOR_BGR2GRAY)
            return self.detect_hotspots(gray, base_timestamp_id)
        return []

    def _detect_yolo(
        self,
        frame_bgr: np.ndarray,
        base_timestamp_id: str
    ) -> List[TargetDetection]:
        """Ejecuta inferencia YOLOv8 con imgsz divisible por 32 filtrando clases tácticas ampliadas."""
        results = self._yolo_model(
            frame_bgr,
            conf=self._confidence_threshold,
            iou=self._iou_threshold,
            verbose=False,
            imgsz=self._inference_imgsz
        )

        candidates: List[dict] = []
        if not results or len(results) == 0:
            return []

        res = results[0]
        boxes = res.boxes
        if boxes is None or len(boxes) == 0:
            return []

        names = res.names

        for box in boxes:
            cls_id = int(box.cls[0].item())
            class_name = names.get(cls_id, "unknown")
            conf = float(box.conf[0].item())

            # Filtrar solo clases tácticas de interés si están configuradas
            if self._target_classes and class_name not in self._target_classes:
                continue

            xyxy = box.xyxy[0].cpu().numpy()
            x1, y1, x2, y2 = int(xyxy[0]), int(xyxy[1]), int(xyxy[2]), int(xyxy[3])
            w = max(1, x2 - x1)
            h = max(1, y2 - y1)
            area = w * h
            cx = x1 + (w // 2)
            cy = y1 + (h // 2)

            threat = self._classify_yolo_threat(class_name, area, conf)

            candidates.append({
                "bbox_x": x1,
                "bbox_y": y1,
                "bbox_w": w,
                "bbox_h": h,
                "centroid_x": cx,
                "centroid_y": cy,
                "area_px": area,
                "mean_intensity": 240.0,
                "threat_level": threat,
                "class_name": class_name,
                "confidence": round(conf, 2)
            })

        # Top-N targets
        candidates.sort(key=lambda c: (c["confidence"], c["area_px"]), reverse=True)
        top_candidates = candidates[:self._settings.MAX_TARGETS_PER_FRAME]

        targets: List[TargetDetection] = []
        for idx, c in enumerate(top_candidates, start=1):
            target_id = f"RAW-{base_timestamp_id}-{idx:02d}"
            targets.append(
                TargetDetection(
                    target_id=target_id,
                    bbox_x=c["bbox_x"],
                    bbox_y=c["bbox_y"],
                    bbox_w=c["bbox_w"],
                    bbox_h=c["bbox_h"],
                    centroid_x=c["centroid_x"],
                    centroid_y=c["centroid_y"],
                    area_px=c["area_px"],
                    mean_intensity=c["mean_intensity"],
                    threat_level=c["threat_level"],
                    class_name=c["class_name"],
                    confidence=c["confidence"]
                )
            )

        return targets

    def _classify_yolo_threat(self, class_name: str, area: int, conf: float) -> str:
        """Determina la amenaza táctica según la semántica de la clase con búsqueda O(1)."""
        cls_lower = class_name.lower()
        if cls_lower in CRITICAL_THREAT_CLASSES and area > 1200:
            return "CRITICAL"
        if cls_lower in HIGH_THREAT_CLASSES or conf > 0.75:
            return "HIGH"
        if cls_lower in MEDIUM_THREAT_CLASSES:
            return "MEDIUM"
        return "LOW"

    def detect_hotspots(
        self,
        gray_frame: np.ndarray,
        base_timestamp_id: str
    ) -> List[TargetDetection]:
        """
        Segmenta regiones con emisión térmica superior al umbral configurado (Fallback morfológico).
        """
        if gray_frame is None or gray_frame.size == 0:
            raise DetectionProcessingError("Matriz monocromática inválida para detección de hotspots.")

        try:
            # 1. Filtro Gaussiano anti-ruido
            smoothed_gray = cv2.GaussianBlur(gray_frame, (7, 7), 0)

            # 2. Binarización
            _, binary_mask = cv2.threshold(
                smoothed_gray,
                self._settings.HOTSPOT_BRIGHTNESS_THRESHOLD,
                255,
                cv2.THRESH_BINARY
            )

            # 3. Operaciones morfológicas
            cleaned_mask = cv2.morphologyEx(binary_mask, cv2.MORPH_OPEN, self._morph_kernel)
            cleaned_mask = cv2.morphologyEx(cleaned_mask, cv2.MORPH_DILATE, self._morph_kernel)

            # 4. Contornos
            contours, _ = cv2.findContours(
                cleaned_mask,
                cv2.RETR_EXTERNAL,
                cv2.CHAIN_APPROX_SIMPLE
            )

            candidates: List[dict] = []

            for cnt in contours:
                area = int(cv2.contourArea(cnt))
                if area < self._settings.HOTSPOT_MIN_AREA:
                    continue

                x, y, w, h = cv2.boundingRect(cnt)
                m = cv2.moments(cnt)
                if m["m00"] != 0:
                    cx = int(m["m10"] / m["m00"])
                    cy = int(m["m01"] / m["m00"])
                else:
                    cx = x + (w // 2)
                    cy = y + (h // 2)

                roi_mask = cleaned_mask[y:y+h, x:x+w]
                roi_gray = smoothed_gray[y:y+h, x:x+w]
                mean_val = float(cv2.mean(roi_gray, mask=roi_mask)[0])
                threat = self._classify_threat(area, mean_val)

                candidates.append({
                    "bbox_x": x,
                    "bbox_y": y,
                    "bbox_w": w,
                    "bbox_h": h,
                    "centroid_x": cx,
                    "centroid_y": cy,
                    "area_px": area,
                    "mean_intensity": round(mean_val, 2),
                    "threat_level": threat,
                    "class_name": "hotspot",
                    "confidence": 0.85
                })

            candidates.sort(key=lambda c: c["area_px"], reverse=True)
            top_candidates = candidates[:self._settings.MAX_TARGETS_PER_FRAME]

            targets: List[TargetDetection] = []
            for idx, c in enumerate(top_candidates, start=1):
                target_id = f"RAW-{base_timestamp_id}-{idx:02d}"
                targets.append(
                    TargetDetection(
                        target_id=target_id,
                        bbox_x=c["bbox_x"],
                        bbox_y=c["bbox_y"],
                        bbox_w=c["bbox_w"],
                        bbox_h=c["bbox_h"],
                        centroid_x=c["centroid_x"],
                        centroid_y=c["centroid_y"],
                        area_px=c["area_px"],
                        mean_intensity=c["mean_intensity"],
                        threat_level=c["threat_level"],
                        class_name=c["class_name"],
                        confidence=c["confidence"]
                    )
                )

            return targets

        except cv2.error as err:
            logger.error(f"[DETECTION-ERR] Fallo de procesamiento en segmentación: {err}")
            raise DetectionProcessingError(f"Error OpenCV en detección: {err}") from err

    def _classify_threat(self, area: int, mean_intensity: float) -> str:
        """Determina el nivel de criticidad táctica térmica."""
        if area >= self._settings.THREAT_TRIGGER_AREA and mean_intensity > 235:
            return "CRITICAL"
        if area >= self._settings.THREAT_TRIGGER_AREA or mean_intensity > 225:
            return "HIGH"
        if area >= (self._settings.HOTSPOT_MIN_AREA * 2):
            return "MEDIUM"
        return "LOW"

    @classmethod
    def render_tactical_hud(
        cls,
        canvas: np.ndarray,
        tracked_targets: list,
        geo_positions: Dict[str, TargetGeoPosition],
        geofence_statuses: Dict[str, TargetGeofenceStatus],
        behaviors: Dict[str, TargetBehaviorIntent],
        fps: float,
        source_name: str,
        thermal_mode_name: str,
        health_metrics: Optional[SystemHealthMetrics] = None,
        sector_inventory: Optional[SectorInventory] = None,
        raw_sensor_frame: Optional[np.ndarray] = None,
        focused_target_id: Optional[str] = None,
        attach_side_panel: bool = True,
        target_history: Optional[Dict[str, Any]] = None
    ) -> np.ndarray:
        """
        Renderiza el Heads-Up Display (HUD) militar monocromático con clasificación semántica YOLOv8:
        - Paleta limpia: Negro (10,12,15), Gris Carbón (70,75,85), Blanco Puro (255,255,255).
        - Panel Lateral Táctico (Side Inspector Panel de 300px) adjunto a la derecha:
          * Métricas del objetivo enfocado: TRG-ID, clase, confianza %, análisis HSV de vestimenta/superficie.
          * Vector cinemático: Rumbo (Heading cardinal + grados), velocidad px/s, estado [SAFE] / [BREACH].
          * Ficha de densidad y cobertura del sector en metros cuadrados (m²).
        """
        hud = canvas.copy()
        height, width = hud.shape[:2]

        COLOR_BLACK = (10, 12, 15)
        COLOR_PANEL_BG = (14, 16, 20)
        COLOR_BORDER_GREY = (70, 75, 85)
        COLOR_TEXT_MAIN = (255, 255, 255)
        COLOR_TEXT_DIM = (180, 185, 195)
        COLOR_WHITE_BRIGHT = (255, 255, 255)
        COLOR_PLATINUM = (220, 225, 230)
        COLOR_TRAJECTORY = (130, 135, 145)

        # 1. Overlay superior: Banner de Estado del Sistema C2
        cv2.rectangle(hud, (0, 0), (width, 42), COLOR_BLACK, -1)
        cv2.line(hud, (0, 42), (width, 42), COLOR_BORDER_GREY, 1)

        header_text = f"▲ LATTICE-CORE ISR C2 // [{source_name}] // MODE: {thermal_mode_name}"
        cv2.putText(hud, header_text, (16, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.48, COLOR_TEXT_MAIN, 1, cv2.LINE_AA)

        status_right = f"FPS: {fps:.1f} | TRACKS: {len(tracked_targets)}"
        cv2.putText(hud, status_right, (max(16, width - 210), 26), cv2.FONT_HERSHEY_SIMPLEX, 0.48, COLOR_TEXT_DIM, 1, cv2.LINE_AA)

        # 2. Retícula central óptica (Boresight)
        center_x = width // 2
        center_y = height // 2
        cv2.line(hud, (center_x - 16, center_y), (center_x + 16, center_y), COLOR_BORDER_GREY, 1)
        cv2.line(hud, (center_x, center_y - 16), (center_x, center_y + 16), COLOR_BORDER_GREY, 1)
        cv2.circle(hud, (center_x, center_y), 4, COLOR_BORDER_GREY, 1)

        # 3. Renderizado de objetivos rastreados en el visor principal
        for trg in tracked_targets:
            x, y, w, h = trg.bbox_x, trg.bbox_y, trg.bbox_w, trg.bbox_h
            cx, cy = trg.centroid_x, trg.centroid_y

            gf = geofence_statuses.get(trg.target_id)
            is_breach = gf.is_breaching if gf else False
            beh = behaviors.get(trg.target_id)
            intent_str = beh.intent if beh else "TRANSITING"

            is_locked = (focused_target_id is not None and trg.target_id == focused_target_id)
            target_color = COLOR_WHITE_BRIGHT if (is_locked or is_breach or trg.threat_level == "CRITICAL") else COLOR_PLATINUM
            line_thickness = 2 if (is_locked or is_breach or trg.threat_level in ("HIGH", "CRITICAL")) else 1

            # 3.1 Trayectoria histórica
            if hasattr(trg, "trajectory") and len(trg.trajectory) > 1:
                pts = np.array(trg.trajectory, np.int32).reshape((-1, 1, 2))
                cv2.polylines(hud, [pts], isClosed=False, color=COLOR_TRAJECTORY, thickness=1, lineType=cv2.LINE_AA)

            # 3.2 Esquinas tácticas
            line_len = max(8, int(min(w, h) * 0.25))
            cv2.line(hud, (x, y), (x + line_len, y), target_color, line_thickness)
            cv2.line(hud, (x, y), (x, y + line_len), target_color, line_thickness)
            cv2.line(hud, (x + w, y), (x + w - line_len, y), target_color, line_thickness)
            cv2.line(hud, (x + w, y), (x + w, y + line_len), target_color, line_thickness)
            cv2.line(hud, (x, y + h), (x + line_len, y + h), target_color, line_thickness)
            cv2.line(hud, (x, y + h), (x, y + h - line_len), target_color, line_thickness)
            cv2.line(hud, (x + w, y + h), (x + w - line_len, y + h), target_color, line_thickness)
            cv2.line(hud, (x + w, y + h), (x + w, y + h - line_len), target_color, line_thickness)

            if is_locked:
                cv2.rectangle(hud, (x - 2, y - 2), (x + w + 2, y + h + 2), COLOR_WHITE_BRIGHT, 1)

            # 3.3 Marcador de centroide
            cv2.drawMarker(hud, (cx, cy), target_color, markerType=cv2.MARKER_CROSS, markerSize=8, thickness=1)

            # 3.4 Vector de rumbo y velocidad
            if trg.velocity_px_s > 4.0 and trg.heading_deg > 0:
                vector_len = min(36, max(12, int(trg.velocity_px_s * 0.4)))
                rad = math.radians(trg.heading_deg)
                vx = int(cx + vector_len * math.sin(rad))
                vy = int(cy - vector_len * math.cos(rad))
                cv2.arrowedLine(hud, (cx, cy), (vx, vy), target_color, 1, tipLength=0.3)

            # 3.5 Panel de telemetría flotante con Clase y Confianza YOLO
            geo = geo_positions.get(trg.target_id)
            geo_lat_str = f"{geo.latitude:.5f}" if geo else "N/A"
            geo_lon_str = f"{geo.longitude:.5f}" if geo else "N/A"

            panel_y = max(68, y - 8)
            breach_tag = "[PERIMETER BREACH] " if is_breach else ""
            lock_prefix = "[LOCKED] " if is_locked else ""

            class_label = getattr(trg, "class_name", "TARGET").upper()
            conf_val = int(getattr(trg, "confidence", 1.0) * 100)
            tag_line1 = f"{lock_prefix}{breach_tag}{class_label} {conf_val}% | {trg.target_id} [{trg.threat_level}]"
            tag_line2 = f"GPS: {geo_lat_str}, {geo_lon_str} | HDG: {trg.heading_deg:.0f}° | {trg.velocity_px_s:.0f}px/s | {intent_str}"

            panel_w = max(280, len(tag_line2) * 7 + 14)
            cv2.rectangle(hud, (x, panel_y - 34), (x + panel_w, panel_y + 4), COLOR_BLACK, -1)
            cv2.rectangle(hud, (x, panel_y - 34), (x + panel_w, panel_y + 4), target_color, 1)

            cv2.putText(hud, tag_line1, (x + 6, panel_y - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.36, COLOR_TEXT_MAIN, 1, cv2.LINE_AA)
            cv2.putText(hud, tag_line2, (x + 6, panel_y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.31, COLOR_TEXT_DIM, 1, cv2.LINE_AA)

        # 4. Barra inferior: Monitor de Recursos de Hardware y Salud (< 900 MB RAM)
        cv2.rectangle(hud, (0, height - 26), (width, height), COLOR_BLACK, -1)
        cv2.line(hud, (0, height - 26), (width, height - 26), COLOR_BORDER_GREY, 1)

        if health_metrics:
            mem_status = "MEM LIMIT: >850MB WARN" if health_metrics.ram_limit_warning else "MEM LIMIT: <900MB OK"
            health_text = (
                f"SYSTEM HEALTH // FPS: {health_metrics.fps:.1f} | "
                f"RAM: {health_metrics.process_ram_mb:.1f} MB | "
                f"CPU: {health_metrics.process_cpu_percent:.1f}% (SYS: {health_metrics.system_cpu_percent:.1f}%) | "
                f"{mem_status}"
            )
            color_health = COLOR_WHITE_BRIGHT if health_metrics.ram_limit_warning else COLOR_TEXT_DIM
        else:
            health_text = f"SYSTEM HEALTH // FPS: {fps:.1f} | RAM: <900MB OPERATIONAL | CPU: NORMAL"
            color_health = COLOR_TEXT_DIM

        cv2.putText(hud, health_text, (16, height - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.38, color_health, 1, cv2.LINE_AA)

        if not attach_side_panel:
            return hud

        # =====================================================================
        # 5. PANEL LATERAL DE INSPECCIÓN TÁCTICA (SIDE INSPECTOR PANEL - 300px)
        # =====================================================================
        PANEL_WIDTH = 300
        # Optimización vectorizada NumPy para composición a 60 FPS sin sobrecarga
        composite = np.empty((height, width + PANEL_WIDTH, 3), dtype=np.uint8)
        composite[:, :width] = hud
        composite[:, width:] = COLOR_PANEL_BG

        px_start = width
        # Línea divisoria vertical principal
        cv2.line(composite, (px_start, 0), (px_start, height), COLOR_BORDER_GREY, 1)

        # 5.1 Header del Panel Lateral
        cv2.rectangle(composite, (px_start, 0), (px_start + PANEL_WIDTH, 42), COLOR_BLACK, -1)
        cv2.line(composite, (px_start, 42), (px_start + PANEL_WIDTH, 42), COLOR_BORDER_GREY, 1)
        cv2.putText(
            composite,
            "▲ TACTICAL INSPECTOR",
            (px_start + 14, 26),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.46,
            COLOR_WHITE_BRIGHT,
            1,
            cv2.LINE_AA
        )

        # 5.2 Determinación del Objetivo Enfocado y Persistencia
        target_focus = None
        is_frozen = False

        if focused_target_id:
            if tracked_targets:
                for t in tracked_targets:
                    if t.target_id == focused_target_id:
                        target_focus = t
                        break
            if target_focus is None and target_history:
                target_focus = target_history.get(focused_target_id)
                if target_focus is not None:
                    is_frozen = True

        if target_focus is None:
            if tracked_targets:
                # Priorizar objetivos con BREACH o mayor amenaza
                criticals = [t for t in tracked_targets if t.threat_level == "CRITICAL"]
                highs = [t for t in tracked_targets if t.threat_level == "HIGH"]
                if criticals:
                    target_focus = criticals[0]
                elif highs:
                    target_focus = highs[0]
                else:
                    target_focus = tracked_targets[0]
            elif target_history and len(target_history) > 0:
                # Persistencia en Panel: mantener última entidad conocida si la cámara se mueve
                target_focus = list(target_history.values())[-1]
                is_frozen = True

        curr_y = 62

        if target_focus is not None:
            trg_id = target_focus.target_id
            cls_name = getattr(target_focus, "class_name", "TARGET").upper()
            conf_pct = int(getattr(target_focus, "confidence", 1.0) * 100)
            gf = geofence_statuses.get(trg_id) if geofence_statuses else None
            is_breach = gf.is_breaching if gf else False
            beh = behaviors.get(trg_id) if behaviors else None
            geo = geo_positions.get(trg_id) if geo_positions else None

            # Tarjeta de Identificación
            lock_str = " [LOCKED]" if (focused_target_id and trg_id == focused_target_id) else ""
            frozen_str = " (OFF-FRAME)" if is_frozen else ""
            cv2.putText(composite, f"TARGET: {trg_id}{lock_str}{frozen_str}", (px_start + 14, curr_y), cv2.FONT_HERSHEY_SIMPLEX, 0.40, COLOR_WHITE_BRIGHT, 1, cv2.LINE_AA)
            curr_y += 18
            cv2.putText(composite, f"CLASS: {cls_name} ({conf_pct}%)", (px_start + 14, curr_y), cv2.FONT_HERSHEY_SIMPLEX, 0.38, COLOR_PLATINUM, 1, cv2.LINE_AA)
            curr_y += 18
            cv2.putText(composite, f"THREAT: [{target_focus.threat_level}]", (px_start + 14, curr_y), cv2.FONT_HERSHEY_SIMPLEX, 0.38, COLOR_TEXT_DIM, 1, cv2.LINE_AA)
            curr_y += 24

            # Miniatura (Thumbnail) del Objetivo y Análisis HSV Cacheados
            # Se recalcula únicamente si cambia el objetivo seleccionado o transcurre 1 segundo
            now_t = time.monotonic()
            cache = cls._INSPECTOR_CACHE
            need_refresh = (
                not is_frozen and (
                    cache["target_id"] != target_focus.target_id
                    or (now_t - cache["last_analysis_time"]) >= 1.0
                    or cache["thumbnail"] is None
                )
            )

            if need_refresh:
                src_frame = raw_sensor_frame if raw_sensor_frame is not None else canvas
                bx, by, bw, bh = target_focus.bbox_x, target_focus.bbox_y, target_focus.bbox_w, target_focus.bbox_h
                h_f, w_f = src_frame.shape[:2]
                y1 = max(0, min(h_f - 1, by))
                y2 = max(0, min(h_f, by + bh))
                x1 = max(0, min(w_f - 1, bx))
                x2 = max(0, min(w_f, bx + bw))

                roi = src_frame[y1:y2, x1:x2] if (y2 > y1 and x2 > x1) else None
                cache["dominant_attr_str"] = extract_dominant_color_hsv(roi, target_focus.class_name)
                if roi is not None and roi.size > 0:
                    cache["thumbnail"] = cv2.resize(roi, (100, 75), interpolation=cv2.INTER_LINEAR)
                else:
                    cache["thumbnail"] = None
                cache["target_id"] = target_focus.target_id
                cache["last_analysis_time"] = now_t

            dominant_attr_str = cache.get("dominant_attr_str", "Indeterminado")
            thumb = cache.get("thumbnail")

            if thumb is not None:
                thumb_w, thumb_h = 100, 75
                # Composición vectorizada ultrarrápida de la miniatura
                composite[curr_y:curr_y + thumb_h, px_start + 14:px_start + 14 + thumb_w] = thumb
                # Borde táctico alrededor de la miniatura
                cv2.rectangle(composite, (px_start + 14, curr_y), (px_start + 14 + thumb_w, curr_y + thumb_h), COLOR_BORDER_GREY, 1)

                # Estado de Alerta destacado al costado de la miniatura
                if is_frozen:
                    alert_text = "STATUS: FROZEN"
                    alert_bg = COLOR_BLACK
                    alert_fg = COLOR_PLATINUM
                elif is_breach:
                    alert_text = "STATUS: BREACH"
                    alert_bg = COLOR_WHITE_BRIGHT
                    alert_fg = COLOR_BLACK
                else:
                    alert_text = "STATUS: SAFE"
                    alert_bg = COLOR_BLACK
                    alert_fg = COLOR_PLATINUM

                cv2.rectangle(composite, (px_start + 126, curr_y + 12), (px_start + 286, curr_y + 40), alert_bg, -1)
                cv2.rectangle(composite, (px_start + 126, curr_y + 12), (px_start + 286, curr_y + 40), COLOR_BORDER_GREY, 1)
                cv2.putText(composite, alert_text, (px_start + 134, curr_y + 32), cv2.FONT_HERSHEY_SIMPLEX, 0.40, alert_fg, 1, cv2.LINE_AA)

                curr_y += thumb_h + 18
            else:
                curr_y += 10

            # Línea separadora
            cv2.line(composite, (px_start + 14, curr_y), (px_start + PANEL_WIDTH - 14, curr_y), COLOR_BORDER_GREY, 1)
            curr_y += 18

            # Análisis de Atributos Espectrales
            cv2.putText(composite, "▲ ATTRIBUTE ANALYSIS (HSV)", (px_start + 14, curr_y), cv2.FONT_HERSHEY_SIMPLEX, 0.38, COLOR_TEXT_DIM, 1, cv2.LINE_AA)
            curr_y += 18

            # Renderizado multilinea del atributo si es largo
            if len(dominant_attr_str) > 32:
                parts = dominant_attr_str.split(":", 1)
                line1 = parts[0] + ":"
                line2 = parts[1].strip() if len(parts) > 1 else ""
                cv2.putText(composite, line1, (px_start + 14, curr_y), cv2.FONT_HERSHEY_SIMPLEX, 0.36, COLOR_WHITE_BRIGHT, 1, cv2.LINE_AA)
                curr_y += 16
                cv2.putText(composite, line2, (px_start + 24, curr_y), cv2.FONT_HERSHEY_SIMPLEX, 0.36, COLOR_WHITE_BRIGHT, 1, cv2.LINE_AA)
            else:
                cv2.putText(composite, dominant_attr_str, (px_start + 14, curr_y), cv2.FONT_HERSHEY_SIMPLEX, 0.36, COLOR_WHITE_BRIGHT, 1, cv2.LINE_AA)
            curr_y += 24

            # Vector Cinemático
            cv2.putText(composite, "▲ KINEMATIC VECTOR", (px_start + 14, curr_y), cv2.FONT_HERSHEY_SIMPLEX, 0.38, COLOR_TEXT_DIM, 1, cv2.LINE_AA)
            curr_y += 18

            cardinal = heading_to_cardinal(target_focus.heading_deg)
            hdg_str = f"HEADING: {target_focus.heading_deg:.0f}° [{cardinal}]"
            vel_str = f"VELOCITY: {target_focus.velocity_px_s:.1f} px/s"
            intent_str = f"INTENT: {beh.intent}" if beh else "INTENT: TRANSITING"

            cv2.putText(composite, hdg_str, (px_start + 14, curr_y), cv2.FONT_HERSHEY_SIMPLEX, 0.35, COLOR_PLATINUM, 1, cv2.LINE_AA)
            curr_y += 16
            cv2.putText(composite, vel_str, (px_start + 14, curr_y), cv2.FONT_HERSHEY_SIMPLEX, 0.35, COLOR_PLATINUM, 1, cv2.LINE_AA)
            curr_y += 16
            cv2.putText(composite, intent_str, (px_start + 14, curr_y), cv2.FONT_HERSHEY_SIMPLEX, 0.35, COLOR_PLATINUM, 1, cv2.LINE_AA)
            curr_y += 22

            # Telemetría de Ubicación
            if geo:
                cv2.putText(composite, f"GPS: {geo.latitude:.5f}, {geo.longitude:.5f}", (px_start + 14, curr_y), cv2.FONT_HERSHEY_SIMPLEX, 0.32, COLOR_TEXT_DIM, 1, cv2.LINE_AA)
                curr_y += 15
                cv2.putText(composite, f"MGRS: {geo.mgrs_grid}", (px_start + 14, curr_y), cv2.FONT_HERSHEY_SIMPLEX, 0.32, COLOR_TEXT_DIM, 1, cv2.LINE_AA)
                curr_y += 15
                cv2.putText(composite, f"DIST SUELO: {geo.distance_ground_m:.1f} m", (px_start + 14, curr_y), cv2.FONT_HERSHEY_SIMPLEX, 0.32, COLOR_TEXT_DIM, 1, cv2.LINE_AA)
                curr_y += 20

        else:
            # Estado pasivo / escaneo cuando no hay objetivos
            cv2.putText(composite, "NO TARGETS ACQUIRED", (px_start + 14, curr_y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, COLOR_TEXT_DIM, 1, cv2.LINE_AA)
            curr_y += 20
            cv2.putText(composite, "SCANNING SECTOR...", (px_start + 14, curr_y), cv2.FONT_HERSHEY_SIMPLEX, 0.36, COLOR_TEXT_DIM, 1, cv2.LINE_AA)
            curr_y += 30
            cv2.line(composite, (px_start + 14, curr_y), (px_start + PANEL_WIDTH - 14, curr_y), COLOR_BORDER_GREY, 1)

        # Roster interactivo de objetivos conocidos (Persistencia y Selección 1-9 / TAB / Click)
        known_roster: List[Any] = list(tracked_targets)
        if target_history:
            for hid, htrg in target_history.items():
                if all(t.target_id != hid for t in known_roster):
                    known_roster.append(htrg)

        if known_roster:
            cv2.putText(composite, "▲ ROSTER [KEY 1-9 / TAB / CLICK]", (px_start + 14, curr_y), cv2.FONT_HERSHEY_SIMPLEX, 0.32, COLOR_TEXT_DIM, 1, cv2.LINE_AA)
            curr_y += 15
            roster_items = []
            for idx, r_trg in enumerate(known_roster[:5], start=1):
                marker = "*" if (focused_target_id == r_trg.target_id) else ""
                roster_items.append(f"[{idx}]{marker}{r_trg.target_id[-3:]}")
            cv2.putText(composite, " ".join(roster_items), (px_start + 14, curr_y), cv2.FONT_HERSHEY_SIMPLEX, 0.34, COLOR_PLATINUM, 1, cv2.LINE_AA)
            curr_y += 20

        # 5.3 Ficha Inferior de Inventario Táctico del Sector y Cobertura (m²)
        box_y = max(curr_y + 10, height - 120)
        composite[box_y:, px_start:] = COLOR_BLACK
        cv2.line(composite, (px_start, box_y), (px_start + PANEL_WIDTH, box_y), COLOR_BORDER_GREY, 1)

        cv2.putText(
            composite,
            "▲ SECTOR COVERAGE & INVENTORY",
            (px_start + 14, box_y + 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.38,
            COLOR_WHITE_BRIGHT,
            1,
            cv2.LINE_AA
        )

        if sector_inventory:
            area_line = f"Área encuadrada: {sector_inventory.area_m2:.1f} m²"
            dims_line = f"Sector: {sector_inventory.ground_width_m:.1f}m x {sector_inventory.ground_height_m:.1f}m"
            # Densidad extraída del resumen
            dens_line = sector_inventory.density_summary
            if "|" in dens_line:
                dens_part = dens_line.split("|")[1].strip()
            else:
                dens_part = f"Densidad: {sector_inventory.total_targets} objetivos"

            cv2.putText(composite, area_line, (px_start + 14, box_y + 40), cv2.FONT_HERSHEY_SIMPLEX, 0.35, COLOR_PLATINUM, 1, cv2.LINE_AA)
            cv2.putText(composite, dims_line, (px_start + 14, box_y + 58), cv2.FONT_HERSHEY_SIMPLEX, 0.32, COLOR_TEXT_DIM, 1, cv2.LINE_AA)
            cv2.putText(composite, dens_part, (px_start + 14, box_y + 78), cv2.FONT_HERSHEY_SIMPLEX, 0.35, COLOR_WHITE_BRIGHT, 1, cv2.LINE_AA)
        else:
            cv2.putText(composite, "Área encuadrada: -- m²", (px_start + 14, box_y + 42), cv2.FONT_HERSHEY_SIMPLEX, 0.35, COLOR_TEXT_DIM, 1, cv2.LINE_AA)
            cv2.putText(composite, "Densidad: Escaneando sector...", (px_start + 14, box_y + 64), cv2.FONT_HERSHEY_SIMPLEX, 0.33, COLOR_TEXT_DIM, 1, cv2.LINE_AA)

        return composite
