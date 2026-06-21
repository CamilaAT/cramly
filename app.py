"""
app.py — Sílabo2Calendar
Aplicación principal en Streamlit.
Convierte sílabos universitarios en PDF a calendarios inteligentes usando Claude AI.
"""
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
from src.llm_extractor import extract_syllabus_data
from src.pdf_extractor import extract_text_from_pdf
from src.workload import calculate_workload_scores, get_critical_weeks_summary

# ─────────────────────────────────────
# Configuración de página
# ─────────────────────────────────────
st.set_page_config(
    page_title="Sílabo2Calendar",
    page_icon="📅",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .main-title  { font-size: 2.4rem; font-weight: 800; color: #1e293b; line-height: 1.1; }
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
             "date_iso": "2026-05-19", "week": 10, "weight_percent": 5,
             "description": "Control semanal", "source_quote": "Controles de lectura semanales", "confidence": 0.80},
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
def get_api_key() -> str:
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        try:
            key = st.secrets.get("ANTHROPIC_API_KEY", "")
        except Exception:
            pass
    return key


def flatten_events(course_data_list: list) -> pd.DataFrame:
    """Convierte lista de cursos en DataFrame plano de eventos."""
    rows = []
    for course in course_data_list:
        course_name = course.get("course_name") or "Curso desconocido"
        for event in course.get("events", []):
            rows.append({
                "Curso": course_name,
                "Evaluación": event.get("title", ""),
                "Tipo": event.get("event_type", "other"),
                "Fecha": event.get("date_iso"),
                "Semana": event.get("week"),
                "Peso (%)": event.get("weight_percent"),
                "Descripción": event.get("description", ""),
                "Confianza": event.get("confidence"),
                "Aprox.": event.get("date_approximate", False),
                "Cita del sílabo": event.get("source_quote", ""),
            })
    return pd.DataFrame(rows)


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

    api_key_input = st.text_input(
        "🔑 API Key de Anthropic",
        type="password",
        value=get_api_key(),
        help="Obtén tu key en console.anthropic.com. También puedes ponerla en un archivo .env",
    )
    if api_key_input:
        os.environ["ANTHROPIC_API_KEY"] = api_key_input

    st.divider()
    st.markdown("**Sílabo2Calendar** usa Claude AI para extraer automáticamente evaluaciones, fechas y pesos de tus sílabos en PDF.")
    st.markdown("🛠 Stack: Claude API · pdfplumber · Streamlit · Python")


# ─────────────────────────────────────
# Header
# ─────────────────────────────────────
st.markdown('<div class="main-title">📅 Sílabo2Calendar</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="subtitle">Convierte tus sílabos universitarios en un calendario inteligente — impulsado por IA</div>',
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

                    status.info(f"📄 Extrayendo texto de **{cname}**...")
                    progress_bar.progress(base + 0.15 / len(uploaded_files))

                    text = extract_text_from_pdf(f)

                    if not text or len(text) < 80:
                        st.warning(
                            f"⚠️ Poco texto extraído de '{f.name}'. "
                            "El PDF puede estar escaneado — usa un PDF con texto seleccionable para mejor resultado."
                        )
                        text = f"Sílabo del curso {cname}. Sin texto extraíble."

                    status.info(f"🤖 Analizando **{cname}** con Claude AI...")
                    progress_bar.progress(base + 0.5 / len(uploaded_files))

                    data = extract_syllabus_data(text, cname, cycle_start.isoformat())

                    if data.get("error"):
                        st.error(f"⚠️ Error en {cname}: {data['error']}")

                    results.append(data)
                    progress_bar.progress((i + 1) / len(uploaded_files))

                status.success("✅ ¡Procesamiento completado!")
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
        st.session_state.processed_data = DEMO_DATA
        st.session_state.events_df = flatten_events(DEMO_DATA)
        st.rerun()


# ─────────────────────────────────────
# Resultados
# ─────────────────────────────────────
if st.session_state.events_df is not None:
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

    # ── Tabs de resultados ───────────
    rt1, rt2, rt3, rt4 = st.tabs([
        "📋 Evaluaciones",
        "📈 Carga académica",
        "📅 Calendario",
        "📤 Exportar",
    ])

    # ── Tab 1: Tabla ─────────────────
    with rt1:
        st.markdown("### Todas tus evaluaciones")

        courses_list = ["Todos"] + sorted(df["Curso"].unique().tolist())
        selected = st.selectbox("Filtrar por curso", courses_list)

        display = df.copy()
        if selected != "Todos":
            display = display[display["Curso"] == selected]

        display["_sort"] = pd.to_datetime(display["Fecha"], errors="coerce")
        display = display.sort_values("_sort", na_position="last").drop(columns=["_sort"])

        cols_show = ["Curso", "Evaluación", "Tipo", "Fecha", "Semana", "Peso (%)", "Aprox.", "Descripción"]

        def color_weight(val):
            if pd.isna(val):
                return ""
            if val >= 25:
                return "background-color:#fef2f2; color:#dc2626; font-weight:bold"
            if val >= 15:
                return "background-color:#fffbeb; color:#d97706"
            return ""

        styled = display[cols_show].style.map(color_weight, subset=["Peso (%)"])
        st.dataframe(styled, use_container_width=True, height=420)

        csv = display.to_csv(index=False, encoding="utf-8-sig")
        st.download_button("⬇️ Descargar CSV", csv, "evaluaciones.csv", "text/csv")

    # ── Tab 2: Carga académica ────────
    with rt2:
        st.markdown("### Carga académica por semana")

        if not workload_df.empty:
            color_map = {
                "Alta carga 🔴": "#ef4444",
                "Media carga 🟡": "#f59e0b",
                "Baja carga 🟢": "#22c55e",
            }
            fig = px.bar(
                workload_df,
                x="Semana",
                y="Score",
                color="Nivel",
                color_discrete_map=color_map,
                title="Score de carga académica por semana",
                labels={"Score": "Score de carga", "Semana": "Semana del ciclo"},
                text="Score",
            )
            fig.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font_family="Inter, sans-serif",
            )
            fig.update_traces(textposition="outside")
            st.plotly_chart(fig, use_container_width=True)

            # Semanas críticas
            critical_weeks = get_critical_weeks_summary(df, workload_df)
            if critical_weeks:
                st.markdown("### 🚨 Semanas críticas")
                for cw in critical_weeks:
                    evals_str = " · ".join(cw["evaluaciones"])
                    st.markdown(
                        f'<div class="critical-week"><strong>Semana {cw["semana"]}</strong> '
                        f'— Score {cw["score"]} | Peso acumulado: {cw["peso_total"]}% <br>'
                        f'<small>{evals_str}</small></div>',
                        unsafe_allow_html=True,
                    )

            # Gráficos secundarios
            col_a, col_b = st.columns(2)
            with col_a:
                type_counts = df["Tipo"].value_counts()
                fig2 = px.pie(
                    values=type_counts.values,
                    names=type_counts.index,
                    title="Evaluaciones por tipo",
                )
                st.plotly_chart(fig2, use_container_width=True)

            with col_b:
                wpc = df.groupby("Curso")["Peso (%)"].sum().reset_index()
                fig3 = px.bar(
                    wpc, x="Curso", y="Peso (%)", title="Peso total detectado por curso", color="Curso"
                )
                fig3.update_layout(showlegend=False)
                st.plotly_chart(fig3, use_container_width=True)
        else:
            st.info("No hay suficientes datos de semanas para generar el gráfico de carga.")

    # ── Tab 3: Calendario ─────────────
    with rt3:
        st.markdown("### 📅 Calendario de evaluaciones")

        df_cal = df[df["Fecha"].notna()].copy()
        df_cal["Fecha_dt"] = pd.to_datetime(df_cal["Fecha"])
        df_cal = df_cal.sort_values("Fecha_dt")

        if not df_cal.empty:
            for _, row in df_cal.iterrows():
                w = row.get("Peso (%)")
                weight_badge = f"**{int(w)}%**" if pd.notna(w) and w else ""
                if pd.notna(w) and w:
                    icon = "🔴" if w >= 25 else "🟡" if w >= 15 else "🟢"
                else:
                    icon = "⚪"
                approx_tag = " *(fecha aprox.)*" if row.get("Aprox.") else ""
                st.markdown(
                    f"**{row['Fecha']}** — {icon} {row['Evaluación']} {weight_badge}{approx_tag}  \n"
                    f"📚 *{row['Curso']}* · `{row['Tipo']}`"
                )
                st.markdown("---")
        else:
            st.info("No se detectaron evaluaciones con fechas exactas.")

        no_date = df[df["Fecha"].isna()]
        if not no_date.empty:
            with st.expander(f"⚠️ {len(no_date)} evaluación(es) sin fecha — revisar manualmente en el sílabo"):
                st.dataframe(
                    no_date[["Curso", "Evaluación", "Tipo", "Semana", "Peso (%)", "Cita del sílabo"]],
                    use_container_width=True,
                )

    # ── Tab 4: Exportar ───────────────
    with rt4:
        st.markdown("### 📤 Exportar tus datos")

        col_x, col_y = st.columns(2)

        with col_x:
            st.markdown("#### 📆 Google Calendar (.ics)")
            df_ics = df[df["Fecha"].notna()].copy()
            if not df_ics.empty:
                ics_bytes = generate_ics(df_ics)
                st.download_button(
                    "⬇️ Descargar .ics",
                    data=ics_bytes,
                    file_name="silabo2calendar.ics",
                    mime="text/calendar",
                    use_container_width=True,
                )
                st.caption(
                    "Importa este archivo en Google Calendar: "
                    "Configuración → Importar y exportar → Importar."
                )
            else:
                st.warning("No hay evaluaciones con fecha exacta para exportar al calendario.")

        with col_y:
            st.markdown("#### 📊 Tabla completa (.csv)")
            csv_full = df.to_csv(index=False, encoding="utf-8-sig")
            st.download_button(
                "⬇️ Descargar CSV completo",
                data=csv_full,
                file_name="silabo2calendar_completo.csv",
                mime="text/csv",
                use_container_width=True,
            )

        st.divider()
        st.markdown("#### 📋 Resumen en Markdown")
        summary_md = f"# Resumen — Sílabo2Calendar\n\n"
        summary_md += f"**Generado:** {datetime.now().strftime('%d/%m/%Y %H:%M')}  \n"
        summary_md += f"**Universidad:** {university}  \n"
        summary_md += f"**Ciclo:** {cycle_start} → {cycle_end}\n\n"
        summary_md += f"## Cursos procesados: {total_courses}\n\n"
        for course in data:
            summary_md += f"### {course.get('course_name', 'Curso')}\n"
            summary_md += f"- Docente: {course.get('professor') or 'No detectado'}\n"
            summary_md += f"- Evaluaciones detectadas: {len(course.get('events', []))}\n"
            for gp in course.get("grading_policy", []):
                summary_md += f"  - {gp['component']}: {gp.get('weight_percent', '?')}%\n"
            summary_md += "\n"

        st.download_button(
            "⬇️ Descargar resumen (.md)",
            data=summary_md,
            file_name="silabo2calendar_resumen.md",
            mime="text/markdown",
            use_container_width=True,
        )
