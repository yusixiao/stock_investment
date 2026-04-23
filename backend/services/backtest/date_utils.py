import re
from datetime import date as _date

FREQ_ORDER = {
    "daily": 0,
    "weekly": 1,
    "monthly": 2,
    "quarterly": 3,
    "semi-annual": 4,
    "yearly": 5,
}

_PATTERNS = [
    (re.compile(r"^\d{4}-\d{2}-\d{2}$"), "daily"),
    (re.compile(r"^\d{4}-W\d{2}$"), "weekly"),
    (re.compile(r"^\d{4}-\d{2}$"), "monthly"),
    (re.compile(r"^\d{4}-Q[1-4]$"), "quarterly"),
    (re.compile(r"^\d{4}-H[12]$"), "semi-annual"),
    (re.compile(r"^\d{4}$"), "yearly"),
]


def detect_frequency(date_str: str) -> str:
    for pattern, freq in _PATTERNS:
        if pattern.match(date_str):
            return freq
    raise ValueError(f"Cannot detect frequency from date string: {date_str}")


def format_match_date(date_str: str, frequency: str) -> str:
    dt = _date.fromisoformat(date_str)
    if frequency == "daily":
        return date_str
    if frequency == "weekly":
        yr, wk, _ = dt.isocalendar()
        return f"{yr}-W{wk:02d}"
    if frequency == "monthly":
        return f"{dt.year}-{dt.month:02d}"
    if frequency == "quarterly":
        q = (dt.month - 1) // 3 + 1
        return f"{dt.year}-Q{q}"
    if frequency == "semi-annual":
        h = 1 if dt.month <= 6 else 2
        return f"{dt.year}-H{h}"
    if frequency == "yearly":
        return str(dt.year)
    raise ValueError(f"Unknown frequency: {frequency}")


def _to_representative_date(date_str: str, freq: str) -> _date:
    if freq == "daily":
        return _date.fromisoformat(date_str)
    if freq == "weekly":
        year, week = date_str.split("-W")
        return _date.fromisocalendar(int(year), int(week), 4)
    if freq == "monthly":
        return _date.fromisoformat(date_str + "-15")
    if freq == "quarterly":
        year, qpart = date_str.split("-Q")
        month = (int(qpart) - 1) * 3 + 2
        return _date(int(year), month, 15)
    if freq == "semi-annual":
        year, hpart = date_str.split("-H")
        month = 3 if hpart == "1" else 9
        return _date(int(year), month, 15)
    if freq == "yearly":
        return _date(int(date_str), 7, 1)
    raise ValueError(f"Unknown frequency: {freq}")


def date_belongs_to(fine_date: str, coarse_date: str) -> bool:
    fine_freq = detect_frequency(fine_date)
    coarse_freq = detect_frequency(coarse_date)
    fine_order = FREQ_ORDER[fine_freq]
    coarse_order = FREQ_ORDER[coarse_freq]
    if fine_order > coarse_order:
        return False
    if fine_order == coarse_order:
        return fine_date == coarse_date
    if fine_freq == "daily":
        fine_converted = format_match_date(fine_date, coarse_freq)
    else:
        rep = _to_representative_date(fine_date, fine_freq)
        fine_converted = format_match_date(rep.isoformat(), coarse_freq)
    return fine_converted == coarse_date
