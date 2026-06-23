"""
llm_extractor.py
Llama a la API de Claude para extraer información estructurada de un sílabo universitario.

Estrategia (Cramly):
1. Manda el PDF DIRECTO a Claude (document block) en lugar de texto pre-extraído.
   Claude lee el PDF de forma nativa y preserva el layout de las tablas (cronogramas,
   sistemas de notas), que es justo donde viven las fechas y los pesos. Esto evita que
   pdfplumber aplane las tablas y rompa la relación fecha↔evaluación.
2. Usa structured outputs (output_config.format con JSON schema): la API garantiza que
   la respuesta cumpla el esquema, eliminando los errores de "JSON inválido".

Mantiene un fallback a texto plano (pdfplumber) por si el PDF falla o es muy grande.
"""
import os
import json
import base64
import anthropic

from .pdf_extractor import truncate_text

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = (
    "Eres un extractor experto de sílabos universitarios latinoamericanos. "
    "Lees el sílabo (en PDF o texto) y extraes evaluaciones, fechas, pesos y el sistema "
    "de notas. Nunca inventes información: si un dato no aparece, usa null. "
    "Presta especial atención a las TABLAS de cronograma y de calificación."
)

# Esquema que la API obliga a cumplir (structured outputs).
SYLLABUS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "course_name": {"type": ["string", "null"]},
        "professor": {"type": ["string", "null"]},
        "institution": {"type": ["string", "null"]},
        "grading_policy": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "component": {"type": "string"},
                    "weight_percent": {"type": ["number", "null"]},
                    "description": {"type": ["string", "null"]},
                },
                "required": ["component", "weight_percent", "description"],
            },
        },
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string"},
                    "event_type": {
                        "type": "string",
                        "enum": ["exam", "assignment", "presentation",
                                 "quiz", "project", "reading", "other"],
                    },
                    "date_text": {"type": ["string", "null"]},
                    "date_iso": {"type": ["string", "null"]},
                    "week": {"type": ["integer", "null"]},
                    "weight_percent": {"type": ["number", "null"]},
                    "description": {"type": ["string", "null"]},
                    "source_quote": {"type": ["string", "null"]},
                    "confidence": {"type": ["number", "null"]},
                },
                "required": ["title", "event_type", "date_text", "date_iso", "week",
                             "weight_percent", "description", "source_quote", "confidence"],
            },
        },
        "class_schedule": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "properties": {
                "days": {"type": "array", "items": {"type": "string"}},
                "start_time": {"type": ["string", "null"]},
                "end_time": {"type": ["string", "null"]},
            },
            "required": ["days", "start_time", "end_time"],
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["course_name", "professor", "institution",
                 "grading_policy", "events", "class_schedule", "warnings"],
}

EXTRACTION_PROMPT = """Extrae la información de evaluaciones del sílabo universitario adjunto.

Contexto:
- Fecha de inicio del ciclo académico: {cycle_start}
- Nombre del curso sugerido (usa solo si no aparece en el sílabo): {course_name}

REGLAS CRÍTICAS:
1. Las TABLAS son la fuente más confiable de fechas. Lee el cronograma/schedule celda por
   celda manteniendo la alineación entre la fila de la evaluación y su fecha.
2. El SISTEMA DE NOTAS (pesos) y el CRONOGRAMA (fechas) casi siempre están en SECCIONES
   DISTINTAS del sílabo. Debes CRUZARLOS: a cada evaluación del cronograma asígnale el peso
   que le corresponde en el sistema de notas (ej: "Final exam 25%" en la sección de notas →
   el "Final Exam" del cronograma lleva weight_percent=25).
3. Si un componente agrupa varias instancias (ej: "Practical tests (02) = 20%", o
   "Cases (03) = 20%"), reparte el peso en partes iguales entre las instancias datables
   (cada practical test = 10%) y baja un poco la confidence.
4. Si las notas se dan como FÓRMULA (ej: NF = 0.3·PV + 0.35·VF1 + 0.35·VF2), interpreta cada
   coeficiente como el peso (0.3 → 30%) y mapea cada término a su evaluación.
5. NO inventes fechas. Si una evaluación no tiene fecha explícita, pon date_iso=null. Si solo
   dice "semana 8", pon week=8 y date_iso=null.
6. Fechas como "Mo. 16/03", "Th.19/03", "Lunes 6 de abril", "06/05" → conviértelas a
   date_iso (YYYY-MM-DD) usando el año del ciclo. Para RANGOS ("Del 13 al 29 de mayo",
   "From Wed. 06/05 to Fr. 08/05") usa la fecha de INICIO en date_iso y menciona el rango
   completo en description.
7. Extrae TODAS las evaluaciones calificadas: parciales, finales, controles, prácticas
   calificadas, tests, casos, trabajos, exposiciones, sustentaciones, entregas con plazo.
   Las sesiones de clase o talleres NO calificados no son evaluaciones (omítelos).
8. source_quote: copia breve y literal del texto donde encontraste el dato (fecha o peso).
9. confidence: 0.0 a 1.0 según tu certeza.
10. En warnings anota fechas ambiguas, pesos que no suman 100%, o info que requiera revisión.
11. HORARIO DE CLASES: si el sílabo indica un horario regular de clases (ej: "Horario: Martes
    y Jueves, 17:30 - 19:30 hs"), llena class_schedule con los días EN ESPAÑOL en minúscula
    (ej: ["martes","jueves"]) y las horas en formato HH:MM (start_time, end_time). Si no hay
    un horario regular claro, deja class_schedule en null.
"""


def extract_syllabus_data(
    pdf_bytes: bytes = None,
    text: str = None,
    course_name: str = None,
    cycle_start: str = "2026-03-17",
) -> dict:
    """
    Envía el sílabo a Claude y devuelve un dict estructurado.

    Preferentemente recibe `pdf_bytes` (el PDF crudo) y lo manda como document block.
    Si solo hay `text`, usa la ruta de texto plano como fallback.
    En caso de error devuelve un dict con 'error' y listas vacías.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return _error_response(course_name, "No se encontró ANTHROPIC_API_KEY en las variables de entorno.")

    if not pdf_bytes and not text:
        return _error_response(course_name, "No se recibió ni PDF ni texto del sílabo.")

    client = anthropic.Anthropic(api_key=api_key)

    prompt = EXTRACTION_PROMPT.format(
        cycle_start=cycle_start,
        course_name=course_name or "No especificado",
    )

    # Construir el contenido del mensaje: PDF nativo (preferido) o texto (fallback).
    if pdf_bytes:
        b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
        user_content = [
            {
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
            },
            {"type": "text", "text": prompt},
        ]
    else:
        truncated = truncate_text(text, max_chars=12000)
        user_content = prompt + "\n\nTexto del sílabo:\n" + truncated

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=8000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            output_config={"format": {"type": "json_schema", "schema": SYLLABUS_SCHEMA}},
        )

        # Con structured outputs el primer bloque de texto es JSON válido garantizado.
        raw = next(b.text for b in message.content if b.type == "text")
        result = json.loads(raw)

        if not result.get("course_name") and course_name:
            result["course_name"] = course_name

        result.setdefault("events", [])
        result.setdefault("grading_policy", [])
        result.setdefault("warnings", [])

        return result

    except anthropic.APIStatusError as e:
        return _error_response(course_name, f"Error de API Anthropic ({e.status_code}): {e.message}")
    except json.JSONDecodeError as e:
        return _error_response(course_name, f"La IA no devolvió JSON válido: {e}")
    except Exception as e:
        return _error_response(course_name, f"Error inesperado: {str(e)}")


def _error_response(course_name: str, message: str) -> dict:
    return {
        "course_name": course_name,
        "professor": None,
        "institution": None,
        "error": message,
        "events": [],
        "grading_policy": [],
        "warnings": [f"Error durante extracción: {message}"],
    }
