"""
Prueba rápida de extracción contra los sílabos reales en data/sample_syllabi/.
Corre:  python scripts/test_extraction.py
Requiere ANTHROPIC_API_KEY (en .env o variable de entorno).
"""
import os
import sys
import glob

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.llm_extractor import extract_syllabus_data
from src.date_normalizer import normalize_events

CYCLE_START = "2026-03-17"
SAMPLE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "data", "sample_syllabi")


def main():
    pdfs = sorted(glob.glob(os.path.join(SAMPLE_DIR, "*.pdf")))
    if not pdfs:
        print(f"No se encontraron PDFs en {SAMPLE_DIR}")
        return

    for path in pdfs:
        name = os.path.basename(path)
        course_guess = name.replace(".pdf", "")
        print("\n" + "=" * 78)
        print(f"ARCHIVO: {name}")
        print("=" * 78)

        with open(path, "rb") as f:
            pdf_bytes = f.read()

        data = extract_syllabus_data(
            pdf_bytes=pdf_bytes,
            course_name=course_guess,
            cycle_start=CYCLE_START,
        )

        if data.get("error"):
            print("ERROR:", data["error"])
            continue

        print(f"Curso:    {data.get('course_name')}")
        print(f"Docente:  {data.get('professor')}")
        print(f"Institucion: {data.get('institution')}")

        print("\nSISTEMA DE NOTAS:")
        for gp in data.get("grading_policy", []):
            w = gp.get("weight_percent")
            print(f"  - {gp.get('component')}: {w if w is not None else '?'}%")

        events = normalize_events(data.get("events", []), CYCLE_START)
        print(f"\nEVALUACIONES ({len(events)}):")
        print(f"  {'Fecha':<12} {'Aprox':<6} {'Peso':<6} {'Tipo':<13} Titulo")
        print(f"  {'-'*11} {'-'*5} {'-'*5} {'-'*12} {'-'*30}")
        # ordenar por fecha (las sin fecha al final)
        events_sorted = sorted(
            events,
            key=lambda e: (e.get("date_iso") is None, e.get("date_iso") or "")
        )
        for e in events_sorted:
            date = e.get("date_iso") or "—"
            aprox = "si" if e.get("date_approximate") else ""
            w = e.get("weight_percent")
            wt = f"{w}%" if w is not None else ""
            print(f"  {date:<12} {aprox:<6} {wt:<6} {e.get('event_type',''):<13} {e.get('title','')}")

        if data.get("warnings"):
            print("\nADVERTENCIAS:")
            for w in data["warnings"]:
                print(f"  ! {w}")


if __name__ == "__main__":
    main()
