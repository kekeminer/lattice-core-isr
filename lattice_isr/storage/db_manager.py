"""
LATTICE-CORE ISR - Embedded Edge Relational Database (SQLite)
Registro asíncrono y reconstrucción analítica posterior a la misión (After Action Review).
"""

import queue
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from loguru import logger

from lattice_isr.config.settings import SystemSettings


class DatabaseError(Exception):
    """Excepción del subsistema de persistencia en base de datos."""
    pass


class TelemetryRecord(BaseModel):
    """Registro inmutable de telemetría táctica para almacenamiento analítico."""
    timestamp: float
    iso_time: str
    target_id: str
    latitude: float
    longitude: float
    altitude_m: float
    heading_deg: float
    velocity_px_s: float
    area_px: int
    threat_level: str
    geofence_status: str
    behavior_intent: str
    mgrs_grid: str


class EmbeddedDatabaseManager:
    """
    Gestor de base de datos embebida SQLite de alto rendimiento y bajo consumo de memoria (< 5 MB).
    Las escrituras se canalizan a través de una cola en memoria con un hilo dedicado para I/O no bloqueante.
    """

    def __init__(self, settings: SystemSettings):
        self._settings = settings
        self._db_path = settings.DB_PATH.resolve()

        # Cola de inserción asíncrona desacoplada
        self._write_queue: queue.Queue = queue.Queue(maxsize=1000)
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

        self._init_database_schema()
        self._start_worker()

    def _init_database_schema(self) -> None:
        """Crea las tablas y los índices analíticos requeridos."""
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(str(self._db_path)) as conn:
                cursor = conn.cursor()
                # Optimización de rendimiento para almacenamiento Edge
                cursor.execute("PRAGMA journal_mode = WAL;")
                cursor.execute("PRAGMA synchronous = NORMAL;")

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS telemetry_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp REAL NOT NULL,
                        iso_time TEXT NOT NULL,
                        target_id TEXT NOT NULL,
                        latitude REAL NOT NULL,
                        longitude REAL NOT NULL,
                        altitude_m REAL NOT NULL,
                        heading_deg REAL NOT NULL,
                        velocity_px_s REAL NOT NULL,
                        area_px INTEGER NOT NULL,
                        threat_level TEXT NOT NULL,
                        geofence_status TEXT NOT NULL,
                        behavior_intent TEXT NOT NULL,
                        mgrs_grid TEXT NOT NULL
                    );
                """)

                # Índices para acelerar consultas analíticas de After Action Review
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_target ON telemetry_events (target_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_time ON telemetry_events (timestamp);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_breach ON telemetry_events (geofence_status);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_threat ON telemetry_events (threat_level);")
                conn.commit()

            logger.info(f"[DATABASE] Base de datos SQLite embebida inicializada en: {self._db_path}")

        except sqlite3.Error as err:
            logger.error(f"[DATABASE-ERR] Error inicializando esquema SQLite: {err}")
            raise DatabaseError(f"Fallo al inicializar base de datos: {err}") from err

    def _start_worker(self) -> None:
        """Inicia el hilo de escritura asíncrona por lotes."""
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._writer_loop,
            name="LatticeDbWriterThread",
            daemon=True
        )
        self._worker_thread.start()

    def record_event_async(self, record: TelemetryRecord) -> None:
        """Encola un registro de telemetría de forma no bloqueante."""
        try:
            self._write_queue.put_nowait(record)
        except queue.Full:
            # Si la cola se satura por I/O extremadamente lento, descartar el más viejo para no congelar la RAM
            try:
                self._write_queue.get_nowait()
                self._write_queue.put_nowait(record)
            except queue.Empty:
                pass

    def _writer_loop(self) -> None:
        """Bucle consumidor que ejecuta transacciones por lotes periódicas."""
        batch: List[TelemetryRecord] = []
        batch_size = 25
        last_flush = time.monotonic()

        while not self._stop_event.is_set():
            try:
                # Esperar registro con timeout
                item = self._write_queue.get(timeout=0.2)
                batch.append(item)
            except queue.Empty:
                pass

            now = time.monotonic()
            # Flush si el lote alcanza el tamaño o pasó más de 0.5 segundo
            if len(batch) >= batch_size or (len(batch) > 0 and (now - last_flush) >= 0.5):
                self._flush_batch(batch)
                batch.clear()
                last_flush = now

        # Flush final al cerrar: vaciar lo que haya en batch y lo que quede en la cola
        while not self._write_queue.empty():
            try:
                batch.append(self._write_queue.get_nowait())
            except queue.Empty:
                break

        if batch:
            self._flush_batch(batch)
            batch.clear()

    def flush(self) -> None:
        """Fuerza la persistencia síncrona inmediata de todos los elementos encolados."""
        batch: List[TelemetryRecord] = []
        while not self._write_queue.empty():
            try:
                batch.append(self._write_queue.get_nowait())
            except queue.Empty:
                break
        if batch:
            self._flush_batch(batch)
            batch.clear()

    def _flush_batch(self, batch: List[TelemetryRecord]) -> None:
        """Escribe un lote en disco en una única transacción atómica."""
        if not batch:
            return
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                cursor = conn.cursor()
                cursor.executemany("""
                    INSERT INTO telemetry_events (
                        timestamp, iso_time, target_id, latitude, longitude, altitude_m,
                        heading_deg, velocity_px_s, area_px, threat_level, geofence_status,
                        behavior_intent, mgrs_grid
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, [
                    (
                        r.timestamp, r.iso_time, r.target_id, r.latitude, r.longitude, r.altitude_m,
                        r.heading_deg, r.velocity_px_s, r.area_px, r.threat_level, r.geofence_status,
                        r.behavior_intent, r.mgrs_grid
                    )
                    for r in batch
                ])
                conn.commit()
        except sqlite3.Error as err:
            logger.error(f"[DATABASE-ERR] Fallo al insertar lote de telemetría: {err}")

    # =========================================================================
    # Consultas Analíticas: After Action Review (AAR)
    # =========================================================================

    def query_mission_summary(self) -> Dict[str, Any]:
        """Devuelve un informe cuantitativo de la misión táctica."""
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                cursor.execute("SELECT COUNT(*) AS total_records FROM telemetry_events;")
                total_records = cursor.fetchone()["total_records"]

                cursor.execute("SELECT COUNT(DISTINCT target_id) AS total_targets FROM telemetry_events;")
                total_targets = cursor.fetchone()["total_targets"]

                cursor.execute("SELECT COUNT(*) AS breaches FROM telemetry_events WHERE geofence_status = 'PERIMETER_BREACH';")
                breaches = cursor.fetchone()["breaches"]

                cursor.execute("""
                    SELECT behavior_intent, COUNT(*) AS count
                    FROM telemetry_events
                    GROUP BY behavior_intent;
                """)
                intents = {row["behavior_intent"]: row["count"] for row in cursor.fetchall()}

                return {
                    "total_telemetry_records": total_records,
                    "distinct_targets_tracked": total_targets,
                    "perimeter_breaches_logged": breaches,
                    "intent_distribution": intents
                }
        except sqlite3.Error as err:
            logger.error(f"[DATABASE-ERR] Fallo consultando resumen de misión: {err}")
            return {}

    def query_target_history(self, target_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        """Obtiene la trayectoria histórica y cinemática de un objetivo específico."""
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT iso_time, latitude, longitude, heading_deg, velocity_px_s,
                           threat_level, geofence_status, behavior_intent
                    FROM telemetry_events
                    WHERE target_id = ?
                    ORDER BY timestamp ASC
                    LIMIT ?;
                """, (target_id, limit))
                return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as err:
            logger.error(f"[DATABASE-ERR] Error consultando histórico del objetivo {target_id}: {err}")
            return []

    def close(self) -> None:
        """Detiene el hilo de escritura y asegura que todos los datos pendientes se guarden."""
        logger.info("[DATABASE] Finalizando conexiones y volcando buffers a disco...")
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
        logger.info("[DATABASE] Base de datos SQLite sincronizada y cerrada.")
