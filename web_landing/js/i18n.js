/**
 * LATTICE-CORE ISR // Tactical Multi-Language Engine (I18n)
 * Soporte Multi-idioma (Español / Inglés) con persistencia en localStorage.
 */

const I18N_DATA = {
  es: {
    page_title: "LATTICE-CORE ISR | Plataforma Táctica C2 y Reconocimiento Edge",
    meta_description: "Plataforma C2 de grado industrial para procesamiento ISR en tiempo real: inferencia neuronal asíncrona YOLOv8 a 60 FPS, geolocalización esférica MGRS/UTM y auditoría forense en Obsidian.",
    brand_version: "v1.0.0 // OPEN SOURCE",
    nav_telemetry: "Telemetría",
    nav_capabilities: "Capacidades",
    nav_deployment: "Despliegue",
    nav_github: "GitHub Repository",
    
    // Hero
    hero_title: "Estación de Mando y Control Táctico",
    hero_title_accent: "para Procesamiento ISR Periférico",
    hero_description: "Plataforma de ingeniería de misión crítica para nodos Edge. Ingesta a 60 FPS sin degradación de latencia, clasificación neuronal YOLOv8 desacoplada, telemetría cinemática en panel lateral, proyección esférica MGRS/UTM y registro de auditoría en Obsidian.",
    btn_official_repo: "Repositorio Oficial",
    btn_specs: "Especificaciones Técnicas",
    
    // Terminal
    terminal_title: "SHELL // CLONACIÓN Y DESPLIEGUE",
    terminal_protocol: "HTTPS / GIT",
    btn_copy: "Copiar",
    btn_copied: "Copiado",
    
    // Métricas
    metric_1_title: "60 FPS Continuous Render Rate",
    metric_1_sub: "Rendimiento del Canvas",
    metric_2_title: "< 160 MB Memory Footprint",
    metric_2_sub: "Consumo de RAM",
    metric_3_title: "43 / 43 QA Test Suites Passed (100% Coverage)",
    metric_3_sub: "Validación Operativa",
    metric_4_title: "MGRS / UTM Spherical Geolocation Engine",
    metric_4_sub: "Coordenadas Tácticas",
    
    // Capacidades
    sec_tag_capabilities: "SISTEMAS MODULARES",
    sec_title_capabilities: "Capacidades Operativas del Sistema",
    sec_desc_capabilities: "Arquitectura modular asíncrona optimizada para procesamiento de telemetría y reconocimiento en nodos de cómputo periférico (Edge Computing).",
    
    // Tarjetas MOD
    card_1_tag: "NEURAL PIPELINE",
    card_1_title: "Detección Neuronal Asíncrona (YOLOv8)",
    card_1_text: "Inferencia multiclase en hilo secundario desacoplado a resolución Stride 32 (384x640), garantizando renderizado gráfico fluido a 60 FPS sin latencia de captura.",
    card_1_spec: "RESOLUCIÓN: 384x640 (STRIDE 32)",
    
    card_2_tag: "TACTICAL HUD",
    card_2_title: "Panel de Inspección Táctica (Side Inspector)",
    card_2_text: "Telemetría lateral en tiempo real con recortes dinamizados, vectores cinemáticos (rumbo y velocidad) y caracterización de vestimenta/superficies mediante cuantización de espectro HSV.",
    card_2_spec: "LAYOUT: 300PX DEDICADO // ESPECTRO HSV",
    
    card_3_tag: "GEOSPATIAL COV",
    card_3_title: "Análisis de Terreno y Cobertura Métrica (m²)",
    card_3_text: "Trigonometría proyectiva basada en distancia focal y FOV angular para el cálculo de superficie encuadrada e inventario sectorial de densidad.",
    card_3_spec: "MODELO: PINHOLE + WGS84 ESFÉRICO",
    
    card_4_tag: "PERIMETER DEFENSE",
    card_4_title: "Perímetro Virtual y Persistencia Sostenida",
    card_4_text: "Geofencing con filtrado semántico de amenazas y ventana de permanencia continua (> 3.0s) para mitigar falsos positivos.",
    card_4_spec: "DISCRIMINACIÓN: CLASES CRÍTICAS COCO",
    
    card_5_tag: "AUDIO & VIDEO C2",
    card_5_title: "Síntesis de Alertas Sonoras y Grabación Forense",
    card_5_text: "Transmisión de voz asíncrona no bloqueante y empaquetado automático de clips .mp4 en búfer circular ante eventos confirmados.",
    card_5_spec: "MOTOR: PYTTSX3 + MP4 ROLLING BUFFER",
    
    card_6_tag: "STORAGE & STREAM",
    card_6_title: "Persistencia Híbrida y Dashboard Web",
    card_6_text: "Integración nativa con Bóveda de Obsidian en Markdown, base de datos embebida SQLite y servidor WebSockets para la estación de control en vivo.",
    card_6_spec: "PROTOCOLOS: WEBSOCKETS + SQLITE WAL + OBSIDIAN",
    
    // Pipeline
    pipe_kicker: "FLUJO DE PROCESAMIENTO DETERMINISTA",
    pipe_title: "Topología de Flujo Asíncrono de Cuadros",
    pipe_step_1_label: "Ingesta Edge Video",
    pipe_step_1_sub: "RTSP / HTTP (OpenCV)",
    pipe_step_2_label: "Inferencia Desacoplada",
    pipe_step_2_sub: "YOLOv8 Stride 32 (384x640)",
    pipe_step_3_label: "Tracking & Geodesia",
    pipe_step_3_sub: "Centroides, MGRS y m²",
    pipe_step_4_label: "Render & Auditoría",
    pipe_step_4_sub: "60 FPS HUD + Obsidian Vault",
    
    // Footer
    footer_title: "LATTICE-CORE ISR",
    footer_text: "Plataforma de Reconocimiento Táctico, Telemetría y Geolocalización de Código Abierto.",
    footer_license: "Licencia Abierta MIT // Repositorio kekeminer/lattice-core-isr",
    footer_link_repo: "Repositorio GitHub",
    footer_link_license: "Licencia MIT",
    footer_link_contributing: "Guía de Contribución"
  },
  en: {
    page_title: "LATTICE-CORE ISR | Tactical C2 & Edge Recognition Platform",
    meta_description: "Industrial-grade C2 platform for real-time ISR processing: asynchronous YOLOv8 neural inference at 60 FPS, MGRS/UTM spherical geolocation, and forensic Obsidian audit logging.",
    brand_version: "v1.0.0 // OPEN SOURCE",
    nav_telemetry: "Telemetry",
    nav_capabilities: "Capabilities",
    nav_deployment: "Deployment",
    nav_github: "GitHub Repository",
    
    // Hero
    hero_title: "Tactical Command and Control Station",
    hero_title_accent: "for Edge ISR Processing",
    hero_description: "Mission-critical engineering platform for Edge nodes. 60 FPS video ingestion with zero latency degradation, decoupled YOLOv8 neural classification, side inspector kinematic telemetry, MGRS/UTM spherical projection, and Obsidian audit logging.",
    btn_official_repo: "Official Repository",
    btn_specs: "Technical Specifications",
    
    // Terminal
    terminal_title: "SHELL // CLONING & DEPLOYMENT",
    terminal_protocol: "HTTPS / GIT",
    btn_copy: "Copy",
    btn_copied: "Copied",
    
    // Metrics
    metric_1_title: "60 FPS Continuous Render Rate",
    metric_1_sub: "Canvas Render Performance",
    metric_2_title: "< 160 MB Memory Footprint",
    metric_2_sub: "RAM Memory Footprint",
    metric_3_title: "43 / 43 QA Test Suites Passed (100% Coverage)",
    metric_3_sub: "Operational Validation",
    metric_4_title: "MGRS / UTM Spherical Geolocation Engine",
    metric_4_sub: "Tactical Coordinates",
    
    // Capabilities
    sec_tag_capabilities: "MODULAR SYSTEMS",
    sec_title_capabilities: "Operational System Capabilities",
    sec_desc_capabilities: "Asynchronous modular architecture optimized for telemetry processing and recognition on edge computing nodes.",
    
    // MOD Cards
    card_1_tag: "NEURAL PIPELINE",
    card_1_title: "Asynchronous Neural Detection (YOLOv8)",
    card_1_text: "Multiclass inference on decoupled background thread at Stride 32 (384x640), ensuring fluid 60 FPS graphic rendering with zero capture latency.",
    card_1_spec: "RESOLUTION: 384x640 (STRIDE 32)",
    
    card_2_tag: "TACTICAL HUD",
    card_2_title: "Tactical Inspection Panel (Side Inspector)",
    card_2_text: "Real-time lateral telemetry with dynamic crops, kinematic vectors (heading & velocity), and clothing/surface profiling via HSV spectrum quantization.",
    card_2_spec: "LAYOUT: 300PX DEDICATED // HSV SPECTRUM",
    
    card_3_tag: "GEOSPATIAL COV",
    card_3_title: "Terrain Analysis & Metric Coverage (m²)",
    card_3_text: "Projective trigonometry based on focal length and angular FOV for ground footprint calculation and sectoral density inventory.",
    card_3_spec: "MODEL: PINHOLE + SPHERICAL WGS84",
    
    card_4_tag: "PERIMETER DEFENSE",
    card_4_title: "Virtual Perimeter & Sustained Persistence",
    card_4_text: "Geofencing with semantic threat filtering and continuous residence window (> 3.0s) to mitigate false positives.",
    card_4_spec: "DISCRIMINATION: CRITICAL COCO CLASSES",
    
    card_5_tag: "AUDIO & VIDEO C2",
    card_5_title: "Voice Alert Synthesis & Forensic Recording",
    card_5_text: "Non-blocking asynchronous voice alerts and automatic .mp4 clip packaging in rolling circular buffer upon confirmed events.",
    card_5_spec: "ENGINE: PYTTSX3 + MP4 ROLLING BUFFER",
    
    card_6_tag: "STORAGE & STREAM",
    card_6_title: "Hybrid Persistence & Web Dashboard",
    card_6_text: "Native Markdown Obsidian Vault integration, SQLite embedded database, and WebSockets server for live control station.",
    card_6_spec: "PROTOCOLS: WEBSOCKETS + SQLITE WAL + OBSIDIAN",
    
    // Pipeline
    pipe_kicker: "DETERMINISTIC PROCESSING PIPELINE",
    pipe_title: "Asynchronous Frame Pipeline Topology",
    pipe_step_1_label: "Edge Video Ingestion",
    pipe_step_1_sub: "RTSP / HTTP (OpenCV)",
    pipe_step_2_label: "Decoupled Inference",
    pipe_step_2_sub: "YOLOv8 Stride 32 (384x640)",
    pipe_step_3_label: "Tracking & Geodesy",
    pipe_step_3_sub: "Centroids, MGRS & m²",
    pipe_step_4_label: "Render & Audit",
    pipe_step_4_sub: "60 FPS HUD + Obsidian Vault",
    
    // Footer
    footer_title: "LATTICE-CORE ISR",
    footer_text: "Open Source Tactical Recognition, Telemetry, and Geolocation Platform.",
    footer_license: "MIT Open Source License // Repository kekeminer/lattice-core-isr",
    footer_link_repo: "GitHub Repository",
    footer_link_license: "MIT License",
    footer_link_contributing: "Contribution Guide"
  }
};

let currentLanguage = "es";

function setLanguage(lang) {
  if (!I18N_DATA[lang]) {
    lang = "es";
  }
  currentLanguage = lang;
  localStorage.setItem("lattice_lang", lang);
  document.documentElement.lang = lang;

  const data = I18N_DATA[lang];

  // Actualizar título y metadatos
  document.title = data.page_title;
  const metaDesc = document.querySelector('meta[name="description"]');
  if (metaDesc) {
    metaDesc.setAttribute("content", data.meta_description);
  }

  // Actualizar todos los elementos con atributo data-i18n
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.getAttribute("data-i18n");
    if (data[key]) {
      el.textContent = data[key];
    }
  });

  // Botones del switcher
  const btnEs = document.getElementById("lang-btn-es");
  const btnEn = document.getElementById("lang-btn-en");
  if (btnEs && btnEn) {
    if (lang === "es") {
      btnEs.classList.add("active");
      btnEn.classList.remove("active");
    } else {
      btnEn.classList.add("active");
      btnEs.classList.remove("active");
    }
  }
}

function initLanguage() {
  const savedLang = localStorage.getItem("lattice_lang") || "es";
  setLanguage(savedLang);

  const btnEs = document.getElementById("lang-btn-es");
  const btnEn = document.getElementById("lang-btn-en");

  if (btnEs) {
    btnEs.addEventListener("click", () => setLanguage("es"));
  }
  if (btnEn) {
    btnEn.addEventListener("click", () => setLanguage("en"));
  }
}

document.addEventListener("DOMContentLoaded", initLanguage);
