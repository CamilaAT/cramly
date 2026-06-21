"""
pdf_extractor.py
Extrae texto de archivos PDF usando pdfplumber.
Prioriza secciones con palabras clave de evaluación para no exceder tokens del LLM.
"""
import io
import pdfplumber

PRIORITY_KEYWORDS = [
    "evaluaci", "cronograma", "calendario", "semana", "parcial",
    "final", "entrega", "trabajo", "porcentaje", "examen", "peso",
    "calificaci", "nota", "control", "práctica", "práctica", "proyecto",
    "exposici", "sustentaci", "quiz", "tarea"
]


def extract_text_from_pdf(file) -> str:
    """
    Extrae texto de un PDF (UploadedFile de Streamlit o file-like object).
    También extrae tablas y las convierte a texto plano.
    """
    text_parts = []

    try:
        if hasattr(file, "read"):
            file_bytes = file.read()
            pdf_file = io.BytesIO(file_bytes)
        else:
            pdf_file = file

        with pdfplumber.open(pdf_file) as pdf:
            for i, page in enumerate(pdf.pages):
                # Texto normal
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(f"--- Página {i + 1} ---\n{page_text}")

                # Tablas (cronogramas, sistemas de evaluación, etc.)
                tables = page.extract_tables()
                for table in tables:
                    if not table:
                        continue
                    rows = []
                    for row in table:
                        if row:
                            clean_row = " | ".join(
                                str(cell).strip() if cell else "" for cell in row
                            )
                            rows.append(clean_row)
                    if rows:
                        text_parts.append(f"[TABLA]\n" + "\n".join(rows) + "\n[/TABLA]")

    except Exception as e:
        return f"Error al extraer texto del PDF: {str(e)}"

    return "\n\n".join(text_parts).strip()


def truncate_text(text: str, max_chars: int = 7000) -> str:
    """
    Trunca el texto a max_chars priorizando líneas con palabras clave de evaluación.
    Así no se pierden las fechas y pesos aunque el sílabo sea largo.
    """
    if len(text) <= max_chars:
        return text

    lines = text.split("\n")
    priority_lines = []
    normal_lines = []

    for line in lines:
        lower = line.lower()
        if any(kw in lower for kw in PRIORITY_KEYWORDS):
            priority_lines.append(line)
        else:
            normal_lines.append(line)

    priority_text = "\n".join(priority_lines)

    if len(priority_text) >= max_chars:
        return priority_text[:max_chars]

    remaining = max_chars - len(priority_text)
    return priority_text + "\n" + "\n".join(normal_lines)[:remaining]
