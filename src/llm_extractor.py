"""
llm_extractor.py
Llama a la API de Claude para extraer información estructurada de un sílabo universitario.
Devuelve un dict con cursos, evaluaciones, fechas y pesos.
"""
import os
import json
import anthropic
from .pdf_extractor import truncate_text

SYSTEM_PROMPT = (
    "Eres un extractor experto de sílabos universitarios latinoamericanos. "
    "Tu tarea es leer el texto de un sílabo y devolver SOLO un JSON válido, "
    "sin markdown, sin backticks, sin texto adicional antes o después. "
    "Si no puedes extraer algo con certeza, usa null. Nunca inventes información."
)

EXTRACTION_PROMPT = """Extrae la información del siguiente sílabo universitario.

Contexto:
- Fecha de inicio del ciclo académico: {cycle_start}
- Nombre del curso sugerido (usa solo si no aparece en el texto): {course_name}

REGLAS CRÍTICAS:
1. NO inventes fechas. Si una fecha no aparece explícitamente, pon null en date_iso.
2. Si dice "semana 8" sin fecha exacta → week=8, date_iso=null.
3. Pesos como "30%" → weight_percent=30 (solo el número).
4. Incluye source_quote: copia breve exacta del texto donde encontraste el dato.
5. confidence: 0.0 a 1.0 según tu certeza.
6. Extrae TODAS las evaluaciones: parciales, finales, controles, prácticas calificadas,
   trabajos, exposiciones, proyectos, quizzes, lecturas evaluadas.
7. En grading_policy pon el sistema de notas completo con pesos si aparece.
8. Devuelve SOLO el JSON, sin texto adicional.

JSON requerido (respeta exactamente estos nombres de campo):
{{
  "course_name": "string o null",
  "professor": "string o null",
  "institution": "string o null",
  "grading_policy": [
    {{
      "component": "string",
      "weight_percent": 30,
      "description": "string o null"
    }}
  ],
  "events": [
    {{
      "title": "string",
      "event_type": "exam | assignment | presentation | quiz | project | reading | other",
      "date_text": "texto de fecha tal como aparece en el sílabo, o null",
      "date_iso": "YYYY-MM-DD o null",
      "week": 8,
      "weight_percent": 30,
      "description": "string o null",
      "source_quote": "cita breve del texto original",
      "confidence": 0.95
    }}
  ],
  "weekly_topics": [
    {{
      "week": 1,
      "topic": "string o null",
      "deliverables": []
    }}
  ],
  "warnings": ["advertencias sobre fechas ambiguas o info faltante"]
}}

Texto del sílabo:
{syllabus_text}"""


def extract_syllabus_data(
    text: str,
    course_name: str = None,
    cycle_start: str = "2026-03-17"
) -> dict:
    """
    Envía el texto del sílabo a Claude y devuelve un dict estructurado.
    En caso de error devuelve un dict con 'error' y listas vacías.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return _error_response(course_name, "No se encontró ANTHROPIC_API_KEY en las variables de entorno.")

    client = anthropic.Anthropic(api_key=api_key)

    truncated = truncate_text(text, max_chars=7000)

    prompt = EXTRACTION_PROMPT.format(
        cycle_start=cycle_start,
        course_name=course_name or "No especificado",
        syllabus_text=truncated,
    )

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = message.content[0].text.strip()
        raw = _clean_json_fences(raw)
        result = json.loads(raw)

        # Asegurar que course_name esté presente
        if not result.get("course_name") and course_name:
            result["course_name"] = course_name

        # Garantizar listas vacías si faltan campos
        result.setdefault("events", [])
        result.setdefault("grading_policy", [])
        result.setdefault("warnings", [])
        result.setdefault("weekly_topics", [])

        return result

    except json.JSONDecodeError as e:
        raw_preview = raw[:400] if "raw" in dir() else ""
        return _error_response(
            course_name,
            f"La IA no devolvió JSON válido: {e}. Fragmento recibido: {raw_preview}"
        )
    except anthropic.APIStatusError as e:
        return _error_response(course_name, f"Error de API Anthropic ({e.status_code}): {e.message}")
    except Exception as e:
        return _error_response(course_name, f"Error inesperado: {str(e)}")


def _clean_json_fences(text: str) -> str:
    """Elimina bloques ```json ... ``` si el modelo los incluyó por error."""
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def _error_response(course_name: str, message: str) -> dict:
    return {
        "course_name": course_name,
        "professor": None,
        "institution": None,
        "error": message,
        "events": [],
        "grading_policy": [],
        "weekly_topics": [],
        "warnings": [f"Error durante extracción: {message}"],
    }
