"""
calendar_exporter.py
Genera un archivo .ics estándar a partir del DataFrame de evaluaciones.
Compatible con Google Calendar, Apple Calendar y Outlook.
"""
import uuid
from datetime import datetime, timedelta

import pandas as pd
from icalendar import Alarm, Calendar, Event


def generate_ics(df: pd.DataFrame) -> bytes:
    """
    Genera y devuelve un archivo .ics como bytes.
    Solo incluye eventos que tienen fecha_iso válida.
    """
    cal = Calendar()
    cal.add("prodid", "-//Sílabo2Calendar//UP//ES")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", "Sílabo2Calendar — Evaluaciones")
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
        desc_lines.append("Generado por Sílabo2Calendar")

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

    return cal.to_ical()
