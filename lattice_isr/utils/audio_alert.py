"""
LATTICE-CORE ISR - Synthetic Audio Voice Alert Module
Generación asíncrona no bloqueante de avisos tácticos audibles usando pyttsx3.
Incluye ventana de cooldown (5.0s) para evitar saturación acústica en el puesto de mando C2.
"""

import time
import queue
import threading
from typing import Optional
from loguru import logger

from lattice_isr.config.settings import SystemSettings

try:
    import pyttsx3
    PYTTSX3_AVAILABLE = True
except ImportError:
    PYTTSX3_AVAILABLE = False


class AudioAlertManager:
    """
    Sintetizador de voz táctica en segundo plano.
    Emite avisos concisos ante incursiones perimetrales y objetivos críticos.
    """

    SPANISH_CLASS_NAMES = {
        "person": "Persona",
        "car": "Vehículo",
        "truck": "Camión",
        "bus": "Autobús",
        "motorcycle": "Motocicleta",
        "bicycle": "Bicicleta",
        "backpack": "Mochila táctica",
        "handbag": "Bolso sospechoso",
        "target": "Objetivo no identificado"
    }

    def __init__(self, settings: SystemSettings):
        self._settings = settings
        self._enabled = getattr(settings, "AUDIO_ALERTS_ENABLED", True)
        self._cooldown_seconds = getattr(settings, "AUDIO_COOLDOWN_SECONDS", 5.0)
        self._last_alert_time: float = 0.0
        self._last_alert_key: str = ""

        self._queue: queue.Queue = queue.Queue(maxsize=10)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        if self._enabled and PYTTSX3_AVAILABLE:
            self._start_worker()
        else:
            if not PYTTSX3_AVAILABLE:
                logger.warning("[AUDIO] pyttsx3 no disponible en el host. Alertas audibles en modo simulado.")

    def _start_worker(self) -> None:
        """Arranca el hilo consumidor de mensajes de voz."""
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._worker_loop,
            name="LatticeAudioWorker",
            daemon=True
        )
        self._thread.start()
        logger.info("[AUDIO] Motor de sintetizador de voz inicializado.")

    def _worker_loop(self) -> None:
        """Bucle dedicado para inicializar el motor TTS en su propio hilo OS y reproducir texto."""
        engine = None
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", 165)  # Velocidad militar clara
            engine.setProperty("volume", 0.9)
        except Exception as init_err:
            logger.debug(f"[AUDIO] No se pudo inicializar motor COM pyttsx3: {init_err}")
            engine = None

        while not self._stop_event.is_set():
            try:
                msg = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if engine is not None:
                try:
                    engine.say(msg)
                    engine.runAndWait()
                except Exception as tts_err:
                    logger.debug(f"[AUDIO] Excepción en sintetizador TTS: {tts_err}")
            else:
                logger.info(f"[AUDIO-VOICE-SIM] >>> {msg} <<<")

        if engine is not None:
            try:
                engine.stop()
            except Exception:
                pass

    def trigger_perimeter_alert(self, class_name: str, target_id: str) -> bool:
        """
        Encola un aviso hablado si ha transcurrido la ventana de cooldown.
        Retorna True si la alerta fue encolada, False si fue bloqueada por cooldown.
        """
        if not self._enabled:
            return False

        now = time.monotonic()
        alert_key = f"{class_name}:{target_id}"

        # Cooldown global y por objetivo
        if (now - self._last_alert_time) < self._cooldown_seconds:
            return False

        self._last_alert_time = now
        self._last_alert_key = alert_key

        translated_class = self.SPANISH_CLASS_NAMES.get(class_name.lower(), class_name.capitalize())
        message_text = f"Alerta táctica: {translated_class} detectado en zona restringida."

        logger.warning(f"[AUDIO-ALERT] Emisión de aviso por voz: '{message_text}'")

        try:
            self._queue.put_nowait(message_text)
            return True
        except queue.Full:
            return False

    def close(self) -> None:
        """Detiene de forma limpia el hilo de audio."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
