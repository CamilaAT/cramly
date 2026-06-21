# Prompt: Extracción de sílabo universitario

Este archivo documenta el prompt utilizado en `src/llm_extractor.py` para extraer información estructurada de sílabos universitarios latinoamericanos.

## Modelo utilizado

`claude-sonnet-4-6` via Anthropic API

## Diseño del prompt

El prompt tiene tres secciones:

### 1. System prompt
Define el rol del modelo: extractor experto de sílabos universitarios latinoamericanos.
Instrucción clave: devolver SOLO JSON válido, sin markdown.

### 2. Contexto
- Fecha de inicio del ciclo (para calcular fechas aproximadas desde semanas)
- Nombre del curso sugerido (por si no aparece en el PDF)

### 3. Reglas críticas
1. No inventar fechas — si no aparece, usar `null`
2. Si dice "semana 8" sin fecha → `week=8`, `date_iso=null`
3. Pesos como "30%" → número `30`
4. Siempre incluir `source_quote` para auditoría
5. Incluir `confidence` (0.0 a 1.0)
6. Extraer TODAS las evaluaciones
7. Devolver SOLO JSON

## Formato JSON esperado

```json
{
  "course_name": "Data Science con Python",
  "professor": "Alexander Quispe",
  "institution": "Universidad del Pacífico",
  "grading_policy": [
    {
      "component": "Proyecto Final",
      "weight_percent": 30,
      "description": "Startup funcional con demo y pitch"
    }
  ],
  "events": [
    {
      "title": "Presentación Final",
      "event_type": "presentation",
      "date_text": "Martes 23 de junio",
      "date_iso": "2026-06-23",
      "week": 16,
      "weight_percent": 30,
      "description": "Pitch de 7 minutos + Q&A",
      "source_quote": "Presentaciones: Martes 23 y miércoles 24 de junio",
      "confidence": 0.98
    }
  ],
  "weekly_topics": [
    {
      "week": 1,
      "topic": "Introducción al curso",
      "deliverables": []
    }
  ],
  "warnings": [
    "Algunas fechas no aparecen en formato día/mes/año explícito."
  ]
}
```

## Casos límite manejados

| Caso | Manejo |
|---|---|
| PDF sin texto | Mensaje de advertencia, texto vacío enviado |
| Fecha ambigua ("TBD") | `date_iso: null`, entrada en `warnings` |
| Solo semana, sin fecha | `week: 8`, `date_iso: null` → calculado en `date_normalizer.py` |
| Peso faltante | `weight_percent: null` |
| JSON malformado en respuesta | Manejo de excepción en `llm_extractor.py`, retorna error |
