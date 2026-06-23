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
from datetime import date, datetime

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
from src.llm_extractor import extract_syllabus_data
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
    "assignment": "Trabajo / Entrega",
    "presentation": "Exposición",
    "quiz": "Control / Quiz",
    "project": "Proyecto",
    "reading": "Lectura",
    "other": "Otro",
    "class": "Clase",
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


def _month_html(year: int, month: int, by_day: dict, color_by_course: dict) -> str:
    """Genera el HTML de una grilla de mes con los eventos en cada día."""
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
                cells += "<td style='border:1px solid #f1f5f9;background:#fafafa;height:82px;'></td>"
                continue
            chips = ""
            for ev in by_day.get(day, []):
                color = color_by_course.get(ev["Curso"], "#64748b")
                w = ev.get("Peso (%)")
                wtxt = f" {int(w)}%" if pd.notna(w) and w else ""
                aprox = "≈ " if ev.get("Aprox.") else ""
                title = str(ev["Evaluación"])
                label = (title[:22] + "…") if len(title) > 22 else title
                tip = f"{ev['Curso']} — {title}{wtxt}"
                chips += (
                    f"<div title=\"{tip}\" style='background:{color};color:#fff;font-size:10px;"
                    f"line-height:1.25;border-radius:4px;padding:1px 4px;margin:2px 0;overflow:hidden;"
                    f"white-space:nowrap;text-overflow:ellipsis;'>{aprox}{label}{wtxt}</div>"
                )
            cells += (
                "<td style='border:1px solid #f1f5f9;vertical-align:top;height:82px;padding:3px;'>"
                f"<div style='font-size:11px;font-weight:bold;color:#334155;'>{day:02d}</div>{chips}</td>"
            )
        body += f"<tr>{cells}</tr>"
    return (
        f"<div style='margin:0.4rem 0 1rem;'>"
        f"<div style='font-weight:800;font-size:1.05rem;text-transform:uppercase;margin-bottom:4px;'>"
        f"{MONTH_ES[month]} {year}</div>"
        f"<table style='width:100%;border-collapse:collapse;table-layout:fixed;'>"
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def render_month_calendar(df_dated: pd.DataFrame, color_by_course: dict):
    """Renderiza una vista de calendario por mes (todos los meses con eventos)."""
    if df_dated.empty:
        st.info("No hay evaluaciones con fecha exacta para mostrar en el calendario.")
        return
    tmp = df_dated.copy()
    tmp["_dt"] = pd.to_datetime(tmp["Fecha"])
    for period in sorted(tmp["_dt"].dt.to_period("M").unique()):
        year, month = period.year, period.month
        sub = tmp[(tmp["_dt"].dt.year == year) & (tmp["_dt"].dt.month == month)]
        by_day = {}
        for _, r in sub.iterrows():
            by_day.setdefault(r["_dt"].day, []).append(r)
        st.markdown(_month_html(year, month, by_day, color_by_course), unsafe_allow_html=True)


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
    c2.metric("Estado (mínimo 11)", "✅ Aprobado" if weighted >= 11 else "❌ Desaprobado")
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
        "grading_policy": [
            {"component": "Proyecto Final", "weight_percent": 30, "description": "Startup funcional con demo y pitch"},
            {"component": "Controles de lectura", "weight_percent": 25, "description": "Controles semanales"},
            {"component": "Tareas", "weight_percent": 25, "description": "Tareas prácticas"},
            {"component": "Participación", "weight_percent": 20, "description": "Participación en clase"},
        ],
        "events": [
            {"title": "Presentación Final – Startup", "event_type": "presentation",
             "date_iso": "2026-06-23", "week": 16, "weight_percent": 30,
             "description": "Pitch de 7 min + Q&A", "source_quote": "Presentaciones: Martes 23 y miércoles 24 de junio", "confidence": 0.98},
            {"title": "Control de Lectura 5", "event_type": "quiz",
             "date_iso": None, "week": 11, "weight_percent": 5,
             "description": "Control semanal (sin fecha exacta en el sílabo)",
             "source_quote": "Controles de lectura semanales", "confidence": 0.70},
            {"title": "Entrega Avance del Proyecto", "event_type": "project",
             "date_iso": "2026-05-25", "week": 11, "weight_percent": 20,
             "description": "Avance intermedio de la startup", "source_quote": "Avance del proyecto semana 11", "confidence": 0.92},
            {"title": "Tarea 3 – Agentes crewAI", "event_type": "assignment",
             "date_iso": "2026-06-01", "week": 12, "weight_percent": 8,
             "description": "Implementar agente con crewAI", "source_quote": "Tareas prácticas del curso", "confidence": 0.85},
        ],
        "warnings": [],
    },
    {
        "course_name": "Econometría II",
        "professor": "Carlos Mendoza",
        "institution": "Universidad del Pacífico",
        "grading_policy": [
            {"component": "Examen Parcial", "weight_percent": 30, "description": ""},
            {"component": "Examen Final", "weight_percent": 35, "description": ""},
            {"component": "Prácticas Calificadas", "weight_percent": 25, "description": "3 prácticas"},
            {"component": "Trabajo de Investigación", "weight_percent": 10, "description": ""},
        ],
        "events": [
            {"title": "Práctica Calificada 1", "event_type": "exam",
             "date_iso": "2026-04-28", "week": 5, "weight_percent": 8,
             "description": "Temas 1-3", "source_quote": "PC1 semana 5", "confidence": 0.90},
            {"title": "Examen Parcial", "event_type": "exam",
             "date_iso": "2026-05-26", "week": 11, "weight_percent": 30,
             "description": "Temas semanas 1-10", "source_quote": "Parcial semana 11", "confidence": 0.95},
            {"title": "Práctica Calificada 2", "event_type": "exam",
             "date_iso": "2026-06-09", "week": 13, "weight_percent": 8,
             "description": "Temas 4-7", "source_quote": "PC2 semana 13", "confidence": 0.90},
            {"title": "Trabajo de Investigación", "event_type": "assignment",
             "date_iso": "2026-06-16", "week": 14, "weight_percent": 10,
             "description": "Entrega del paper", "source_quote": "Entrega semana 14", "confidence": 0.88},
            {"title": "Examen Final", "event_type": "exam",
             "date_iso": "2026-06-30", "week": 17, "weight_percent": 35,
             "description": "Temas semanas 11-16", "source_quote": "Final semana 17", "confidence": 0.95},
        ],
        "warnings": ["La PC3 no tiene fecha explícita en el sílabo — requiere revisión manual."],
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
        "Sube tus sílabos en PDF (máximo 5 archivos)",
        type=["pdf"],
        accept_multiple_files=True,
        help="PDFs con texto seleccionable dan mejor resultado. PDFs escaneados pueden tener menor precisión.",
    )

    if uploaded_files:
        if len(uploaded_files) > 5:
            st.warning("⚠️ Máximo 5 sílabos. Se procesarán los primeros 5.")
            uploaded_files = uploaded_files[:5]

        st.success(f"✅ {len(uploaded_files)} archivo(s) listo(s)")

        course_names = []
        for i, f in enumerate(uploaded_files):
            default_name = f.name.replace(".pdf", "").replace("_", " ").replace("-", " ").title()
            name = st.text_input(
                f"Nombre del curso para **{f.name}**",
                value=default_name,
                key=f"cname_{i}",
            )
            course_names.append(name)

        if st.button("🚀 Procesar sílabos con IA", type="primary", use_container_width=True):
            if not os.getenv("ANTHROPIC_API_KEY"):
                st.error("❌ Agrega tu API key de Anthropic en el panel lateral.")
            else:
                results = []
                progress_bar = st.progress(0)
                status = st.empty()

                for i, (f, cname) in enumerate(zip(uploaded_files, course_names)):
                    base = i / len(uploaded_files)

                    status.info(f"🤖 Analizando **{cname}** con Claude (lectura directa del PDF)...")
                    progress_bar.progress(base + 0.4 / len(uploaded_files))

                    f.seek(0)
                    pdf_bytes = f.read()

                    if not pdf_bytes:
                        st.warning(f"⚠️ No se pudo leer '{f.name}'. Se omite.")
                        continue

                    # Claude lee el PDF de forma nativa (preserva tablas de cronograma y notas).
                    # Si el PDF fallara, hace fallback a texto extraído con pdfplumber.
                    data = extract_syllabus_data(
                        pdf_bytes=pdf_bytes,
                        course_name=cname,
                        cycle_start=cycle_start.isoformat(),
                    )

                    if data.get("error"):
                        status.info(f"↩️ Reintentando **{cname}** con extracción de texto...")
                        fallback_text = extract_text_from_pdf(f)
                        data = extract_syllabus_data(
                            text=fallback_text,
                            course_name=cname,
                            cycle_start=cycle_start.isoformat(),
                        )

                    if data.get("error"):
                        st.error(f"⚠️ Error en {cname}: {data['error']}")

                    results.append(data)
                    progress_bar.progress((i + 1) / len(uploaded_files))

                status.success("✅ ¡Procesamiento completado!")
                results = normalize_all_courses(results, cycle_start.isoformat())
                st.session_state.processed_data = results
                st.session_state.events_df = flatten_events(results)
                st.rerun()

with tab_demo:
    st.markdown("### 🎯 Demo con datos de ejemplo")
    st.markdown(
        "Carga 2 cursos simulados (**Data Science con Python** y **Econometría II**) "
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

    # ── Tabs: General + una por curso ─
    color_by_course = course_color_map(sorted(df["Curso"].unique().tolist()))
    course_keys = [c.get("course_name") or "Curso desconocido" for c in data]

    tab_objs = st.tabs(["📊 General"] + [f"📚 {n}" for n in course_keys])

    # ===== Tab General =====
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

        st.divider()
        st.markdown("## 📅 Calendario del ciclo")
        # Leyenda de colores por curso
        legend = " &nbsp; ".join(
            f"<span style='display:inline-block;width:11px;height:11px;border-radius:3px;"
            f"background:{color};margin-right:4px;'></span>{cur}"
            for cur, color in color_by_course.items()
        )
        st.markdown(f"<div style='font-size:12px;margin-bottom:6px;'>{legend}</div>", unsafe_allow_html=True)
        render_month_calendar(df[df["Fecha"].notna()], color_by_course)

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
                "⬇️ Descargar .ics (todos los cursos)",
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
        with tab_objs[idx + 1]:
            course_df = df[df["Curso"] == cname].copy()
            prof = course.get("professor")
            st.markdown(f"### {cname}")
            if prof:
                st.caption(f"👨‍🏫 Docente: {prof}")

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
