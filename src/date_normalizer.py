"""
date_normalizer.py
Normaliza fechas de texto libre a formato ISO YYYY-MM-DD.
Maneja formatos típicos de sílabos peruanos/latinoamericanos.
"""
import re
from datetime import datetime, timedelta
from dateutil import parser as dateutil_parser

MONTHS_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12,
}


def normalize_date(date_text: str, year: int = 2026) -> str | None:
    """
    Intenta convertir un texto de fecha a ISO YYYY-MM-DD.
    Devuelve None si no puede convertir.
    """
    if not date_text:
        return None

    text = str(date_text).strip().lower()

    # 1. Ya está en ISO
    if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return text

    # 2. DD/MM/YYYY  o  DD-MM-YYYY  o  DD/MM  o  DD-MM
    m = re.match(r"^(\d{1,2})[/\-](\d{1,2})(?:[/\-](\d{2,4}))?$", text)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        yr = int(m.group(3)) if m.group(3) else year
        if yr < 100:
            yr += 2000
        try:
            return datetime(yr, month, day).strftime("%Y-%m-%d")
        except ValueError:
            pass

    # 3. "23 de junio" / "martes 23 de junio" / "23 de junio de 2026"
    m = re.search(r"(\d{1,2})\s+de\s+(\w+)(?:\s+de\s+(\d{4}))?", text)
    if m:
        day = int(m.group(1))
        month_name = m.group(2).lower()
        yr = int(m.group(3)) if m.group(3) else year
        month = MONTHS_ES.get(month_name)
        if month:
            try:
                return datetime(yr, month, day).strftime("%Y-%m-%d")
            except ValueError:
                pass

    # 4. Último recurso: dateutil
    try:
        parsed = dateutil_parser.parse(text, dayfirst=True, yearfirst=False)
        if parsed.year < 2020:
            parsed = parsed.replace(year=year)
        return parsed.strftime("%Y-%m-%d")
    except Exception:
        pass

    return None


def approximate_date_from_week(start_date: datetime, week_number: int) -> str:
    """Calcula fecha aproximada a partir del número de semana y la fecha de inicio del ciclo."""
    result = start_date + timedelta(days=(week_number - 1) * 7)
    return result.strftime("%Y-%m-%d")


def normalize_events(events: list, cycle_start_str: str = "2026-03-17") -> list:
    """
    Procesa una lista de eventos y normaliza sus fechas.
    - Si date_iso es null pero hay date_text, intenta convertirlo.
    - Si sigue sin fecha pero hay semana, calcula fecha aproximada.
    - Añade campo 'date_approximate': True cuando la fecha es estimada.
    """
    try:
        cycle_start = datetime.strptime(cycle_start_str, "%Y-%m-%d")
    except Exception:
        cycle_start = datetime(2026, 3, 17)

    normalized = []
    for event in events:
        ev = dict(event)

        # Intentar normalizar date_text si no hay date_iso
        if not ev.get("date_iso") and ev.get("date_text"):
            norm = normalize_date(ev["date_text"], year=cycle_start.year)
            if norm:
                ev["date_iso"] = norm
                ev["date_approximate"] = False

        # Calcular desde semana si todavía no hay fecha
        if not ev.get("date_iso") and ev.get("week"):
            try:
                week_num = int(ev["week"])
                if 1 <= week_num <= 22:
                    ev["date_iso"] = approximate_date_from_week(cycle_start, week_num)
                    ev["date_approximate"] = True
            except (ValueError, TypeError):
                pass

        normalized.append(ev)

    return normalized
