"""
LATTICE-CORE ISR - Obsidian Markdown & Evidence Exporter
Genera notas estructuradas en Markdown con YAML frontmatter enriquecido con conducta y geofence.
Hardening estricto contra Path Traversal (CWE-22) y persistencia asíncrona mediante ThreadPoolExecutor.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import cv2
import numpy as np
from loguru import logger

from lattice_isr.config.settings import SystemSettings
from lattice_isr.core.security import StreamSecurityValidator, PathTraversalAttemptError
from lattice_isr.engine.target_tracker import TrackedTargetState
from lattice_isr.engine.geolocation_engine import TargetGeoPosition
from lattice_isr.engine.geofence_engine import TargetGeofenceStatus
from lattice_isr.engine.behavior_analyzer import TargetBehaviorIntent


class StoragePersistenceError(Exception):
    """Fallo en la persistencia de evidencia física o nota Markdown."""
    pass


class ObsidianExporter:
    """
    Exportador de auditoría para Obsidian Vault.
    Confinamiento estricto de rutas (CWE-22) y concurrencia no bloqueante para I/O.
    """

    def __init__(self, settings: SystemSettings):
        self._settings = settings
        self._vault_path = settings.VAULT_PATH.resolve()
        self._evidence_dir = self._vault_path / "evidence"
        self._reports_dir = self._vault_path / "recon_reports"

        self._init_vault_structure()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ObsidianWriter")

    def _init_vault_structure(self) -> None:
        """Crea la estructura del Vault si no existe, valida permisos y genera nota de bienvenida para Obsidian."""
        try:
            self._evidence_dir.mkdir(parents=True, exist_ok=True)
            self._reports_dir.mkdir(parents=True, exist_ok=True)

            # Nota inicial de bienvenida para indexación automática al abrir en Obsidian
            readme_vault = self._vault_path / "00_BOVEDA_TACTICA_ISR.md"
            if not readme_vault.exists():
                readme_content = """---
tipo: index_tactico
sistema: LATTICE-CORE ISR
creado: 2026-10-07
tags:
  - lattice_vault
  - centro_de_mando
---

# 🛰️ BÓVEDA TÁCTICA LATTICE-CORE ISR

Esta carpeta funciona como **Bóveda Local Autónoma de Obsidian** (Obsidian Vault).
Todos los reportes tácticos generados por la estación terrena se guardan e indexan automáticamente aquí.

## 📁 Estructura del Vault:
- **`recon_reports/`**: Informes de reconocimiento en formato Markdown enriquecido con Frontmatter YAML (Objetivos, GPS, MGRS, intenciones y geofence).
- **`evidence/`**: Capturas gráficas PNG de alta resolución radiométrica enlazadas en cada informe.

---
*Para visualizar en Obsidian: Abre la aplicación Obsidian -> Abrir carpeta como Bóveda -> Selecciona esta carpeta `obsidian_vault`.*
"""
                with open(readme_vault, "w", encoding="utf-8") as f:
                    f.write(readme_content)

            logger.info(f"[STORAGE] Vault de Obsidian verificado e indexado en: {self._vault_path}")
        except OSError as err:
            logger.error(f"[STORAGE-ERR] No se pudo crear la estructura del Vault: {err}")
            raise StoragePersistenceError(f"Error al inicializar directorios del Vault: {err}") from err

    def export_recon_event_async(
        self,
        frame_rgb: np.ndarray,
        tracked_targets: List[TrackedTargetState],
        geo_positions: Dict[str, TargetGeoPosition],
        geofence_statuses: Dict[str, TargetGeofenceStatus],
        behaviors: Dict[str, TargetBehaviorIntent],
        manual_trigger: bool = False,
        video_clip_path: Optional[Path] = None
    ) -> None:
        """Encola la exportación en segundo plano sin interrumpir el pipeline gráfico."""
        frame_copy = frame_rgb.copy()
        targets_copy = [t.model_copy() for t in tracked_targets]
        geo_copy = {k: v.model_copy() for k, v in geo_positions.items()}
        gf_copy = {k: v.model_copy() for k, v in geofence_statuses.items()}
        beh_copy = {k: v.model_copy() for k, v in behaviors.items()}

        self._executor.submit(
            self._export_worker,
            frame_copy,
            targets_copy,
            geo_copy,
            gf_copy,
            beh_copy,
            manual_trigger,
            video_clip_path
        )

    def _export_worker(
        self,
        frame: np.ndarray,
        targets: List[TrackedTargetState],
        geo_positions: Dict[str, TargetGeoPosition],
        geofence_statuses: Dict[str, TargetGeofenceStatus],
        behaviors: Dict[str, TargetBehaviorIntent],
        manual_trigger: bool,
        video_clip_path: Optional[Path] = None
    ) -> None:
        """Trabajo de guardado en hilo secundario."""
        try:
            now = datetime.now()
            iso_timestamp = now.strftime("%Y-%m-%dT%H:%M:%S")
            raw_stamp = now.strftime("%Y%m%d_%H%M%S_%f")[:19]
            safe_stamp = StreamSecurityValidator.sanitize_filename(raw_stamp)

            # Selección del objetivo principal para el frontmatter
            if targets:
                breaching = [t for t in targets if geofence_statuses.get(t.target_id, TargetGeofenceStatus(target_id=t.target_id, status="SAFE", distance_to_base_m=999, is_breaching=False)).is_breaching]
                if breaching:
                    primary_target = breaching[0]
                else:
                    primary_target = max(targets, key=lambda t: t.area_px)

                raw_target_id = primary_target.target_id
                target_id = StreamSecurityValidator.sanitize_filename(raw_target_id)
                threat_level = primary_target.threat_level
                hotspot_area = primary_target.area_px
                heading_deg = primary_target.heading_deg

                primary_geo = geo_positions.get(target_id)
                estimated_lat = primary_geo.latitude if primary_geo else self._settings.BASE_SENSOR_LAT
                estimated_lon = primary_geo.longitude if primary_geo else self._settings.BASE_SENSOR_LON
                maps_url = primary_geo.maps_url if primary_geo else f"https://maps.google.com/?q={estimated_lat},{estimated_lon}"
                mgrs_grid = primary_geo.mgrs_grid if primary_geo else "N/A"

                gf_obj = geofence_statuses.get(target_id)
                geofence_status = gf_obj.status if gf_obj else "SAFE"

                beh_obj = behaviors.get(target_id)
                behavior_intent = beh_obj.intent if beh_obj else "TRANSITING"
            else:
                target_id = f"SNAP_{safe_stamp}"
                threat_level = "INFORMATIONAL"
                hotspot_area = 0
                heading_deg = 0.0
                estimated_lat = self._settings.BASE_SENSOR_LAT
                estimated_lon = self._settings.BASE_SENSOR_LON
                maps_url = f"https://maps.google.com/?q={estimated_lat},{estimated_lon}"
                mgrs_grid = "N/A"
                geofence_status = "SAFE"
                behavior_intent = "NONE"

            # Sanitización rigurosa de nombres de archivo
            image_filename = f"capture_{safe_stamp}.png"
            image_path = self._evidence_dir / image_filename

            # Validación de Path Traversal
            safe_image_path = StreamSecurityValidator.validate_safe_storage_path(
                self._vault_path,
                image_path
            )

            # 1. Guardar captura gráfica
            success = cv2.imwrite(str(safe_image_path), frame)
            if not success:
                raise StoragePersistenceError(f"OpenCV no pudo escribir la imagen en: {safe_image_path}")

            # 2. Generar archivo Markdown para Obsidian
            report_filename = f"ISR_{target_id}_{safe_stamp}.md"
            report_path = self._reports_dir / report_filename

            safe_report_path = StreamSecurityValidator.validate_safe_storage_path(
                self._vault_path,
                report_path
            )

            # 3. Generar contenido Markdown estructurado
            md_content = self._build_markdown_content(
                target_id=target_id,
                iso_timestamp=iso_timestamp,
                threat_level=threat_level,
                hotspot_area_px=hotspot_area,
                estimated_lat=estimated_lat,
                estimated_lon=estimated_lon,
                heading_deg=heading_deg,
                maps_url=maps_url,
                mgrs_grid=mgrs_grid,
                geofence_status=geofence_status,
                behavior_intent=behavior_intent,
                image_relative_path=f"../evidence/{image_filename}",
                targets=targets,
                geo_positions=geo_positions,
                geofence_statuses=geofence_statuses,
                behaviors=behaviors,
                manual_trigger=manual_trigger,
                video_clip_path=video_clip_path
            )

            with open(safe_report_path, "w", encoding="utf-8") as f:
                f.write(md_content)

            logger.info(
                f"[OBSIDIAN-AUDIT] Registro táctico archivado: {report_filename} "
                f"(Target: {target_id}, Breach: {geofence_status}, Intent: {behavior_intent})"
            )

        except (OSError, PathTraversalAttemptError, StoragePersistenceError) as err:
            logger.error(f"[STORAGE-ERR] Fallo persistiendo reporte de misión: {err}")
        finally:
            # Liberación explícita de referencias a matrices de imagen y diccionarios
            del frame
            del targets
            del geo_positions
            del geofence_statuses
            del behaviors

    def _build_markdown_content(
        self,
        target_id: str,
        iso_timestamp: str,
        threat_level: str,
        hotspot_area_px: int,
        estimated_lat: float,
        estimated_lon: float,
        heading_deg: float,
        maps_url: str,
        mgrs_grid: str,
        geofence_status: str,
        behavior_intent: str,
        image_relative_path: str,
        targets: List[TrackedTargetState],
        geo_positions: Dict[str, TargetGeoPosition],
        geofence_statuses: Dict[str, TargetGeofenceStatus],
        behaviors: Dict[str, TargetBehaviorIntent],
        manual_trigger: bool
    ) -> str:
        """Construye la nota Markdown compatible con Dataview / Obsidian Core."""
        trigger_mode = "MANUAL_OPERATOR (Key: 'S')" if manual_trigger else "AUTOMATIC_BREACH_DETECTION"

        targets_table_rows = []
        for t in targets:
            g = geo_positions.get(t.target_id)
            gf = geofence_statuses.get(t.target_id)
            beh = behaviors.get(t.target_id)

            lat_str = f"{g.latitude:.6f}" if g else "N/A"
            lon_str = f"{g.longitude:.6f}" if g else "N/A"
            gf_str = gf.status if gf else "SAFE"
            beh_str = beh.intent if beh else "TRANSITING"
            cls_str = getattr(t, "class_name", "target")

            targets_table_rows.append(
                f"| `{t.target_id}` | `{cls_str}` | `{gf_str}` | `{beh_str}` | `{t.threat_level}` | "
                f"`{t.velocity_px_s} px/s` | `{lat_str}, {lon_str}` |"
            )
        table_str = "\n".join(targets_table_rows) if targets_table_rows else "_Sin objetivos específicos segmentados._"

        video_section = ""
        if video_clip_path is not None:
            clip_name = Path(video_clip_path).name
            video_section = f"""
## 🎬 Videoclip Forense del Evento (MP4)

![[evidence/{clip_name}]]

*Clip archivado en:* `obsidian_vault/evidence/{clip_name}`
"""

        content = f"""---
target_id: "{target_id}"
behavior_intent: "{behavior_intent}"
geofence_status: "{geofence_status}"
estimated_lat: {estimated_lat:.6f}
estimated_lon: {estimated_lon:.6f}
heading_deg: {heading_deg:.1f}
threat_level: "{threat_level}"
timestamp: "{iso_timestamp}"
source_device: "{self._settings.SOURCE_DEVICE_NAME}"
hotspot_area_px: {hotspot_area_px}
mgrs_grid: "{mgrs_grid}"
maps_url: "{maps_url}"
trigger_type: "{trigger_mode}"
tags:
  - tactical_isr
  - threat_audit
  - lattice_core
  - geofence
  - behavior_analysis
---

# 🛰️ REPORTE TÁCTICO ISR C2: {target_id}

> **Dispositivo Edge:** {self._settings.SOURCE_DEVICE_NAME}  
> **Estado de Perímetro:** `{geofence_status}`  
> **Intención Táctica:** `{behavior_intent}`  
> **Nivel de Amenaza:** `{threat_level}`  
> **Timestamp:** {iso_timestamp}  
> **Coordenadas WGS84:** [`{estimated_lat:.6f}, {estimated_lon:.6f}`]({maps_url})  
> **Cuadrícula Militar MGRS:** `{mgrs_grid}`  

---

## 📷 Evidencia Radiométrica Capturada

![[evidence/{Path(image_relative_path).name}]]

*Ruta de almacenamiento local:* `{image_relative_path}`
{video_section}
---

## 🎯 Desglose de Objetivos Rastreados

| Target ID | Clase | Geofence | Intención | Amenaza | Velocidad | Coordenadas GPS (Lat, Lon) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
{table_str}

---

## 🗺️ Geolocalización y Navegación
- 📍 **Enlace Google Maps:** [{maps_url}]({maps_url})
- 🛡️ **Radio Perimetral Configurado:** `{self._settings.GEOFENCE_RADIUS_METERS} metros`
"""
        return content

    def shutdown(self) -> None:
        """Cierra el pool de persistencia."""
        logger.info("[STORAGE] Esperando finalización de escrituras pendientes en Obsidian...")
        self._executor.shutdown(wait=True)
        logger.info("[STORAGE] Subsistema de persistencia finalizado.")
