"""
LATTICE-CORE ISR - Tactical Edge Recognition, Geolocation & C2 Platform
Entrypoint Principal y Orquestador de Mando y Control C2.
"""

import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
import cv2
import numpy as np
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from lattice_isr.config.settings import get_settings
from lattice_isr.utils.logger import setup_logger, logger
from lattice_isr.utils.system_health import SystemHealthMonitor
from lattice_isr.core.stream_loader import AsyncStreamLoader, StreamConnectionError
from lattice_isr.engine.thermal_processor import ThermalProcessor, ThermalProcessingError
from lattice_isr.engine.object_detector import ThermalObjectDetector, DetectionProcessingError
from lattice_isr.engine.target_tracker import TargetTrackerManager, TrackerBaseException
from lattice_isr.engine.geolocation_engine import TargetGeocoder, TargetGeoPosition
from lattice_isr.engine.geofence_engine import GeofenceManager
from lattice_isr.engine.behavior_analyzer import BehaviorAnalyzer
from lattice_isr.network.web_bridge import WebBridgeServer
from lattice_isr.storage.obsidian_exporter import ObsidianExporter
from lattice_isr.storage.db_manager import EmbeddedDatabaseManager, TelemetryRecord
from lattice_isr.storage.video_recorder import VideoClipRecorder
from lattice_isr.utils.audio_alert import AudioAlertManager

console = Console()


def print_tactical_banner() -> None:
    """Imprime el banner del centro de mando ISR monocromático."""
    grid = Table.grid(expand=True)
    grid.add_column(justify="center", ratio=1)
    grid.add_row(
        "[bold white]▲ LATTICE-CORE ISR // TACTICAL C2 & AUTONOMOUS RECOGNITION ▲[/bold white]"
    )
    grid.add_row(
        "[dim white]Monochrome HUD (White/Black Hot) | Geofence Defense | Intent Analyzer[/dim white]"
    )
    grid.add_row(
        "[bold white]SQLite Embedded Edge DB • Authenticated WebSockets • Health Telemetry (<100MB RAM)[/bold white]"
    )
    console.print(Panel(grid, border_style="white"))


def run_orchestrator(stream_override: Optional[str] = None) -> None:
    """
    Bucle principal de orquestación de LATTICE-CORE ISR.
    """
    settings = get_settings()
    if stream_override:
        settings.STREAM_URL = stream_override

    # 1. Configurar Logger Estructurado Empresarial
    setup_logger(
        log_level=settings.LOG_LEVEL,
        json_format=settings.LOG_JSON_FORMAT,
        log_dir="logs"
    )

    print_tactical_banner()
    logger.info(f"[BOOT] Inicializando subsistemas C2 para: {settings.SOURCE_DEVICE_NAME}")
    logger.info(f"[BOOT] Endpoint de streaming: {settings.STREAM_URL}")
    logger.info(f"[BOOT] Base de datos embebida: {settings.DB_PATH}")

    # 2. Inicializar subsistemas modulares
    stream_loader = AsyncStreamLoader(settings)
    thermal_processor = ThermalProcessor(palette=settings.THERMAL_PALETTE)
    object_detector = ThermalObjectDetector(settings)
    target_tracker = TargetTrackerManager(settings)
    target_geocoder = TargetGeocoder(settings)
    geofence_manager = GeofenceManager(settings)
    behavior_analyzer = BehaviorAnalyzer(settings)
    obsidian_exporter = ObsidianExporter(settings)
    db_manager = EmbeddedDatabaseManager(settings)
    health_monitor = SystemHealthMonitor()
    video_recorder = VideoClipRecorder(settings)
    audio_alert_manager = AudioAlertManager(settings)

    # 3. Inicializar Servidor Web Bridge (FastAPI + WebSockets)
    web_bridge: Optional[WebBridgeServer] = None
    if settings.WEB_ENABLED:
        try:
            web_bridge = WebBridgeServer(settings)
            web_bridge.start()
        except Exception as web_err:
            logger.error(f"[BOOT-WARN] No fue posible iniciar Web Bridge: {web_err}")

    # 4. Tarjeta visual out-of-the-box para el operador
    web_url_direct = f"http://{settings.WEB_HOST}:{settings.WEB_PORT}?token={settings.API_AUTH_TOKEN}"
    vault_display_path = "./obsidian_vault/recon_reports/"
    
    launch_card = (
        "[bold green]✔ SISTEMA LISTO PARA OPERAR CON IA Y SENSOR RGB[/bold green]\n\n"
        f"[bold white]🌐 Dashboard Web en Vivo:[/bold white] [bold cyan underline]{web_url_direct}[/bold cyan underline]\n"
        f"[bold white]📁 Bóveda Obsidian (Vault):[/bold white] [bold yellow]{vault_display_path}[/bold yellow]\n"
        f"[bold white]🤖 Modelo Neuronal:[/bold white] [bold magenta]YOLOv8n (Multiclase Táctica)[/bold magenta]\n"
        f"[bold white]🔊 Avisos por Voz:[/bold white] [bold green]Activados (pyttsx3)[/bold green]\n\n"
        "[dim]ℹ Al instalar Obsidian: Selecciona la carpeta 'obsidian_vault' como tu Vault local para ver todos los reportes y clips.[/dim]"
    )
    console.print(Panel(launch_card, title="[bold white]ACCESO RÁPIDO Y TELEMETRÍA TÁCTICA ISR[/bold white]", border_style="green"))

    # 4. Estado de la sesión de mando (Modo Color RGB Principal por Defecto)
    display_mode = "RGB_HUD"  # 'RGB_HUD' (Color Real Principal), 'THERMAL_HUD', 'SPLIT', 'RAW'
    auto_alert_cooldown_seconds = 4.0
    last_auto_alert_time = 0.0

    try:
        stream_loader.start()
    except StreamConnectionError as conn_err:
        logger.critical(f"[ABORT] Fallo al iniciar el stream: {conn_err}")
        if web_bridge:
            web_bridge.stop()
        db_manager.close()
        return

    window_name = "LATTICE-CORE ISR // TACTICAL C2 GCS"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    # Incluir 300px adicionales para el Side Inspector Panel
    cv2.resizeWindow(window_name, settings.FRAME_WIDTH + 300, settings.FRAME_HEIGHT)

    # Iniciar inferencia neuronal asíncrona para garantizar 60 FPS ininterrumpidos
    object_detector.start_async_worker()

    # Estado interactivo de Selección y Bloqueo de Objetivos (Target Lock)
    locked_target_id: Optional[str] = None

    def on_mouse_event(event: int, x: int, y: int, flags: int, param: Any) -> None:
        """Callback de mouse para seleccionar o desbloquear objetivos tácticos."""
        nonlocal locked_target_id
        if event == cv2.EVENT_LBUTTONDOWN:
            # Si se hace clic en el área de video principal
            if x < settings.FRAME_WIDTH:
                # Buscar si el clic cae dentro de una bounding box de un objetivo activo o el más cercano
                all_targets = target_tracker.get_all_known_targets()
                clicked_target = None
                min_dist = float("inf")
                for trg in all_targets:
                    x1 = trg.bbox_x
                    y1 = trg.bbox_y
                    x2 = trg.bbox_x + trg.bbox_w
                    y2 = trg.bbox_y + trg.bbox_h
                    if x1 <= x <= x2 and y1 <= y <= y2:
                        clicked_target = trg.target_id
                        break
                    # Medir distancia al centroide
                    dist = ((x - trg.centroid_x) ** 2 + (y - trg.centroid_y) ** 2) ** 0.5
                    if dist < min_dist and dist < 120:  # Radio de tolerancia 120px
                        min_dist = dist
                        clicked_target = trg.target_id

                if clicked_target:
                    locked_target_id = clicked_target
                    logger.info(f"[TARGET-LOCK] Objetivo fijado manualmente (Click): {locked_target_id}")
                else:
                    # Clic en vacío deselecciona
                    locked_target_id = None
                    logger.info("[TARGET-LOCK] Bloqueo liberado (Click en espacio libre).")
            else:
                # Clic en el panel lateral: ciclar selección
                roster = target_tracker.get_all_known_targets()
                if roster:
                    idx = 0
                    if locked_target_id:
                        ids = [t.target_id for t in roster]
                        if locked_target_id in ids:
                            idx = (ids.index(locked_target_id) + 1) % len(ids)
                    locked_target_id = roster[idx].target_id
                    logger.info(f"[TARGET-LOCK] Objetivo ciclado desde panel: {locked_target_id}")

        elif event == cv2.EVENT_RBUTTONDOWN:
            locked_target_id = None
            logger.info("[TARGET-LOCK] Bloqueo liberado (Click derecho).")

    cv2.setMouseCallback(window_name, on_mouse_event)

    logger.info("[COMMAND] Modo Activo: COLOR RGB PRINCIPAL (60 FPS + ASYNC YOLO + SIDE INSPECTOR).")
    logger.info("[COMMAND] Controles: [1-9] Seleccionar Target | [TAB] Alternar Target | [0/U] Desbloquear | [Click] Lock/Unlock")
    logger.info("[COMMAND] Atajos: [D] Modo de Vista | [B] Paleta Térmica | [S] Snapshot | [Q] Salir")

    frame_counter = 0
    inference_cadence = getattr(settings, "INFERENCE_CADENCE", 3)
    tracked_targets: list = []
    active_frame: Optional[np.ndarray] = None
    # Estabilizador de FPS en rango 30 - 60 FPS Target (16.6ms min a 33.3ms max)
    target_frame_interval = 1.0 / 60.0  # 16.6 ms (60 FPS objetivo)
    max_frame_interval = 1.0 / 30.0     # 33.3 ms (30 FPS suelo de estabilidad)

    try:
        while True:
            loop_start = time.perf_counter()
            has_new_frame, raw_frame = stream_loader.read(timeout=0.002)

            now_mono = time.monotonic()
            timestamp_id = datetime.now().strftime("%Y%m%d-%H%M%S")
            iso_now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

            if raw_frame is not None:
                # Ajuste de tamaño táctico estándar para display
                if raw_frame.shape[1] != settings.FRAME_WIDTH or raw_frame.shape[0] != settings.FRAME_HEIGHT:
                    active_frame = cv2.resize(raw_frame, (settings.FRAME_WIDTH, settings.FRAME_HEIGHT))
                else:
                    active_frame = raw_frame
                if has_new_frame:
                    frame_counter += 1

            if active_frame is None:
                waiting_canvas = np.zeros((settings.FRAME_HEIGHT, settings.FRAME_WIDTH + 300, 3), dtype=np.uint8)
                status_msg = "ENLACE RECONECTANDO..." if not stream_loader.is_connected else "BUSCANDO TRAMAS (MJPEG DRAIN)..."
                cv2.putText(
                    waiting_canvas,
                    f"▲ LATTICE-CORE ISR: {status_msg}",
                    (60, settings.FRAME_HEIGHT // 2),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (220, 220, 220),
                    2,
                    cv2.LINE_AA
                )
                cv2.putText(
                    waiting_canvas,
                    f"Sensor: {settings.SOURCE_DEVICE_NAME} | URI: {settings.STREAM_URL}",
                    (60, (settings.FRAME_HEIGHT // 2) + 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.50,
                    (150, 150, 150),
                    1,
                    cv2.LINE_AA
                )
                cv2.imshow(window_name, waiting_canvas)
                key = cv2.waitKey(10) & 0xFF
                if key in (ord('q'), ord('Q'), 27):
                    break
                continue

            try:
                # 5. Muestreo de Salud del Sistema (RAM <250MB, CPU, FPS)
                health_metrics = health_monitor.sample(stream_loader.fps)

                # Registrar frame en buffer circular de video para clips de evidencia
                if settings.VIDEO_CLIP_ENABLED and has_new_frame:
                    video_recorder.push_frame(active_frame, stream_loader.fps)

                # 6. Pipeline Térmico Monocromático con buffers preasignados
                thermal_rendered, detection_gray = thermal_processor.process_frame(active_frame)

                # 7. Submuestreo Asíncrono de Inferencia (Cadencia cada 3 fotogramas de cámara para 60 FPS sostenidos)
                is_inference_turn = (frame_counter == 1) or (frame_counter % inference_cadence == 0)

                inf_w = settings.INFERENCE_WIDTH
                inf_h = settings.INFERENCE_HEIGHT

                if has_new_frame and is_inference_turn:
                    inf_rgb = cv2.resize(active_frame, (inf_w, inf_h), interpolation=cv2.INTER_LINEAR)
                    inf_gray = cv2.resize(detection_gray, (inf_w, inf_h), interpolation=cv2.INTER_LINEAR)
                    # Enviar frame al worker asíncrono de YOLOv8
                    raw_inf_detections = object_detector.detect_objects(
                        frame_rgb=inf_rgb,
                        base_timestamp_id=timestamp_id,
                        gray_fallback=inf_gray,
                        async_mode=True
                    )
                else:
                    # En frames intermedios, recuperar inmediatamente las detecciones más recientes del worker
                    raw_inf_detections = object_detector.get_latest_detections()

                # Reescalar coordenadas de detección al tamaño real de visualización
                scale_x = settings.FRAME_WIDTH / float(inf_w)
                scale_y = settings.FRAME_HEIGHT / float(inf_h)
                raw_detections = []
                for d in raw_inf_detections:
                    scaled_d = d.model_copy(update={
                        "bbox_x": int(d.bbox_x * scale_x),
                        "bbox_y": int(d.bbox_y * scale_y),
                        "bbox_w": int(d.bbox_w * scale_x),
                        "bbox_h": int(d.bbox_h * scale_y),
                        "centroid_x": int(d.centroid_x * scale_x),
                        "centroid_y": int(d.centroid_y * scale_y),
                        "area_px": int(d.area_px * (scale_x * scale_y))
                    })
                    raw_detections.append(scaled_d)

                # 8. Seguimiento Continuo de Objetivos (Centroid Tracking & Motion Vectors)
                if raw_detections:
                    tracked_targets = target_tracker.update(raw_detections, now_mono)
                else:
                    # Interpolación cinemática continua cuando no hay nuevas detecciones en el tick
                    tracked_targets = target_tracker.extrapolate_kinematics(now_mono)

                # 9. Estimación Geoespacial (GPS, MGRS, UTM) e Inventario Semántico de Terreno (m²)
                geo_positions: Dict[str, TargetGeoPosition] = {}
                for trg in tracked_targets:
                    geo_pos = target_geocoder.estimate_target_position(
                        target_id=trg.target_id,
                        centroid_x=trg.centroid_x,
                        centroid_y=trg.centroid_y,
                        frame_width=settings.FRAME_WIDTH,
                        frame_height=settings.FRAME_HEIGHT
                    )
                    geo_positions[trg.target_id] = geo_pos

                # Ficha de inventario táctico y área visible del terreno encuadrado
                sector_inventory = target_geocoder.calculate_sector_inventory(tracked_targets)

                # 10. Evaluación de Perímetro y Geofencing (con filtro semántico de clases críticas)
                geofence_statuses = geofence_manager.evaluate_batch(geo_positions, tracked_targets)

                # 11. Análisis de Conducta e Intención (Behavior Analyzer)
                behaviors = behavior_analyzer.analyze_batch(
                    tracked_targets,
                    geo_positions,
                    frame_width=settings.FRAME_WIDTH,
                    frame_height=settings.FRAME_HEIGHT
                )

                # 12. Persistencia en Base de Datos Embebida SQLite (Asíncrona)
                for trg in tracked_targets:
                    gp = geo_positions.get(trg.target_id)
                    gf = geofence_statuses.get(trg.target_id)
                    bh = behaviors.get(trg.target_id)
                    if gp and gf and bh:
                        record = TelemetryRecord(
                            timestamp=time.time(),
                            iso_time=iso_now,
                            target_id=trg.target_id,
                            latitude=gp.latitude,
                            longitude=gp.longitude,
                            altitude_m=gp.altitude_m,
                            heading_deg=trg.heading_deg,
                            velocity_px_s=trg.velocity_px_s,
                            area_px=trg.area_px,
                            threat_level=trg.threat_level,
                            geofence_status=gf.status,
                            behavior_intent=bh.intent,
                            mgrs_grid=gp.mgrs_grid
                        )
                        db_manager.record_event_async(record)

                # 13. Transmisión de Telemetría al Web Bridge (WebSockets)
                if web_bridge:
                    ws_payload: List[Dict[str, Any]] = []
                    for trg in tracked_targets:
                        gp = geo_positions.get(trg.target_id)
                        gf = geofence_statuses.get(trg.target_id)
                        bh = behaviors.get(trg.target_id)
                        if gp and gf and bh:
                            ws_payload.append({
                                "target_id": trg.target_id,
                                "lat": gp.latitude,
                                "lon": gp.longitude,
                                "altitude_m": gp.altitude_m,
                                "heading_deg": trg.heading_deg,
                                "velocity_px_s": trg.velocity_px_s,
                                "threat_level": trg.threat_level,
                                "geofence_status": gf.status,
                                "distance_to_base_m": gf.distance_to_base_m,
                                "behavior_intent": bh.intent,
                                "mgrs": gp.mgrs_grid
                            })
                    web_bridge.update_telemetry(ws_payload, stream_loader.fps)

                # 14. Alerta de Invasión de Perímetro (PERIMETER_BREACH sostenido >3s de clase crítica) con cooldown
                breaching_targets = [trg for trg in tracked_targets if geofence_statuses.get(trg.target_id) and geofence_statuses[trg.target_id].qualifies_for_export]
                has_sustained_breach = len(breaching_targets) > 0

                if has_sustained_breach and (now_mono - last_auto_alert_time > auto_alert_cooldown_seconds):
                    last_auto_alert_time = now_mono
                    lead_breach = breaching_targets[0]
                    lead_class = getattr(lead_breach, "class_name", "target")

                    # 14.1 Alerta de Voz Sintetizada No Bloqueante
                    if settings.AUDIO_ALERTS_ENABLED:
                        audio_alert_manager.trigger_perimeter_alert(lead_class, lead_breach.target_id)

                    # 14.2 Grabación Automática de Clip Forense de Video (5s)
                    evidence_clip_path = None
                    if settings.VIDEO_CLIP_ENABLED:
                        evidence_clip_path = video_recorder.record_evidence_clip(lead_breach.target_id)

                    # 14.3 Persistencia de Auditoría en Obsidian Vault
                    if settings.GEOFENCE_ALERT_AUTO_EXPORT:
                        logger.warning(f"[GEOFENCE-BREACH-TRIGGER] Disparando auditoría Obsidian para {lead_breach.target_id} [{lead_class}]...")
                        hud_for_export = object_detector.render_tactical_hud(
                            active_frame,
                            tracked_targets,
                            geo_positions,
                            geofence_statuses,
                            behaviors,
                            stream_loader.fps,
                            settings.SOURCE_DEVICE_NAME,
                            "RGB_TACTICAL",
                            health_metrics=health_metrics,
                            sector_inventory=sector_inventory,
                            raw_sensor_frame=active_frame,
                            focused_target_id=locked_target_id,
                            target_history=target_tracker.get_target_history()
                        )
                        obsidian_exporter.export_recon_event_async(
                            hud_for_export,
                            tracked_targets,
                            geo_positions,
                            geofence_statuses,
                            behaviors,
                            manual_trigger=False,
                            video_clip_path=evidence_clip_path
                        )

                # 15. Renderizado Táctico Adaptativo: Modo Color RGB Principal y Modos Secundarios
                mode_str = "RGB_TACTICAL" if "RGB" in display_mode else thermal_processor.current_palette.value
                base_canvas = active_frame if display_mode in ("RGB_HUD", "RAW") else thermal_rendered

                hud_view = object_detector.render_tactical_hud(
                    base_canvas,
                    tracked_targets,
                    geo_positions,
                    geofence_statuses,
                    behaviors,
                    stream_loader.fps,
                    settings.SOURCE_DEVICE_NAME,
                    mode_str,
                    health_metrics=health_metrics,
                    sector_inventory=sector_inventory,
                    raw_sensor_frame=active_frame,
                    focused_target_id=locked_target_id,
                    target_history=target_tracker.get_target_history()
                )

                # Composición según el modo de visualización seleccionado
                if display_mode == "RGB_HUD":
                    final_view = hud_view
                elif display_mode == "THERMAL_HUD":
                    final_view = object_detector.render_tactical_hud(
                        thermal_rendered,
                        tracked_targets,
                        geo_positions,
                        geofence_statuses,
                        behaviors,
                        stream_loader.fps,
                        settings.SOURCE_DEVICE_NAME,
                        thermal_processor.current_palette.value,
                        health_metrics=health_metrics,
                        sector_inventory=sector_inventory,
                        raw_sensor_frame=active_frame,
                        focused_target_id=locked_target_id,
                        target_history=target_tracker.get_target_history()
                    )
                elif display_mode == "RAW":
                    final_view = active_frame
                elif display_mode == "SPLIT":
                    half_w = settings.FRAME_WIDTH // 2
                    raw_base = object_detector.render_tactical_hud(
                        active_frame,
                        tracked_targets,
                        geo_positions,
                        geofence_statuses,
                        behaviors,
                        stream_loader.fps,
                        settings.SOURCE_DEVICE_NAME,
                        "RGB_TACTICAL",
                        health_metrics=health_metrics,
                        attach_side_panel=False,
                        focused_target_id=locked_target_id,
                        target_history=target_tracker.get_target_history()
                    )
                    therm_base = object_detector.render_tactical_hud(
                        thermal_rendered,
                        tracked_targets,
                        geo_positions,
                        geofence_statuses,
                        behaviors,
                        stream_loader.fps,
                        settings.SOURCE_DEVICE_NAME,
                        thermal_processor.current_palette.value,
                        health_metrics=health_metrics,
                        attach_side_panel=False,
                        focused_target_id=locked_target_id,
                        target_history=target_tracker.get_target_history()
                    )
                    raw_half = cv2.resize(raw_base, (half_w, settings.FRAME_HEIGHT))
                    therm_half = cv2.resize(therm_base, (half_w, settings.FRAME_HEIGHT))
                    split_viewport = np.hstack((raw_half, therm_half))
                    final_view = object_detector.render_tactical_hud(
                        split_viewport,
                        tracked_targets,
                        geo_positions,
                        geofence_statuses,
                        behaviors,
                        stream_loader.fps,
                        settings.SOURCE_DEVICE_NAME,
                        "SPLIT_VIEW",
                        health_metrics=health_metrics,
                        sector_inventory=sector_inventory,
                        raw_sensor_frame=active_frame,
                        attach_side_panel=True,
                        focused_target_id=locked_target_id,
                        target_history=target_tracker.get_target_history()
                    )
                else:
                    final_view = hud_view

                cv2.imshow(window_name, final_view)

            except (ThermalProcessingError, DetectionProcessingError, TrackerBaseException) as pipe_err:
                logger.error(f"[PIPELINE-WARN] Frame omitido: {pipe_err}")
                continue

            # 16. Control de Teclado del Operador y Temporizador de 30-60 FPS
            loop_duration = time.perf_counter() - loop_start
            # Si el procesamiento fue ultra rápido (< 16.6ms), esperar para no exceder 60 FPS
            # Si fue más lento, asegurar al menos 1ms sin exceder 33.3ms (30 FPS suelo)
            sleep_sec = target_frame_interval - loop_duration
            if sleep_sec > 0.001:
                wait_key_ms = max(1, int(sleep_sec * 1000.0))
            else:
                wait_key_ms = 1

            key = cv2.waitKey(wait_key_ms) & 0xFF

            if key in (ord('q'), ord('Q'), 27):  # 'Q' o ESC -> Salir
                logger.info("[OPERATOR] Comando de parada solicitado.")
                break

            elif key in (ord('b'), ord('B')):  # 'B' -> Alternar White Hot / Black Hot / Bone
                new_pal = thermal_processor.toggle_white_black_hot()
                logger.info(f"[OPERATOR] Paleta térmica conmutada a: {new_pal.value}")

            elif key in (ord('s'), ord('S')):  # 'S' -> Snapshot manual a Obsidian
                logger.info("[OPERATOR] Snapshot manual a Obsidian solicitado.")
                obsidian_exporter.export_recon_event_async(
                    hud_view,
                    tracked_targets,
                    geo_positions,
                    geofence_statuses,
                    behaviors,
                    manual_trigger=True
                )

            elif key in (ord('d'), ord('D')):  # 'D' -> Ciclar modo de visualización
                modes = ["RGB_HUD", "THERMAL_HUD", "SPLIT", "RAW"]
                current_idx = modes.index(display_mode) if display_mode in modes else 0
                display_mode = modes[(current_idx + 1) % len(modes)]
                logger.info(f"[DISPLAY] Modo de visualización cambiado a: {display_mode}")

            elif ord('1') <= key <= ord('9'):  # Teclas 1-9 -> Selección rápida de objetivo
                idx = key - ord('1')
                all_targets = target_tracker.get_all_known_targets()
                if idx < len(all_targets):
                    locked_target_id = all_targets[idx].target_id
                    logger.info(f"[TARGET-LOCK] Objetivo fijado (Key {idx+1}): {locked_target_id}")

            elif key in (9, ord('\t')):  # Tecla TAB -> Ciclar entre objetivos
                all_targets = target_tracker.get_all_known_targets()
                if all_targets:
                    ids = [t.target_id for t in all_targets]
                    if locked_target_id in ids:
                        next_idx = (ids.index(locked_target_id) + 1) % len(ids)
                    else:
                        next_idx = 0
                    locked_target_id = ids[next_idx]
                    logger.info(f"[TARGET-LOCK] Objetivo ciclado (TAB): {locked_target_id}")

            elif key in (ord('0'), ord('u'), ord('U')):  # Tecla 0 o 'U' -> Desbloquear objetivo
                locked_target_id = None
                logger.info("[TARGET-LOCK] Bloqueo liberado (Tecla 0 / Unlock).")

    except KeyboardInterrupt:
        logger.warning("[SHUTDOWN] Interrupción manual (SIGINT).")

    finally:
        logger.info("[SHUTDOWN] Procediendo al desmontaje ordenado de LATTICE-CORE...")
        object_detector.stop_async_worker()
        stream_loader.stop()
        if web_bridge:
            web_bridge.stop()
        audio_alert_manager.close()
        db_manager.close()
        obsidian_exporter.shutdown()
        cv2.destroyAllWindows()
        logger.info("[SHUTDOWN] Centro de mando finalizado con éxito.")


if __name__ == "__main__":
    custom_url = sys.argv[1] if len(sys.argv) > 1 else None
    run_orchestrator(stream_override=custom_url)
