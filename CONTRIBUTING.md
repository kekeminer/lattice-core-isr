# 🤝 Guía de Contribución a LATTICE-CORE ISR

¡Gracias por tu interés en contribuir a **LATTICE-CORE ISR**! Este es un proyecto de código abierto enfocado en sistemas autónomos de Mando y Control (C2), visión por computadora y reconocimiento táctico de borde.

Para mantener la robustez, seguridad y rendimiento operativo de grado empresarial, solicitamos a todos los colaboradores seguir los lineamientos descritos en este documento.

---

## 🏛️ Código de Conducta

- Mantén un tono profesional, constructivo y respetuoso en issues, discusiones y revisiones de código.
- Se valora la claridad técnica y el rigor en las propuestas.

---

## 🛠️ Entorno de Desarrollo Local

### 1. Clonar el repositorio
```bash
git clone https://github.com/tu-usuario/lattice-core-isr.git
cd lattice-core-isr
```

### 2. Crear y activar el entorno virtual
En Windows (PowerShell):
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```
En Linux / macOS:
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Instalar dependencias completas
```bash
pip install -r requirements.txt
```

### 4. Configurar variables de entorno
```bash
cp .env.example .env
```

---

## 📐 Estándares de Código y Calidad

Para garantizar la mantenibilidad y estabilidad en tiempo real:

1. **Tipado Estricto (Type Hints):**  
   Todas las funciones y métodos públicos deben incluir type hints completos (`from typing import Optional, List, Dict, Tuple`).
2. **Modelos de Dominio Pydantic v2:**  
   Cualquier intercambio de datos y validación de configuración debe modelarse mediante `pydantic.BaseModel` o `pydantic_settings.BaseSettings`.
3. **Manejo Estricto de Excepciones (Zero Naked Exceptions):**  
   No uses bloques `except:` genéricos sin registrar o tipar. Captura errores específicos (`cv2.error`, `OSError`, etc.) y documenta su causa en logs estructurados con `loguru`.
4. **Límite Estricto de Memoria (< 250 MB RAM):**  
   Cualquier procesamiento de imágenes o video debe dereferenciar matrices obsoletas (`del frame`) y utilizar colas FIFO acotadas (`queue.Queue(maxsize=N)`).
5. **Formateo y Estilo:**  
   Seguimos las directrices de **PEP 8** con longitud máxima de línea de 100 caracteres.

---

## 🧪 Ejecución y Creación de Tests

Antes de enviar cualquier Pull Request, **el 100% de los tests debe pasar satisfactoriamente**:

```bash
python -m pytest -v
```

Si agregas una nueva funcionalidad o corriges un bug:
- Crea o actualiza las pruebas correspondientes en el directorio `tests/`.
- Asegura que los tests no dependan de hardware físico externo (usa mocks o matrices sintéticas).

---

## 🚀 Flujo de Trabajo para Pull Requests (PR)

1. **Crea un Fork** del repositorio y genera una rama descriptiva para tu trabajo:
   ```bash
   git checkout -b feature/reconocimiento-termico-avanzado
   # o
   git checkout -b fix/buffer-overflow-socket
   ```
2. **Realiza tus cambios** respetando las directrices de arquitectura modular (`/lattice_isr/core`, `/lattice_isr/engine`, `/lattice_isr/storage`, `/lattice_isr/utils`, `/lattice_isr/network`).
3. **Ejecuta la suite de pruebas**:
   ```bash
   pytest
   ```
4. **Haz commit con mensajes claros y descriptivos**:
   ```bash
   git commit -m "feat(engine): integrar calibración de matriz intrínseca de cámara"
   ```
5. **Envía tu rama al fork y abre un Pull Request** hacia la rama `main` del repositorio oficial.

---

## 🐛 Reporte de Vulnerabilidades de Seguridad

Por tratarse de un software con consideraciones de ciberseguridad defensiva, si descubres una vulnerabilidad crítica (ej. SSRF, inyección de comandos o path traversal), por favor repórtala de forma confidencial vía Security Advisory en GitHub o contactando a los maintainers antes de abrir un issue público.
