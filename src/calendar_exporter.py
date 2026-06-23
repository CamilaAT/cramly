"""
calendar_exporter.py
Genera un archivo .ics estándar a partir del DataFrame de evaluaciones.
Compatible con Google Calendar, Apple Calendar y Outlook.
"""
import uuid
from datetime import datetime, timedelta

import pandas as pd
from icalendar import Alarm, Calendar, Event


def _parse_hm(value):
    """Convierte 'HH:MM' a (hora, minuto). Devuelve None si no se puede."""
    try:
        parts = str(value).strip().split(":")
        return int(parts[0]), int(parts[1])
    except Exception:
        return None


def generate_ics(df: pd.DataFrame, class_events: list = None) -> bytes:
    """
    Genera y devuelve un archivo .ics como bytes.
    - `df`: evaluaciones (eventos de día completo).
    - `class_events`: clases regulares (eventos CON hora). Lista de dicts con
      claves: Curso, Fecha (YYYY-MM-DD), start_time ('HH:MM'), end_time ('HH:MM').
    """
    cal = Calendar()
    cal.add("prodid", "-//Cramly//UP//ES")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", "Cramly — Evaluaciones y clases")
    cal.add("x-wr-timezone", "America/Lima")

    for _, row in df.iterrows():
        raw_date = row.get("Fecha")
        if pd.isna(raw_date) or not raw_date:
            continue

        try:
            event_date = datetime.strptime(str(raw_date), "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue

        course = row.get("Curso", "")
        title = row.get("Evaluación", "Evaluación")
        weight = row.get("Peso (%)", None)
        event_type = row.get("Tipo", "")
        description = row.get("Descripción", "") or ""

        # Título del evento en el calendario
        weight_str = f" [{int(weight)}%]" if pd.notna(weight) and weight else ""
        summary = f"[{course}] {title}{weight_str}"

        # Descripción completa
        desc_lines = [
            f"Curso: {course}",
            f"Tipo: {event_type}",
            f"Peso: {int(weight)}%" if pd.notna(weight) and weight else "Peso: No especificado",
        ]
        if description:
            desc_lines.append(f"Descripción: {description}")
        desc_lines.append("Generado por Cramly")

        ev = Event()
        ev.add("summary", summary)
        ev.add("description", "\n".join(desc_lines))
        ev.add("dtstart", event_date)
        ev.add("dtend", event_date + timedelta(days=1))
        ev.add("dtstamp", datetime.now())
        ev.add("uid", str(uuid.uuid4()))

        # Recordatorio según peso
        alarm = Alarm()
        alarm.add("action", "DISPLAY")
        alarm.add("description", f"Recordatorio: {title}")
        if pd.notna(weight) and weight:
            days_before = 7 if weight >= 25 else 3 if weight >= 15 else 1
        else:
            days_before = 1
        alarm.add("trigger", timedelta(days=-days_before))
        ev.add_component(alarm)

        cal.add_component(ev)

    # ── Clases regulares (eventos con hora) ──
    for ce in (class_events or []):
        raw_date = ce.get("Fecha")
        if not raw_date:
            continue
        try:
            d = datetime.strptime(str(raw_date), "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue

        course = ce.get("Curso", "")
        st = _parse_hm(ce.get("start_time"))
        et = _parse_hm(ce.get("end_time"))

        ev = Event()
        ev.add("summary", f"[{course}] Clase")
        ev.add("description", "Clase regular\nGenerado por Cramly")
        if st:
            start_dt = datetime(d.year, d.month, d.day, st[0], st[1])
            end_dt = datetime(d.year, d.month, d.day, et[0], et[1]) if et else start_dt + timedelta(hours=2)
            ev.add("dtstart", start_dt)
            ev.add("dtend", end_dt)
        else:
            # Sin hora → evento de día completo
            ev.add("dtstart", d)
            ev.add("dtend", d + timedelta(days=1))
        ev.add("dtstamp", datetime.now())
        ev.add("uid", str(uuid.uuid4()))
        cal.add_component(ev)

    return cal.to_ical()
