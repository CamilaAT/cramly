"""
Tests para date_normalizer.py
Correr con: pytest tests/
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.date_normalizer import normalize_date, approximate_date_from_week
from datetime import datetime


def test_iso_format():
    assert normalize_date("2026-06-23") == "2026-06-23"


def test_slash_format_full():
    assert normalize_date("23/06/2026") == "2026-06-23"


def test_slash_format_short():
    result = normalize_date("23/06", year=2026)
    assert result == "2026-06-23"


def test_spanish_full():
    assert normalize_date("23 de junio de 2026") == "2026-06-23"


def test_spanish_no_year():
    assert normalize_date("23 de junio", year=2026) == "2026-06-23"


def test_spanish_with_weekday():
    result = normalize_date("martes 23 de junio", year=2026)
    assert result == "2026-06-23"


def test_empty_returns_none():
    assert normalize_date("") is None
    assert normalize_date(None) is None


def test_tbd_returns_none():
    # "TBD", "por definir", etc. no deben convertirse
    result = normalize_date("por definir", year=2026)
    assert result is None


def test_week_approximation():
    start = datetime(2026, 3, 17)
    result = approximate_date_from_week(start, 1)
    assert result == "2026-03-17"

    result2 = approximate_date_from_week(start, 2)
    assert result2 == "2026-03-24"


def test_week_11():
    start = datetime(2026, 3, 17)
    result = approximate_date_from_week(start, 11)
    assert result == "2026-05-26"
