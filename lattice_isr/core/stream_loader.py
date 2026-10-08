"""
LATTICE-CORE ISR - Resilient Edge Video Stream Ingestion
Ingesta asíncrona mediante hilo desacoplado, gestión estricta del ciclo de vida de frames
OpenCV para cumplir el límite de memoria (< 100 MB RAM), y reconexión autónoma con Exponential Backoff.
"""

import time
import queue
import threading
from typing import Optional, Tuple
import cv2
import numpy as np
from loguru import logger

from lattice_isr.config.settings import SystemSettings
from lattice_isr.core.security import StreamSecurityValidator, SecurityBaseException


class StreamBaseException(Exception):
    """Excepción base para fallos del subsistema de streaming."""
    pass


class StreamConnectionError(StreamBaseException):
    """Fallo al abrir o mantener la conexión con el stream táctico."""
    pass


class StreamDecodeError(StreamBaseException):
    """El frame recibido está corrupto o no se pudo decodificar."""
    pass


class AsyncStreamLoader:
    """
    Ingestor de video no bloqueante con control de flujo y recolección de basura estricta.
    Diseñado para estaciones con restricción severa de memoria (< 100 MB RAM).
    """

    def __init__(self, settings: SystemSettings):
        self._settings = settings
        self._raw_url = settings.STREAM_URL
        self._sanitized_url: Optional[str] = None

        # Buffer circular FIFO con descarte de cuadros más viejos
        self._buffer: queue.Queue = queue.Queue(maxsize=self._settings.FRAME_BUFFER_SIZE)

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Telemetría interna y buffer suave de reconexión
        self._is_connected = False
        self._fps = 0.0
        self._dropped_frames = 0
        self._total_frames = 0
        self._reconnect_attempts = 0
        self._last_frame_timestamp = 0.0
        self._last_valid_frame: Optional[np.ndarray] = None
        self._last_valid_frame_time: float = 0.0
        self._soft_buffer_seconds: float = 1.5

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._is_connected

    @property
    def fps(self) -> float:
        with self._lock:
            return self._fps

    @property
    def dropped_frames(self) -> int:
        with self._lock:
            return self._dropped_frames

    @property
    def total_frames(self) -> int:
        with self._lock:
            return self._total_frames

    def start(self) -> None:
        """Inicializa la validación de seguridad y arranca el hilo recolector."""
        try:
            self._sanitized_url = StreamSecurityValidator.sanitize_and_validate_stream_url(
                self._raw_url,
                allow_local_only=self._settings.ALLOW_LOCAL_NETWORK_ONLY
            )
            logger.info(f"[STREAM] Endpoint táctico validado contra SSRF: {self._sanitized_url}")
        except SecurityBaseException as sec_err:
            logger.error(f"[STREAM-SEC-ALERT] Fallo en la validación del stream: {sec_err}")
            raise StreamConnectionError(f"Validación de seguridad denegada: {sec_err}") from sec_err

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._worker_loop,
            name="LatticeStreamWorker",
            daemon=True
        )
        self._thread.start()
        logger.info("[STREAM] Hilo de ingesta de video iniciado en segundo plano.")

    def stop(self) -> None:
        """Detiene de forma segura el hilo de ingesta y vacía matrices para el GC."""
        logger.info("[STREAM] Solicitando parada segura de ingesta...")
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)

        with self._lock:
            self._is_connected = False
            self._last_valid_frame = None

        # Liberar explícitamente todas las referencias de memoria de matrices en la cola
        while not self._buffer.empty():
            try:
                frame_to_free = self._buffer.get_nowait()
                del frame_to_free
            except queue.Empty:
                break
        logger.info("[STREAM] Stream worker detenido y memoria de frames liberada.")

    def read(self, timeout: float = 0.05) -> Tuple[bool, Optional[np.ndarray]]:
        """
        Devuelve siempre el frame MÁS RECIENTE disponible (Zero Latency 60 FPS Strategy).
        Drena proactivamente cuadros viejos acumulados en la cola para eliminar retardos.
        Si la red sufre una micro-desconexión, retiene el último frame válido durante 1.5s
        para evitar parpadeos visuales en la pantalla táctica.
        """
        now = time.monotonic()
        try:
            latest_frame = self._buffer.get(block=True, timeout=timeout)
            # Drenar agresivamente cuadros intermedios acumulados para entregar únicamente el más reciente
            while not self._buffer.empty():
                try:
                    newer_frame = self._buffer.get_nowait()
                    del latest_frame
                    latest_frame = newer_frame
                    with self._lock:
                        self._dropped_frames += 1
                except queue.Empty:
                    break

            with self._lock:
                self._last_valid_frame = latest_frame
                self._last_valid_frame_time = now

            return True, latest_frame
        except queue.Empty:
            # Buffer suave: retener último frame válido hasta 1.5s durante micro-cortes
            with self._lock:
                if self._last_valid_frame is not None and (now - self._last_valid_frame_time) <= self._soft_buffer_seconds:
                    return True, self._last_valid_frame.copy()
            return False, None

    def _worker_loop(self) -> None:
        """
        Bucle de trabajo OpenCV resiliente con timeouts explícitos de socket,
        tolerancia a fluctuaciones Wi-Fi y descarte inmediato de tramas obsoletas.
        """
        delay = self._settings.RECONNECT_INITIAL_DELAY
        max_delay = self._settings.RECONNECT_MAX_DELAY
        factor = self._settings.RECONNECT_BACKOFF_FACTOR
        timeout_ms = int(self._settings.STREAM_TIMEOUT_SECONDS * 1000)

        while not self._stop_event.is_set():
            cap: Optional[cv2.VideoCapture] = None
            try:
                logger.info(f"[STREAM] Abriendo socket de video con timeout ({timeout_ms}ms): {self._sanitized_url}")
                cap = cv2.VideoCapture(self._sanitized_url, cv2.CAP_ANY)

                # Configuración de timeouts de apertura y lectura a nivel OpenCV / FFmpeg
                if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
                    cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, timeout_ms)
                if hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
                    cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, timeout_ms)

                # Optimización de buffer interno OpenCV (cero latencia)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

                if not cap.isOpened():
                    raise StreamConnectionError(f"No fue posible abrir el flujo de video: {self._sanitized_url}")

                with self._lock:
                    self._is_connected = True
                    self._reconnect_attempts = 0
                delay = self._settings.RECONNECT_INITIAL_DELAY
                logger.info("[STREAM] Enlace de video establecido con el dispositivo Edge.")

                fps_count = 0
                fps_timer = time.monotonic()
                last_active_time = time.monotonic()

                while not self._stop_event.is_set():
                    ret, frame = cap.read()
                    now = time.monotonic()

                    if not ret or frame is None:
                        # Si es un micro-corte temporal menor al timeout, reintentar silenciosamente sin reiniciar socket
                        if now - last_active_time > self._settings.STREAM_TIMEOUT_SECONDS:
                            raise StreamConnectionError(
                                f"Inactividad de socket superior a {self._settings.STREAM_TIMEOUT_SECONDS}s."
                            )
                        time.sleep(0.015)
                        continue

                    last_active_time = now

                    # Vaciado agresivo de buffer (Zero-Latency Frame Dropping)
                    # Si el buffer contiene más de 1 fotograma acumulado o está lleno, descarta los cuadros anteriores
                    while self._buffer.qsize() >= 1:
                        try:
                            old_frame = self._buffer.get_nowait()
                            del old_frame
                            with self._lock:
                                self._dropped_frames += 1
                        except queue.Empty:
                            break

                    self._buffer.put_nowait(frame)

                    with self._lock:
                        self._total_frames += 1
                        self._last_frame_timestamp = now

                    # Cálculo de FPS
                    fps_count += 1
                    if now - fps_timer >= 1.0:
                        with self._lock:
                            self._fps = round(fps_count / (now - fps_timer), 1)
                        fps_count = 0
                        fps_timer = now

            except (cv2.error, StreamConnectionError, OSError) as err:
                with self._lock:
                    self._is_connected = False
                    self._reconnect_attempts += 1

                logger.warning(
                    f"[STREAM-DOWN] Micro-corte o pérdida de señal ({type(err).__name__}: {err}). "
                    f"Reintentando conexión ({self._reconnect_attempts}) en {delay:.1f}s..."
                )

                sleep_chunk = 0.2
                elapsed = 0.0
                while elapsed < delay and not self._stop_event.is_set():
                    time.sleep(sleep_chunk)
                    elapsed += sleep_chunk

                delay = min(delay * factor, max_delay)

            finally:
                if cap is not None:
                    try:
                        cap.release()
                    except Exception as cap_err:
                        logger.debug(f"[STREAM] Excepción controlada al liberar VideoCapture: {cap_err}")
