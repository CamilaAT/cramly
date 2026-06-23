"""
app.py — Cramly
Aplicación principal en Streamlit.
Convierte sílabos universitarios en PDF a calendarios inteligentes usando Claude AI.
"""
import calendar as pycal
import io
import json
import os
import sys
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

# Asegurar que src/ esté en el path (local y Streamlit Cloud)
sys.path.insert(0, os.path.dirname(__file__))
load_dotenv()

from src.calendar_exporter import generate_ics
from src.date_normalizer import normalize_events
from src.llm_extractor import extract_syllabus_data, refine_course_data
from src.pdf_extractor import extract_text_from_pdf
from src.workload import calculate_workload_scores, get_critical_weeks_summary

# ─────────────────────────────────────
# Configuración de página
# ─────────────────────────────────────
st.set_page_config(
    page_title="Cramly",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    /* Tipografía Arial en toda la app */
    html, body, [class*="css"], .stApp, .main, button, input, textarea, select {
        font-family: Arial, "Helvetica Neue", Helvetica, sans-serif !important;
    }
    /* Títulos en mayúscula y negrita */
    h1, h2, h3, h4 { text-transform: uppercase; font-weight: 800 !important; letter-spacing: 0.01em; }
    .main-title  { font-size: 2.4rem; font-weight: 800; color: #1e293b; line-height: 1.1;
                   text-transform: uppercase; }
    .subtitle    { font-size: 1.05rem; color: #64748b; margin-top: 0.2rem; }
    .critical-week { background:#fef2f2; border-left:4px solid #ef4444;
                     padding:0.75rem 1rem; border-radius:0 8px 8px 0; margin:0.4rem 0; }
    .warning-week  { background:#fffbeb; border-left:4px solid #f59e0b;
                     padding:0.75rem 1rem; border-radius:0 8px 8px 0; margin:0.4rem 0; }
    .ok-week       { background:#f0fdf4; border-left:4px solid #22c55e;
                     padding:0.75rem 1rem; border-radius:0 8px 8px 0; margin:0.4rem 0; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────
# Etiquetas de tipo de evaluación en español
# ─────────────────────────────────────
TIPO_ES = {
    "exam": "Examen",
    "assignment": "Tarea",
    "presentation": "Exposición",
    "quiz": "Práctica calificada",
    "project": "Proyecto",
    "reading": "Lectura",
    "other": "Otro",
    "class": "Clase",
}

# Días de la semana → índice (lunes=0) para generar el horario de clases
DIA_A_WEEKDAY = {
    "lunes": 0, "martes": 1, "miércoles": 2, "miercoles": 2, "jueves": 3,
    "viernes": 4, "sábado": 5, "sabado": 5, "domingo": 6,
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def tipo_es(value: str) -> str:
    return TIPO_ES.get(value, (value or "Otro").capitalize())


# ─────────────────────────────────────
# Helpers de visualización por curso
# ─────────────────────────────────────
COURSE_COLORS = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2", "#db2777", "#65a30d"]
WEEKDAY_ES = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
MONTH_ES = {1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
            7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"}


def course_color_map(courses: list) -> dict:
    return {c: COURSE_COLORS[i % len(COURSE_COLORS)] for i, c in enumerate(courses)}


def color_weight(val):
    """Estilo de celda según el peso de la evaluación (para las tablas)."""
    if pd.isna(val):
        return ""
    if val >= 25:
        return "background-color:#fef2f2; color:#dc2626; font-weight:bold"
    if val >= 15:
        return "background-color:#fffbeb; color:#d97706"
    return ""


def _month_html(year: int, month: int, evals_by_day: dict, classes_by_day: dict, color_by_course: dict) -> str:
    """Genera el HTML de UNA grilla de mes con clases (gris) y evaluaciones (color)."""
    head = "".join(
        f"<th style='border:1px solid #e5e7eb;padding:6px;background:#f8fafc;"
        f"font-size:11px;color:#475569;text-transform:uppercase;'>{d}</th>"
        for d in WEEKDAY_ES
    )
    body = ""
    for week in pycal.Calendar(firstweekday=0).monthdayscalendar(year, month):
        cells = ""
        for day in week:
            if day == 0:
                cells += "<td style='border:1px solid #f1f5f9;background:#fafafa;height:90px;'></td>"
                continue
            chips = ""
            # Clases regulares (chip gris con borde del color del curso)
            for cl in classes_by_day.get(day, []):
                color = color_by_course.get(cl["Curso"], "#94a3b8")
                hora = cl.get("Hora", "")
                tip = f"{cl['Curso']} — Clase {hora}".strip()
                chips += (
                    f"<div title=\"{tip}\" style='background:#eef2f7;color:#475569;border-left:3px solid {color};"
                    f"font-size:9px;line-height:1.2;border-radius:3px;padding:1px 4px;margin:2px 0;overflow:hidden;"
                    f"white-space:nowrap;text-overflow:ellipsis;'>Clase</div>"
                )
            # Evaluaciones (chip sólido con el color del curso)
            for ev in evals_by_day.get(day, []):
                color = color_by_course.get(ev["Curso"], "#64748b")
                w = ev.get("Peso (%)")
                wtxt = f" {int(w)}%" if pd.notna(w) and w else ""
                aprox = "≈ " if ev.get("Aprox.") else ""
                title = str(ev["Evaluación"])
                label = (title[:20] + "…") if len(title) > 20 else title
                tip = f"{ev['Curso']} — {title}{wtxt}"
                chips += (
                    f"<div title=\"{tip}\" style='background:{color};color:#fff;font-size:10px;"
                    f"line-height:1.25;border-radius:4px;padding:1px 4px;margin:2px 0;overflow:hidden;"
                    f"white-space:nowrap;text-overflow:ellipsis;'>{aprox}{label}{wtxt}</div>"
                )
            cells += (
                "<td style='border:1px solid #f1f5f9;vertical-align:top;height:90px;padding:3px;'>"
                f"<div style='font-size:11px;font-weight:bold;color:#334155;'>{day:02d}</div>{chips}</td>"
            )
        body += f"<tr>{cells}</tr>"
    return (
        f"<table style='width:100%;border-collapse:collapse;table-layout:fixed;'>"
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    )


def generate_class_events(course: dict, cycle_start_str: str, cycle_end_str: str) -> list:
    """Genera las clases semanales (eventos 'Clase') del curso entre inicio y fin del ciclo."""
    sched = course.get("class_schedule") or {}
    days = sched.get("days") or []
    weekdays = {DIA_A_WEEKDAY[d.lower().strip()] for d in days if d.lower().strip() in DIA_A_WEEKDAY}
    if not weekdays:
        return []
    try:
        start = datetime.strptime(cycle_start_str, "%Y-%m-%d").date()
        end = datetime.strptime(cycle_end_str, "%Y-%m-%d").date()
    except Exception:
        return []
    hora = ""
    if sched.get("start_time") or sched.get("end_time"):
        hora = f"{sched.get('start_time', '')}-{sched.get('end_time', '')}".strip("-")
    cname = course.get("course_name") or "Curso desconocido"
    out = []
    d = start
    while d <= end:
        if d.weekday() in weekdays:
            out.append({"Curso": cname, "Fecha": d.isoformat(), "Hora": hora})
        d += timedelta(days=1)
    return out


def render_grade_calculator(course: dict, key_prefix: str):
    """Calculadora de nota final (escala 0–20) en base a los pesos del curso."""
    gp = [g for g in course.get("grading_policy", []) if g.get("weight_percent")]
    if not gp:
        st.info("Este curso no tiene un sistema de pesos detectado para calcular la nota.")
        return
    st.caption("Ingresa la nota que esperas/obtuviste en cada componente (escala 0–20):")
    total_w = 0.0
    weighted = 0.0
    for i, g in enumerate(gp):
        w = float(g["weight_percent"])
        total_w += w
        nota = st.number_input(
            f"{g['component']} — peso {w:g}%",
            min_value=0.0, max_value=20.0, value=0.0, step=0.5,
            key=f"{key_prefix}_grade_{i}",
        )
        weighted += nota * w / 100.0
    st.markdown("")
    c1, c2 = st.columns(2)
    c1.metric("Nota final estimada", f"{weighted:.2f} / 20")
    c2.metric("Estado (aprobado ≥ 10.5)", "✅ Aprobado" if weighted >= 10.5 else "❌ Desaprobado")
    if round(total_w) != 100:
        st.warning(
            f"⚠️ Los pesos detectados suman {total_w:g}%, no 100%. "
            "La nota se calcula con los pesos tal como aparecen en el sílabo."
        )


# ─────────────────────────────────────
# Datos de demo
# ─────────────────────────────────────
DEMO_DATA = [
    {
        "course_name": "Data Science con Python",
        "professor": "Alexander Quispe",
        "institution": "Universidad del Pacífico",
        "class_schedule": {"days": ["lunes", "miércoles"], "start_time": "19:00", "end_time": "21:00"},
        "grading_policy": [
            {"component": "Tarea 1", "weight_percent": 10, "description": "Pandas y limpieza de datos"},
            {"component": "Tarea 2", "weight_percent": 10, "description": "Visualización"},
            {"component": "Tarea 3", "weight_percent": 10, "description": "APIs y scraping"},
            {"component": "Tarea 4", "weight_percent": 10, "description": "Modelos de ML"},
            {"component": "Tarea 5", "weight_percent": 10, "description": "LLMs y agentes"},
            {"component": "Proyecto Final", "weight_percent": 30, "description": "Startup funcional con demo y pitch"},
            {"component": "Participación", "weight_percent": 20, "description": "Participación en clase"},
        ],
        "events": [
            {"title": "Tarea 1", "event_type": "assignment", "date_iso": "2026-04-01", "week": 3,
             "weight_percent": 10, "description": "Pandas y limpieza de datos", "source_quote": "", "confidence": 0.9},
            {"title": "Tarea 2", "event_type": "assignment", "date_iso": "2026-04-15", "week": 5,
             "weight_percent": 10, "description": "Visualización", "source_quote": "", "confidence": 0.9},
            {"title": "Tarea 3", "event_type": "assignment", "date_iso": "2026-04-29", "week": 7,
             "weight_percent": 10, "description": "APIs y scraping", "source_quote": "", "confidence": 0.9},
            {"title": "Tarea 4", "event_type": "assignment", "date_iso": "2026-05-20", "week": 10,
             "weight_percent": 10, "description": "Modelos de ML", "source_quote": "", "confidence": 0.9},
            {"title": "Tarea 5", "event_type": "assignment", "date_iso": "2026-06-10", "week": 13,
             "weight_percent": 10, "description": "LLMs y agentes", "source_quote": "", "confidence": 0.9},
            {"title": "Proyecto Final", "event_type": "project", "date_iso": "2026-07-01", "week": 16,
             "weight_percent": 30, "description": "Startup funcional + pitch", "source_quote": "", "confidence": 0.95},
            {"title": "Participación", "event_type": "other", "date_iso": None, "week": None,
             "weight_percent": 20, "description": "Continua durante el ciclo", "source_quote": "", "confidence": 0.8},
        ],
        "warnings": [],
    },
    {
        "course_name": "Organización Industrial",
        "professor": "Julio Aguirre",
        "institution": "Universidad del Pacífico",
        "class_schedule": {"days": ["martes", "jueves"], "start_time": "17:30", "end_time": "19:30"},
        "grading_policy": [
            {"component": "Examen Parcial", "weight_percent": 25, "description": "Semanas 1-7"},
            {"component": "Examen Final", "weight_percent": 25, "description": "Semanas 9-15"},
            {"component": "Práctica Calificada 1", "weight_percent": 10, "description": ""},
            {"component": "Práctica Calificada 2", "weight_percent": 10, "description": ""},
            {"component": "Práctica Calificada 3", "weight_percent": 10, "description": ""},
            {"component": "Práctica Calificada 4", "weight_percent": 10, "description": ""},
            {"component": "Trabajo de Investigación", "weight_percent": 10, "description": "Pesa como una práctica más"},
        ],
        "events": [
            {"title": "Práctica Calificada 1", "event_type": "quiz", "date_iso": "2026-04-09", "week": 4,
             "weight_percent": 10, "description": "Temas 1-3", "source_quote": "", "confidence": 0.9},
            {"title": "Práctica Calificada 2", "event_type": "quiz", "date_iso": "2026-04-30", "week": 7,
             "weight_percent": 10, "description": "Temas 4-6", "source_quote": "", "confidence": 0.9},
            {"title": "Examen Parcial", "event_type": "exam", "date_iso": "2026-05-07", "week": 8,
             "weight_percent": 25, "description": "Semanas 1-7", "source_quote": "", "confidence": 0.95},
            {"title": "Práctica Calificada 3", "event_type": "quiz", "date_iso": "2026-05-28", "week": 11,
             "weight_percent": 10, "description": "Temas 8-10", "source_quote": "", "confidence": 0.9},
            {"title": "Trabajo de Investigación", "event_type": "assignment", "date_iso": "2026-06-18", "week": 14,
             "weight_percent": 10, "description": "Entrega del paper", "source_quote": "", "confidence": 0.88},
            {"title": "Práctica Calificada 4", "event_type": "quiz", "date_iso": None, "week": None,
             "weight_percent": 10, "description": "Temas 11-13 (fecha por confirmar con el profesor)",
             "source_quote": "", "confidence": 0.5},
            {"title": "Examen Final", "event_type": "exam", "date_iso": "2026-07-02", "week": 16,
             "weight_percent": 25, "description": "Semanas 9-15", "source_quote": "", "confidence": 0.95},
        ],
        "warnings": ["La Práctica Calificada 4 no tiene fecha exacta en el sílabo — confírmala con el profesor."],
    },
]


# ─────────────────────────────────────
# Helpers
# ─────────────────────────────────────
def configured_api_key() -> str:
    """
    Devuelve la API key del SERVIDOR: del entorno (.env en local) o de st.secrets
    (en el deploy). Para uso interno — NUNCA se muestra en la UI para no exponerla.
    """
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        try:
            key = (st.secrets.get("ANTHROPIC_API_KEY", "") or "").strip()
        except Exception:
            pass
    return key


def normalize_all_courses(course_data_list: list, cycle_start_str: str) -> list:
    """
    Aplica normalize_events() a los eventos de cada curso.
    - Convierte date_text a ISO cuando el LLM no devolvió date_iso.
    - Calcula fecha aproximada desde la semana cuando no hay fecha exacta.
    - Marca date_approximate=True en las fechas estimadas.
    Funciona igual para sílabos reales (salida del LLM) y para el modo demo.
    """
    normalized = []
    for course in course_data_list:
        c = dict(course)
        c["events"] = normalize_events(course.get("events", []), cycle_start_str)
        normalized.append(c)
    return normalized


EVENT_COLUMNS = [
    "Curso", "Evaluación", "Tipo", "Fecha", "Semana", "Peso (%)",
    "Descripción", "Confianza", "Aprox.", "Cita del sílabo",
]


def flatten_events(course_data_list: list) -> pd.DataFrame:
    """Convierte lista de cursos en DataFrame plano de eventos."""
    rows = []
    for course in course_data_list:
        course_name = course.get("course_name") or "Curso desconocido"
        for event in course.get("events", []):
            rows.append({
                "Curso": course_name,
                "Evaluación": event.get("title", ""),
                "Tipo": tipo_es(event.get("event_type", "other")),
                "Fecha": event.get("date_iso"),
                "Semana": event.get("week"),
                "Peso (%)": event.get("weight_percent"),
                "Descripción": event.get("description", ""),
                "Confianza": event.get("confidence"),
                "Aprox.": event.get("date_approximate", False),
                "Cita del sílabo": event.get("source_quote", ""),
            })
    # Siempre devolver las columnas esperadas, incluso sin eventos,
    # para que el dashboard no falle con KeyError cuando un sílabo no arroja evaluaciones.
    return pd.DataFrame(rows, columns=EVENT_COLUMNS)


# ─────────────────────────────────────
# Session state
# ─────────────────────────────────────
if "processed_data" not in st.session_state:
    st.session_state.processed_data = None
if "events_df" not in st.session_state:
    st.session_state.events_df = None


# ─────────────────────────────────────
# Sidebar
# ─────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Configuración del ciclo")

    university = st.text_input("Universidad", value="Universidad del Pacífico")

    col1, col2 = st.columns(2)
    with col1:
        cycle_start = st.date_input("Inicio del ciclo", value=date(2026, 3, 17))
    with col2:
        cycle_end = st.date_input("Fin del ciclo", value=date(2026, 7, 5))

    st.divider()

    _server_key = configured_api_key()
    if _server_key:
        # Hay key configurada (servidor): cárgala al entorno para el extractor,
        # sin mostrarla. El campo queda vacío como override opcional.
        os.environ["ANTHROPIC_API_KEY"] = _server_key
        st.success("✅ API key configurada")
        api_key_input = st.text_input(
            "🔑 Usar otra API Key (opcional)",
            type="password",
            value="",
            help="Ya hay una key configurada. Deja vacío para usarla, o pega otra para sobrescribir.",
        )
    else:
        api_key_input = st.text_input(
            "🔑 API Key de Anthropic",
            type="password",
            value="",
            help="Pega tu key de console.anthropic.com. En local puedes ponerla en un archivo .env.",
        )
    if api_key_input:
        os.environ["ANTHROPIC_API_KEY"] = api_key_input.strip()

    st.divider()
    st.markdown("**Cramly** usa Claude AI para extraer automáticamente evaluaciones, fechas y pesos de tus sílabos en PDF.")
    st.markdown("🛠 Stack: Claude API · pdfplumber · Streamlit · Python")


# ─────────────────────────────────────
# Header
# ─────────────────────────────────────
st.markdown('<div class="main-title">🎓 Cramly</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="subtitle">Tu copiloto académico — sube tus sílabos, conoce tus fechas, notas y semanas críticas</div>',
    unsafe_allow_html=True,
)
st.markdown("")


# ─────────────────────────────────────
# Upload / Demo tabs
# ─────────────────────────────────────
tab_upload, tab_demo = st.tabs(["📤 Subir mis sílabos", "🎯 Modo demo"])

with tab_upload:
    uploaded_files = st.file_uploader(
        "Sube tus sílabos en PDF (hasta 8 archivos)",
        type=["pdf"],
        accept_multiple_files=True,
        help="PDFs con texto seleccionable dan mejor resultado. PDFs escaneados pueden tener menor precisión.",
    )

    if uploaded_files:
        if len(uploaded_files) > 8:
            st.warning("⚠️ Máximo 8 archivos. Se procesarán los primeros 8.")
            uploaded_files = uploaded_files[:8]

        st.success(f"✅ {len(uploaded_files)} archivo(s) listo(s)")
        st.info(
            "💡 ¿Tu curso tiene **varios PDFs** (sílabo base + un complemento con las fechas exactas)? "
            "Ponles el **mismo nombre de curso** y Cramly los combinará en uno solo."
        )

        course_names = []
        for i, f in enumerate(uploaded_files):
            default_name = f.name.replace(".pdf", "").replace("_", " ").replace("-", " ").title()
            name = st.text_input(
                f"Nombre del curso para **{f.name}**",
                value=default_name,
                key=f"cname_{i}",
            )
            course_names.append(name)

        # Agrupar PDFs por nombre de curso (mismo nombre → mismo curso)
        groups = {}
        for f, cname in zip(uploaded_files, course_names):
            key = (cname or f.name).strip()
            groups.setdefault(key, []).append(f)

        if len(groups) < len(uploaded_files):
            merged = [f"**{c}** ({len(fs)} PDFs)" for c, fs in groups.items() if len(fs) > 1]
            st.caption("🔗 Se combinarán: " + " · ".join(merged))

        if st.button("🚀 Procesar sílabos con IA", type="primary", use_container_width=True):
            if not os.getenv("ANTHROPIC_API_KEY"):
                st.error("❌ Agrega tu API key de Anthropic en el panel lateral.")
            else:
                results = []
                progress_bar = st.progress(0)
                status = st.empty()
                total_groups = len(groups)

                for i, (cname, files) in enumerate(groups.items()):
                    status.info(f"🤖 Analizando **{cname}** con Claude (lectura directa del PDF)...")
                    progress_bar.progress(i / total_groups + 0.4 / total_groups)

                    pdfs = []
                    for f in files:
                        f.seek(0)
                        b = f.read()
                        if b:
                            pdfs.append(b)

                    if not pdfs:
                        st.warning(f"⚠️ No se pudo leer ningún PDF de '{cname}'. Se omite.")
                        continue

                    # Claude lee el/los PDF(s) de forma nativa (preserva tablas).
                    # Varios PDFs con el mismo curso se combinan en una sola extracción.
                    data = extract_syllabus_data(
                        pdf_bytes=pdfs,
                        course_name=cname,
                        cycle_start=cycle_start.isoformat(),
                    )

                    if data.get("error"):
                        status.info(f"↩️ Reintentando **{cname}** con extracción de texto...")
                        fallback_text = "\n\n".join(extract_text_from_pdf(f) for f in files)
                        data = extract_syllabus_data(
                            text=fallback_text,
                            course_name=cname,
                            cycle_start=cycle_start.isoformat(),
                        )

                    if data.get("error"):
                        st.error(f"⚠️ Error en {cname}: {data['error']}")

                    results.append(data)
                    progress_bar.progress((i + 1) / total_groups)

                status.success("✅ ¡Procesamiento completado!")
                results = normalize_all_courses(results, cycle_start.isoformat())
                st.session_state.processed_data = results
                st.session_state.events_df = flatten_events(results)
                st.rerun()

with tab_demo:
    st.markdown("### 🎯 Demo con datos de ejemplo")
    st.markdown(
        "Carga 2 cursos simulados (**Data Science con Python** y **Organización Industrial**) "
        "para explorar todas las funciones sin necesidad de sílabos propios."
    )
    if st.button("▶️ Cargar datos de demo", type="primary", use_container_width=True):
        demo = normalize_all_courses(DEMO_DATA, cycle_start.isoformat())
        st.session_state.processed_data = demo
        st.session_state.events_df = flatten_events(demo)
        st.rerun()


# ─────────────────────────────────────
# Resultados
# ─────────────────────────────────────
if st.session_state.events_df is not None and st.session_state.events_df.empty:
    st.divider()
    st.warning(
        "😕 No se detectaron evaluaciones en los sílabos procesados. "
        "Puede deberse a un PDF sin cronograma claro o a un error de extracción. "
        "Revisa el mensaje de error de arriba (si lo hay), verifica tu API key, "
        "o prueba el **🎯 Modo demo** para ver la app en acción."
    )

elif st.session_state.events_df is not None:
    df: pd.DataFrame = st.session_state.events_df
    data: list = st.session_state.processed_data

    st.divider()

    # ── Métricas ──────────────────────
    st.markdown("## 📊 Dashboard")

    total_courses = len(data)
    total_events = len(df)
    no_date_count = int(df["Fecha"].isna().sum())
    no_date_pct = int(no_date_count / max(total_events, 1) * 100)

    df_dated = df[df["Fecha"].notna()].copy()
    df_dated["Fecha_dt"] = pd.to_datetime(df_dated["Fecha"])
    future = df_dated[df_dated["Fecha_dt"] >= pd.Timestamp.now()]

    if not future.empty:
        nxt = future.sort_values("Fecha_dt").iloc[0]
        next_eval_label = f"{nxt['Evaluación'][:22]}…" if len(nxt["Evaluación"]) > 22 else nxt["Evaluación"]
        next_eval_date = nxt["Fecha"]
    elif not df_dated.empty:
        nxt = df_dated.sort_values("Fecha_dt").iloc[-1]
        next_eval_label = nxt["Evaluación"][:22]
        next_eval_date = nxt["Fecha"]
    else:
        next_eval_label, next_eval_date = "Sin fechas", "—"

    workload_df = calculate_workload_scores(df)
    if not workload_df.empty:
        busiest = workload_df.loc[workload_df["Score"].idxmax()]
        busiest_text = f"Sem. {int(busiest['Semana'])} (score {int(busiest['Score'])})"
    else:
        busiest_text = "—"

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("📚 Cursos", total_courses)
    c2.metric("📝 Evaluaciones", total_events)
    c3.metric("⏰ Próxima fecha", next_eval_date)
    c4.metric("🔥 Semana más cargada", busiest_text)
    c5.metric("❓ Sin fecha exacta", f"{no_date_count} ({no_date_pct}%)")

    # Advertencias globales
    all_warnings = []
    for course in data:
        for w in course.get("warnings", []):
            all_warnings.append(f"**{course.get('course_name', 'Curso')}:** {w}")
    if all_warnings:
        with st.expander(f"⚠️ {len(all_warnings)} advertencia(s) detectada(s) en los sílabos"):
            for w in all_warnings:
                st.markdown(f"- {w}")

    st.markdown("")

    # ── Tabs: General + Calendario + una por curso ─
    color_by_course = course_color_map(sorted(df["Curso"].unique().tolist()))
    course_keys = [c.get("course_name") or "Curso desconocido" for c in data]

    # Clases regulares (eventos "Clase") de todos los cursos para el calendario
    class_events = []
    for course in data:
        class_events.extend(generate_class_events(course, cycle_start.isoformat(), cycle_end.isoformat()))
    classes_df = pd.DataFrame(class_events) if class_events else pd.DataFrame(columns=["Curso", "Fecha", "Hora"])

    tab_objs = st.tabs(["📊 General", "📅 Calendario"] + [f"📚 {n}" for n in course_keys])

    # ===== Tab General (carga académica) =====
    with tab_objs[0]:
        st.markdown("## Carga académica por semana")
        if not workload_df.empty:
            color_map = {
                "Alta carga 🔴": "#ef4444",
                "Media carga 🟡": "#f59e0b",
                "Baja carga 🟢": "#22c55e",
            }
            fig = px.bar(
                workload_df, x="Semana", y="Score", color="Nivel",
                color_discrete_map=color_map,
                title="Score de carga académica por semana",
                labels={"Score": "Score de carga", "Semana": "Semana del ciclo"},
                text="Score",
            )
            fig.update_layout(
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                font_family="Arial, sans-serif",
            )
            fig.update_xaxes(dtick=1, tickmode="linear")
            fig.update_traces(textposition="outside")
            st.plotly_chart(fig, use_container_width=True)

            st.markdown("### 🔎 Detalle por semana")
            for _, wrow in workload_df.sort_values("Semana").iterrows():
                semana = int(wrow["Semana"])
                nivel = wrow["Nivel"]
                week_events = df[pd.to_numeric(df["Semana"], errors="coerce") == semana]
                evals = week_events[["Evaluación", "Curso", "Peso (%)"]].to_dict("records")
                detalle = " · ".join(
                    f"{e['Evaluación']} ({e['Curso']}"
                    + (f", {int(e['Peso (%)'])}%" if pd.notna(e['Peso (%)']) else "")
                    + ")"
                    for e in evals
                ) or "Sin evaluaciones"
                css = "critical-week" if "Alta" in nivel else "warning-week" if "Media" in nivel else "ok-week"
                st.markdown(
                    f'<div class="{css}"><strong>Semana {semana}</strong> — {nivel} '
                    f'(score {int(wrow["Score"])}, peso acumulado {int(wrow["Peso_total"])}%)<br>'
                    f'<small>{detalle}</small></div>',
                    unsafe_allow_html=True,
                )
            st.caption(
                "El **score de carga** combina el número de evaluaciones de la semana (×10) "
                "más la suma de sus pesos. 🔴 Alta · 🟡 Media · 🟢 Baja."
            )
        else:
            st.info("No hay suficientes datos de semanas para generar el gráfico de carga.")

    # ===== Tab Calendario (vista de mes con navegación) =====
    with tab_objs[1]:
        st.markdown("## Calendario del ciclo")
        # Leyenda de colores por curso
        legend = " &nbsp; ".join(
            f"<span style='display:inline-block;width:11px;height:11px;border-radius:3px;"
            f"background:{color};margin-right:4px;'></span>{cur}"
            for cur, color in color_by_course.items()
        )
        legend += (
            " &nbsp; <span style='display:inline-block;width:11px;height:11px;border-radius:3px;"
            "background:#eef2f7;border:1px solid #cbd5e1;margin-right:4px;'></span>Clase"
        )
        st.markdown(f"<div style='font-size:12px;margin-bottom:6px;'>{legend}</div>", unsafe_allow_html=True)

        # Lista de meses del ciclo
        months = []
        yy, mm = cycle_start.year, cycle_start.month
        while (yy, mm) <= (cycle_end.year, cycle_end.month):
            months.append((yy, mm))
            mm += 1
            if mm > 12:
                mm = 1
                yy += 1
        if "cal_idx" not in st.session_state:
            st.session_state.cal_idx = 0
        st.session_state.cal_idx = max(0, min(st.session_state.cal_idx, len(months) - 1))

        cprev, cmid, cnext = st.columns([1, 4, 1])
        if cprev.button("◀", use_container_width=True, disabled=st.session_state.cal_idx == 0):
            st.session_state.cal_idx -= 1
        if cnext.button("▶", use_container_width=True, disabled=st.session_state.cal_idx >= len(months) - 1):
            st.session_state.cal_idx += 1
        cur_y, cur_m = months[st.session_state.cal_idx]
        cmid.markdown(
            f"<div style='text-align:center;font-weight:800;font-size:1.25rem;text-transform:uppercase;'>"
            f"{MONTH_ES[cur_m]} {cur_y}</div>",
            unsafe_allow_html=True,
        )

        # Eventos y clases del mes seleccionado
        dfd = df[df["Fecha"].notna()].copy()
        dfd["_dt"] = pd.to_datetime(dfd["Fecha"])
        evals_by_day = {}
        for _, r in dfd[(dfd["_dt"].dt.year == cur_y) & (dfd["_dt"].dt.month == cur_m)].iterrows():
            evals_by_day.setdefault(r["_dt"].day, []).append(r)

        classes_by_day = {}
        if not classes_df.empty:
            cdf = classes_df.copy()
            cdf["_dt"] = pd.to_datetime(cdf["Fecha"])
            for _, r in cdf[(cdf["_dt"].dt.year == cur_y) & (cdf["_dt"].dt.month == cur_m)].iterrows():
                classes_by_day.setdefault(r["_dt"].day, []).append(r)

        st.markdown(_month_html(cur_y, cur_m, evals_by_day, classes_by_day, color_by_course),
                    unsafe_allow_html=True)

        no_date = df[df["Fecha"].isna()]
        if not no_date.empty:
            with st.expander(f"⚠️ {len(no_date)} evaluación(es) sin fecha — revisar en el sílabo"):
                st.dataframe(
                    no_date[["Curso", "Evaluación", "Tipo", "Semana", "Peso (%)", "Cita del sílabo"]],
                    use_container_width=True,
                )

        st.divider()
        st.markdown("## 📆 Exportar a Google Calendar")
        df_ics = df[df["Fecha"].notna()].copy()
        if not df_ics.empty:
            st.download_button(
                "⬇️ Descargar .ics (todas las evaluaciones)",
                data=generate_ics(df_ics),
                file_name="cramly.ics",
                mime="text/calendar",
                use_container_width=True,
            )
            st.caption(
                "Impórtalo en Google Calendar: Configuración → Importar y exportar → Importar. "
                "(También funciona en Apple Calendar y Outlook.)"
            )
        else:
            st.info("No hay evaluaciones con fecha exacta para exportar todavía.")

    # ===== Tabs por curso =====
    for idx, course in enumerate(data):
        cname = course.get("course_name") or "Curso desconocido"
        with tab_objs[idx + 2]:
            course_df = df[df["Curso"] == cname].copy()
            prof = course.get("professor")
            st.markdown(f"### {cname}")
            if prof:
                st.caption(f"👨‍🏫 Docente: {prof}")

            # ✏️ Corregir / complementar con IA (info que el profe dio en clase)
            with st.expander("✏️ Corregir o complementar con IA", expanded=False):
                st.caption(
                    "Dile a Cramly cualquier dato que el profe mencionó en clase y no estaba en el sílabo. "
                    "Ej: *\"La Práctica Calificada 4 es el jueves 25 de junio\"* o "
                    "*\"El trabajo de investigación se movió al sábado 4 de julio\"*."
                )
                instruction = st.text_input(
                    "Tu indicación", key=f"refine_input_{idx}",
                    placeholder="La Práctica Calificada 4 es el jueves 25 de junio",
                    label_visibility="collapsed",
                )
                if st.button("Aplicar con IA", key=f"refine_btn_{idx}"):
                    if not os.getenv("ANTHROPIC_API_KEY"):
                        st.error("❌ Agrega tu API key de Anthropic en el panel lateral.")
                    elif not instruction.strip():
                        st.warning("Escribe una indicación primero.")
                    else:
                        with st.spinner("Actualizando con IA..."):
                            refined = refine_course_data(course, instruction, cycle_start.isoformat())
                        if refined.get("error"):
                            st.error(f"⚠️ {refined['error']}")
                        else:
                            pdata = st.session_state.processed_data
                            pdata[idx] = normalize_all_courses([refined], cycle_start.isoformat())[0]
                            st.session_state.processed_data = pdata
                            st.session_state.events_df = flatten_events(pdata)
                            st.success("✅ ¡Actualizado! Revisa el calendario y la tabla.")
                            st.rerun()

            st.markdown("#### 🧮 Calculadora de nota final")
            render_grade_calculator(course, key_prefix=f"calc_{idx}")

            st.divider()
            st.markdown("#### 📋 Evaluaciones del curso")
            disp = course_df.copy()
            disp["_sort"] = pd.to_datetime(disp["Fecha"], errors="coerce")
            disp = disp.sort_values("_sort", na_position="last").drop(columns=["_sort"])
            cols_show = ["Evaluación", "Tipo", "Fecha", "Semana", "Peso (%)", "Aprox.", "Descripción"]
            st.dataframe(
                disp[cols_show].style.map(color_weight, subset=["Peso (%)"]),
                use_container_width=True, height=360,
            )
