# 📅 Sílabo2Calendar

> **Convierte sílabos universitarios en calendarios inteligentes usando IA.**

Suba sus sílabos en PDF y obtenga en minutos: tabla de evaluaciones, gráfico de carga académica por semana, semanas críticas y un archivo `.ics` listo para importar a Google Calendar.

---

## 🚀 Demo

🔗 **URL del demo:** _[agregar link de Streamlit Cloud aquí]_

---

## 🎯 Problema que resuelve

Los estudiantes reciben entre 4 y 7 sílabos al inicio del ciclo. Las fechas, pesos y evaluaciones están dispersas en PDFs largos. El resultado: entregas olvidadas, semanas saturadas y mala planificación.

Sílabo2Calendar convierte ese PDF pasivo en un sistema vivo de planificación académica.

---

## ✨ Features del MVP

| Feature | Descripción |
|---|---|
| 📤 Upload PDF | Hasta 5 sílabos por sesión |
| 🤖 Extracción con IA | Claude AI extrae evaluaciones, pesos y fechas en JSON estructurado |
| 📋 Tabla consolidada | Todas las evaluaciones de todos los cursos en una sola vista |
| 📈 Carga académica | Gráfico de barras con score por semana y detección de semanas críticas |
| 📅 Calendario | Vista cronológica de evaluaciones |
| ⬇️ Export .ics | Archivo estándar para Google Calendar, Apple Calendar, Outlook |
| ⬇️ Export CSV | Tabla completa descargable |
| 🎯 Modo demo | Datos de ejemplo sin necesidad de sílabos propios |

---

## 🛠 Stack técnico

| Componente | Herramienta |
|---|---|
| Frontend / Demo | [Streamlit](https://streamlit.io) |
| PDF Extraction | [pdfplumber](https://github.com/jsvine/pdfplumber) |
| IA / LLM | [Claude claude-sonnet-4-6 via Anthropic API](https://docs.anthropic.com) |
| Visualización | [Plotly](https://plotly.com/python/) |
| Calendario | [icalendar](https://pypi.org/project/icalendar/) |
| Fechas | [python-dateutil](https://dateutil.readthedocs.io) |

### Herramientas del curso usadas

1. **Document AI con Claude API** (Lectura 14) — extracción estructurada de información desde PDFs de sílabos usando prompting avanzado y respuesta JSON.
2. **LLMs y APIs** (Lecturas 12-13) — Claude claude-sonnet-4-6 como motor de comprensión de lenguaje natural para entender formatos de sílabos variados.

---

## 📁 Estructura del repositorio

```
silabo2calendar/
├── app.py                  # Aplicación principal Streamlit
├── requirements.txt
├── .env.example
├── README.md
├── src/
│   ├── pdf_extractor.py    # Extracción de texto de PDFs
│   ├── llm_extractor.py    # Llamada a Claude API → JSON estructurado
│   ├── date_normalizer.py  # Normalización de fechas en español
│   ├── workload.py         # Cálculo de carga académica por semana
│   └── calendar_exporter.py # Generación de archivo .ics
├── prompts/
│   └── extract_syllabus.md # Prompt de extracción documentado
├── data/
│   └── sample_syllabi/     # Sílabos de ejemplo para demo
├── docs/
│   ├── pitch_deck.pdf
│   ├── architecture.png
│   └── screenshots/
└── tests/
    └── test_date_normalizer.py
```

---

## ⚙️ Cómo correr localmente

### 1. Clonar el repositorio

```bash
git clone https://github.com/tu-usuario/silabo2calendar.git
cd silabo2calendar
```

### 2. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 3. Configurar variables de entorno

```bash
cp .env.example .env
# Editar .env y agregar tu ANTHROPIC_API_KEY
```

### 4. Correr la app

```bash
streamlit run app.py
```

La app abre en `http://localhost:8501`

---

## 🌐 Deploy en Streamlit Community Cloud

1. Push el repo a GitHub (público).
2. Ir a [share.streamlit.io](https://share.streamlit.io).
3. Conectar el repo y seleccionar `app.py` como entry point.
4. En **Secrets**, agregar:
   ```
   ANTHROPIC_API_KEY = "sk-ant-..."
   ```

---

## ⚠️ Limitaciones conocidas

- PDFs escaneados (imágenes) tienen menor calidad de extracción. Se recomienda PDFs con texto seleccionable.
- Fechas en formatos muy inusuales pueden quedar como `null` y aparecen en la sección "requiere revisión".
- Pesos que no suman 100% se muestran con advertencia (puede ser que el sílabo esté incompleto).
- Máximo 5 sílabos por sesión en el MVP.

---

## 🗺 Roadmap

| Plazo | Hito |
|---|---|
| 1 mes | OCR fallback para PDFs escaneados (PaddleOCR) |
| 1 mes | Edición manual de eventos en la tabla |
| 3 meses | Integración directa con Google Calendar API |
| 3 meses | Soporte para sílabos de Canvas/Blackboard |
| 6 meses | App móvil + alertas por correo |
| 12 meses | Dashboard para universidades + API pública |

---

## 🤖 Uso de IA en el desarrollo

Este proyecto fue desarrollado con asistencia de Claude Code y Claude AI como herramientas de pair programming. Todo el código fue revisado, entendido y adaptado por el autor.

---

## 📄 Licencia

MIT License — ver `LICENSE`
