"""
LATTICE-CORE ISR - Tactical Web Bridge & Real-Time WebSocket Telemetry
Servidor asíncrono ultra-liviano (FastAPI + Uvicorn) con mapa táctico monocromático en Leaflet.js.
Hardening contra XSS (CWE-79) y autenticación criptográfica en tiempo constante (CWE-208).
"""

import asyncio
import html
import json
import threading
import time
from typing import Any, Dict, List, Optional
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from loguru import logger

from lattice_isr.config.settings import SystemSettings
from lattice_isr.core.security import StreamSecurityValidator
from lattice_isr.network.security_auth import WebSocketAuthenticator


class WebBridgeServer:
    """
    Puente de red C2 para streaming de telemetría geoespacial.
    Corre en un hilo de background para no interferir con el pipeline OpenCV.
    """

    def __init__(self, settings: SystemSettings):
        self._settings = settings
        self._host = settings.WEB_HOST
        self._port = settings.WEB_PORT
        self._rate_hz = settings.WEB_TELEMETRY_RATE_HZ
        self._authenticator = WebSocketAuthenticator(settings)

        self._app = FastAPI(title="LATTICE-CORE ISR Tactical Bridge", docs_url=None, redoc_url=None)
        self._active_connections: List[WebSocket] = []

        # Estado más reciente protegido por thread lock
        self._state_lock = threading.Lock()
        self._latest_telemetry: Dict[str, Any] = {
            "timestamp": time.time(),
            "sensor": {
                "name": settings.SOURCE_DEVICE_NAME,
                "lat": settings.BASE_SENSOR_LAT,
                "lon": settings.BASE_SENSOR_LON,
                "alt_m": settings.BASE_SENSOR_ALT_M,
                "geofence_radius_m": settings.GEOFENCE_RADIUS_METERS
            },
            "targets": []
        }

        self._server_thread: Optional[threading.Thread] = None
        self._uvicorn_server: Optional[uvicorn.Server] = None
        self._stop_event = threading.Event()

        self._setup_routes()

    def update_telemetry(
        self,
        targets_payload: List[Dict[str, Any]],
        fps: float
    ) -> None:
        """Actualiza el estado de telemetría de forma atómica y no bloqueante sanitizando cadenas."""
        # Sanitizar cadenas de texto contra inyección XSS
        sanitized_targets = []
        for t in targets_payload:
            sanitized_targets.append({
                "target_id": StreamSecurityValidator.sanitize_html_text(str(t.get("target_id", ""))),
                "lat": float(t.get("lat", 0.0)),
                "lon": float(t.get("lon", 0.0)),
                "altitude_m": float(t.get("altitude_m", 0.0)),
                "heading_deg": float(t.get("heading_deg", 0.0)),
                "velocity_px_s": float(t.get("velocity_px_s", 0.0)),
                "threat_level": StreamSecurityValidator.sanitize_html_text(str(t.get("threat_level", "LOW"))),
                "geofence_status": StreamSecurityValidator.sanitize_html_text(str(t.get("geofence_status", "SAFE"))),
                "distance_to_base_m": float(t.get("distance_to_base_m", 0.0)),
                "behavior_intent": StreamSecurityValidator.sanitize_html_text(str(t.get("behavior_intent", "TRANSITING"))),
                "mgrs": StreamSecurityValidator.sanitize_html_text(str(t.get("mgrs", "N/A")))
            })

        with self._state_lock:
            self._latest_telemetry = {
                "timestamp": round(time.time(), 3),
                "fps": round(fps, 1),
                "sensor": {
                    "name": self._settings.SOURCE_DEVICE_NAME,
                    "lat": self._settings.BASE_SENSOR_LAT,
                    "lon": self._settings.BASE_SENSOR_LON,
                    "alt_m": self._settings.BASE_SENSOR_ALT_M,
                    "geofence_radius_m": self._settings.GEOFENCE_RADIUS_METERS
                },
                "targets": sanitized_targets
            }

    def _setup_routes(self) -> None:
        """Configura los endpoints de la API y WebSockets."""

        @self._app.get("/", response_class=HTMLResponse)
        async def get_dashboard() -> str:
            return self._generate_tactical_dashboard_html()

        @self._app.get("/api/health")
        async def get_health() -> Dict[str, str]:
            return {"status": "ONLINE", "system": "LATTICE-CORE-ISR"}

        @self._app.websocket("/ws/telemetry")
        async def websocket_telemetry_endpoint(websocket: WebSocket) -> None:
            # 1. Verificación de autenticación: si no se especifica token, usar el token configurado por defecto
            raw_token = websocket.query_params.get("token")
            token_to_verify = raw_token if (raw_token and raw_token.strip()) else self._settings.API_AUTH_TOKEN
            client_ip = websocket.client.host if websocket.client else "Unknown"

            if not self._authenticator.authenticate_query_token(token_to_verify, client_ip):
                await websocket.close(
                    code=WebSocketAuthenticator.WS_CLOSE_UNAUTHORIZED,
                    reason="Acceso denegado: Token de autenticacion invalido o ausente."
                )
                return

            await websocket.accept()
            self._active_connections.append(websocket)
            logger.info(f"[WEB-BRIDGE] Sesión WebSocket autenticada y aceptada desde: {client_ip}")

            sleep_interval = 1.0 / self._rate_hz
            try:
                while not self._stop_event.is_set():
                    with self._state_lock:
                        payload = self._latest_telemetry

                    await websocket.send_text(json.dumps(payload))
                    await asyncio.sleep(sleep_interval)
            except (WebSocketDisconnect, ConnectionResetError, asyncio.CancelledError):
                logger.debug(f"[WEB-BRIDGE] Desconexión de cliente WebSocket ({client_ip}).")
            finally:
                if websocket in self._active_connections:
                    self._active_connections.remove(websocket)

    def start(self) -> None:
        """Arranca el servidor en un hilo secundario independiente."""
        self._stop_event.clear()
        config = uvicorn.Config(
            app=self._app,
            host=self._host,
            port=self._port,
            log_level="warning",
            access_log=False
        )
        self._uvicorn_server = uvicorn.Server(config)

        self._server_thread = threading.Thread(
            target=self._run_server,
            name="LatticeWebBridgeThread",
            daemon=True
        )
        self._server_thread.start()
        logger.info(f"[WEB-BRIDGE] Servidor C2 activo en: http://{self._host}:{self._port}")

    def _run_server(self) -> None:
        """Bucle de ejecución Uvicorn."""
        try:
            self._uvicorn_server.run()
        except Exception as err:
            logger.error(f"[WEB-BRIDGE-ERR] Error en el servidor Web Bridge: {err}")

    def stop(self) -> None:
        """Detiene de forma segura el servidor Uvicorn."""
        logger.info("[WEB-BRIDGE] Deteniendo servidor de telemetría web...")
        self._stop_event.set()
        if self._uvicorn_server:
            self._uvicorn_server.should_exit = True
        if self._server_thread and self._server_thread.is_alive():
            self._server_thread.join(timeout=2.0)
        logger.info("[WEB-BRIDGE] Servidor Web Bridge finalizado.")

    def _generate_tactical_dashboard_html(self) -> str:
        """Genera el HTML/JS interactivo del visor táctico Leaflet en modo monocromo oscuro."""
        base_lat = self._settings.BASE_SENSOR_LAT
        base_lon = self._settings.BASE_SENSOR_LON
        geo_radius = self._settings.GEOFENCE_RADIUS_METERS
        default_token = self._settings.API_AUTH_TOKEN

        return f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LATTICE-CORE ISR // TACTICAL C2 MAP</title>
    <!-- Leaflet CSS & JS -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;800&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-color: #0d0f12;
            --panel-bg: rgba(18, 22, 28, 0.94);
            --border-color: #2b323c;
            --text-main: #e6ebf2;
            --text-dim: #7f8c9b;
            --accent-white: #ffffff;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background-color: var(--bg-color);
            color: var(--text-main);
            font-family: 'JetBrains Mono', monospace;
            overflow: hidden;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }}
        header {{
            background: var(--panel-bg);
            border-bottom: 1px solid var(--border-color);
            padding: 10px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            z-index: 1000;
        }}
        .brand h1 {{
            font-size: 14px;
            font-weight: 800;
            letter-spacing: 1.5px;
            color: var(--accent-white);
        }}
        .status-badge {{
            background: #1a2028;
            border: 1px solid #3d4754;
            color: #d0d7de;
            font-size: 11px;
            padding: 3px 8px;
            border-radius: 2px;
        }}
        #map-container {{
            flex: 1;
            position: relative;
        }}
        #map {{
            width: 100%;
            height: 100%;
            background: #090b0e;
        }}
        #telemetry-drawer {{
            position: absolute;
            top: 15px;
            right: 15px;
            width: 320px;
            max-height: calc(100% - 30px);
            background: var(--panel-bg);
            border: 1px solid var(--border-color);
            border-radius: 4px;
            z-index: 999;
            padding: 14px;
            overflow-y: auto;
            box-shadow: 0 8px 24px rgba(0,0,0,0.6);
            backdrop-filter: blur(8px);
        }}
        .drawer-title {{
            font-size: 11px;
            font-weight: 800;
            letter-spacing: 1px;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 8px;
            margin-bottom: 10px;
            color: var(--accent-white);
        }}
        .target-card {{
            background: #14181f;
            border: 1px solid #2d3542;
            padding: 9px;
            border-radius: 3px;
            margin-bottom: 8px;
            font-size: 11px;
        }}
        .target-card.breach {{
            border: 1px solid #ffffff;
            background: #22262e;
        }}
        .target-id {{
            font-weight: 800;
            color: #ffffff;
            display: flex;
            justify-content: space-between;
        }}
        .target-data {{
            margin-top: 4px;
            color: var(--text-dim);
            line-height: 1.4;
        }}
        .badge-breach {{
            background: #ffffff;
            color: #000000;
            padding: 1px 4px;
            font-weight: 800;
            border-radius: 2px;
        }}
        .badge-safe {{
            background: #2a313d;
            color: #b0bac5;
            padding: 1px 4px;
            border-radius: 2px;
        }}
    </style>
</head>
<body>
    <header>
        <div class="brand">
            <h1>▲ LATTICE-CORE ISR // TACTICAL C2 WEB</h1>
            <span class="status-badge" id="conn-status">WS: CONECTANDO...</span>
        </div>
        <div style="font-size: 11px; color: var(--text-dim);">
            SENSOR BASE: [{base_lat:.5f}, {base_lon:.5f}] | GEOFENCE: {geo_radius}m
        </div>
    </header>

    <div id="map-container">
        <div id="map"></div>
        <div id="telemetry-drawer">
            <div class="drawer-title">ENTIDADES EN RASTREO TÁCTICO</div>
            <div id="targets-list">_Buscando contactos..._</div>
        </div>
    </div>

    <script>
        const BASE_LAT = {base_lat};
        const BASE_LON = {base_lon};
        const GEOFENCE_RADIUS = {geo_radius};
        const DEFAULT_TOKEN = "{default_token}";

        // Función defensiva para mitigar XSS en frontend
        function escapeHtml(str) {{
            if (!str) return '';
            return String(str)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#039;');
        }}

        // Inicializar Leaflet con capa monocromática oscura (CartoDB DarkMatter)
        const map = L.map('map', {{
            center: [BASE_LAT, BASE_LON],
            zoom: 18,
            zoomControl: false
        }});

        L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
            maxZoom: 21,
            subdomains: 'abcd',
            attribution: '&copy; CartoDB &copy; OpenStreetMap'
        }}).addTo(map);

        // Marcador del Sensor Base
        const sensorIcon = L.divIcon({{
            className: 'sensor-marker',
            html: '<div style="background:#fff; width:12px; height:12px; border:2px solid #000; border-radius:50%; box-shadow:0 0 8px #fff;"></div>',
            iconSize: [12, 12],
            iconAnchor: [6, 6]
        }});
        L.marker([BASE_LAT, BASE_LON], {{ icon: sensorIcon }}).addTo(map)
            .bindPopup("<b>NODO SENSOR ISR</b><br>GCS Base").openPopup();

        // Círculo perimetral de Geofence
        L.circle([BASE_LAT, BASE_LON], {{
            radius: GEOFENCE_RADIUS,
            color: '#ffffff',
            weight: 1.5,
            dashArray: '4, 4',
            fillColor: '#ffffff',
            fillOpacity: 0.04
        }}).addTo(map);

        const targetMarkers = {{}};

        // Extraer token de autenticación desde la URL actual o usar token configurado
        const urlParams = new URLSearchParams(window.location.search);
        const authToken = urlParams.get('token') || DEFAULT_TOKEN;

        // Conexión WebSocket con token de seguridad precompartido
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${{protocol}}//${{window.location.host}}/ws/telemetry?token=${{encodeURIComponent(authToken)}}`;
        let ws = new WebSocket(wsUrl);

        ws.onopen = () => {{
            document.getElementById('conn-status').innerText = 'WS: ENLACE AUTORIZADO';
            document.getElementById('conn-status').style.color = '#fff';
        }};

        ws.onclose = (event) => {{
            if (event.code === 4001 || event.code === 4003) {{
                document.getElementById('conn-status').innerText = 'WS: ACCESO DENEGADO (4001)';
                document.getElementById('conn-status').style.color = '#ff6b6b';
            }} else {{
                document.getElementById('conn-status').innerText = 'WS: DESCONECTADO';
                document.getElementById('conn-status').style.color = '#7f8c9b';
                setTimeout(() => location.reload(), 3000);
            }}
        }};

        ws.onmessage = (event) => {{
            try {{
                const data = JSON.parse(event.data);
                const targets = data.targets || [];
                updateTacticalDisplay(targets);
            }} catch(e) {{
                console.error("Error parseando telemetría:", e);
            }}
        }};

        function updateTacticalDisplay(targets) {{
            const listContainer = document.getElementById('targets-list');
            const currentIds = new Set(targets.map(t => String(t.target_id)));

            for (const tid in targetMarkers) {{
                if (!currentIds.has(tid)) {{
                    map.removeLayer(targetMarkers[tid]);
                    delete targetMarkers[tid];
                }}
            }}

            if (targets.length === 0) {{
                listContainer.innerHTML = '<div style="color:#7f8c9b; font-size:11px;">_Sin firmas activas_</div>';
                return;
            }}

            let listHtml = '';

            targets.forEach(t => {{
                const safeId = escapeHtml(t.target_id);
                const safeStatus = escapeHtml(t.geofence_status);
                const safeIntent = escapeHtml(t.behavior_intent);
                const lat = Number(t.lat) || 0;
                const lon = Number(t.lon) || 0;
                const isBreach = safeStatus === 'PERIMETER_BREACH';
                const badgeClass = isBreach ? 'badge-breach' : 'badge-safe';

                if (!targetMarkers[safeId]) {{
                    const trgIcon = L.divIcon({{
                        className: 'trg-marker',
                        html: `<div style="background:#000; color:#fff; border:1px solid #fff; padding:2px 4px; font-size:9px; font-weight:800; border-radius:2px; white-space:nowrap;">${{safeId}}</div>`,
                        iconSize: [40, 15],
                        iconAnchor: [20, 7]
                    }});
                    targetMarkers[safeId] = L.marker([lat, lon], {{ icon: trgIcon }}).addTo(map);
                }} else {{
                    targetMarkers[safeId].setLatLng([lat, lon]);
                }}

                listHtml += `
                    <div class="target-card ${{isBreach ? 'breach' : ''}}">
                        <div class="target-id">
                            <span>${{safeId}}</span>
                            <span class="${{badgeClass}}">${{safeStatus}}</span>
                        </div>
                        <div class="target-data">
                            CONDUCTA: <b>${{safeIntent}}</b><br>
                            GPS: ${{lat.toFixed(5)}}, ${{lon.toFixed(5)}}<br>
                            RUMBO: ${{Number(t.heading_deg || 0).toFixed(0)}}° | VEL: ${{Number(t.velocity_px_s || 0).toFixed(0)}} px/s<br>
                            DIST. BASE: ${{Number(t.distance_to_base_m || 0).toFixed(1)}}m
                        </div>
                    </div>
                `;
            }});

            listContainer.innerHTML = listHtml;
        }}
    </script>
</body>
</html>"""
