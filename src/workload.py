"""
workload.py
Calcula el score de carga académica por semana y clasifica las semanas críticas.
Score = número_de_eventos * 10 + peso_total_de_evaluaciones_esa_semana
"""
import pandas as pd


def calculate_workload_scores(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcula score de carga por semana.
    Devuelve DataFrame con columnas: Semana, Eventos, Peso_total, Score, Nivel.
    """
    if df.empty or "Semana" not in df.columns:
        return pd.DataFrame()

    df_w = df[df["Semana"].notna()].copy()
    if df_w.empty:
        return pd.DataFrame()

    df_w["Semana"] = pd.to_numeric(df_w["Semana"], errors="coerce")
    df_w = df_w[df_w["Semana"].notna()]
    if df_w.empty:
        return pd.DataFrame()

    workload = (
        df_w.groupby("Semana")
        .agg(
            Eventos=("Evaluación", "count"),
            Peso_total=("Peso (%)", lambda x: x.dropna().sum()),
        )
        .reset_index()
    )

    workload["Score"] = workload["Eventos"] * 10 + workload["Peso_total"]
    workload["Nivel"] = workload["Score"].apply(classify_workload)

    return workload.sort_values("Semana").reset_index(drop=True)


def classify_workload(score: float) -> str:
    """Clasifica el score de carga en tres niveles."""
    if score > 50:
        return "Alta carga 🔴"
    elif score > 20:
        return "Media carga 🟡"
    else:
        return "Baja carga 🟢"


def get_critical_weeks_summary(df: pd.DataFrame, workload_df: pd.DataFrame) -> list[dict]:
    """
    Devuelve lista de semanas críticas con detalle de evaluaciones.
    """
    if workload_df.empty:
        return []

    critical = workload_df[workload_df["Nivel"] == "Alta carga 🔴"]
    summaries = []

    for _, row in critical.iterrows():
        week_num = row["Semana"]
        week_events = df[df["Semana"] == week_num]
        summaries.append({
            "semana": int(week_num),
            "score": int(row["Score"]),
            "evaluaciones": week_events["Evaluación"].tolist(),
            "cursos": week_events["Curso"].tolist(),
            "peso_total": int(row["Peso_total"]),
        })

    return summaries
