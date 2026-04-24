### Task 1: `date_utils.py` — 日期工具函数

**Files:**
- Create: `backend/services/backtest/date_utils.py`
- Create: `backend/tests/test_date_utils.py`

---

- [ ] **Step 1: Write failing tests for `detect_frequency`**

Create `backend/tests/test_date_utils.py`:

```python
import pytest
from services.backtest.date_utils import detect_frequency


class TestDetectFrequency:
    def test_daily(self):
        assert detect_frequency("2024-12-15") == "daily"

    def test_weekly(self):
        assert detect_frequency("2024-W51") == "weekly"

    def test_monthly(self):
        assert detect_frequency("2024-12") == "monthly"

    def test_quarterly(self):
        assert detect_frequency("2024-Q4") == "quarterly"

    def test_semi_annual(self):
        assert detect_frequency("2024-H2") == "semi-annual"

    def test_yearly(self):
        assert detect_frequency("2024") == "yearly"

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            detect_frequency("not-a-date")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_date_utils.py::TestDetectFrequency -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `detect_frequency` and `FREQ_ORDER`**

Create `backend/services/backtest/date_utils.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_date_utils.py::TestDetectFrequency -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Write failing tests for `format_match_date`**

Append to `backend/tests/test_date_utils.py`:

```python
from services.backtest.date_utils import format_match_date


class TestFormatMatchDate:
    def test_daily(self):
        assert format_match_date("2024-12-15", "daily") == "2024-12-15"

    def test_weekly(self):
        assert format_match_date("2024-12-15", "weekly") == "2024-W50"

    def test_weekly_iso(self):
        assert format_match_date("2024-12-30", "weekly") == "2025-W01"

    def test_monthly(self):
        assert format_match_date("2024-12-15", "monthly") == "2024-12"

    def test_monthly_jan(self):
        assert format_match_date("2024-01-05", "monthly") == "2024-01"

    def test_quarterly_q1(self):
        assert format_match_date("2024-02-15", "quarterly") == "2024-Q1"

    def test_quarterly_q4(self):
        assert format_match_date("2024-12-15", "quarterly") == "2024-Q4"

    def test_semi_annual_h1(self):
        assert format_match_date("2024-03-15", "semi-annual") == "2024-H1"

    def test_semi_annual_h2(self):
        assert format_match_date("2024-07-15", "semi-annual") == "2024-H2"

    def test_yearly(self):
        assert format_match_date("2024-12-15", "yearly") == "2024"

    def test_already_monthly_input(self):
        assert format_match_date("2024-09-30", "monthly") == "2024-09"
```

- [ ] **Step 6: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_date_utils.py::TestFormatMatchDate -v`
Expected: FAIL with `ImportError`

- [ ] **Step 7: Implement `format_match_date`**

Append to `backend/services/backtest/date_utils.py`:

```python
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
```

- [ ] **Step 8: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_date_utils.py::TestFormatMatchDate -v`
Expected: PASS (11 tests)

- [ ] **Step 9: Write failing tests for `date_belongs_to`**

Append to `backend/tests/test_date_utils.py`:

```python
from services.backtest.date_utils import date_belongs_to


class TestDateBelongsTo:
    def test_daily_belongs_to_monthly(self):
        assert date_belongs_to("2024-12-15", "2024-12") is True

    def test_daily_not_belongs_to_monthly(self):
        assert date_belongs_to("2024-12-15", "2024-11") is False

    def test_daily_belongs_to_weekly(self):
        assert date_belongs_to("2024-12-15", "2024-W50") is True

    def test_daily_not_belongs_to_weekly(self):
        assert date_belongs_to("2024-12-15", "2024-W49") is False

    def test_daily_belongs_to_quarterly(self):
        assert date_belongs_to("2024-12-15", "2024-Q4") is True

    def test_daily_not_belongs_to_quarterly(self):
        assert date_belongs_to("2024-12-15", "2024-Q3") is False

    def test_daily_belongs_to_semi_annual(self):
        assert date_belongs_to("2024-12-15", "2024-H2") is True

    def test_daily_not_belongs_to_semi_annual(self):
        assert date_belongs_to("2024-12-15", "2024-H1") is False

    def test_daily_belongs_to_yearly(self):
        assert date_belongs_to("2024-12-15", "2024") is True

    def test_daily_not_belongs_to_yearly(self):
        assert date_belongs_to("2024-12-15", "2023") is False

    def test_monthly_belongs_to_quarterly(self):
        assert date_belongs_to("2024-12", "2024-Q4") is True

    def test_monthly_not_belongs_to_quarterly(self):
        assert date_belongs_to("2024-12", "2024-Q3") is False

    def test_monthly_belongs_to_yearly(self):
        assert date_belongs_to("2024-12", "2024") is True

    def test_weekly_belongs_to_monthly(self):
        assert date_belongs_to("2024-W50", "2024-12") is True

    def test_weekly_not_belongs_to_monthly(self):
        assert date_belongs_to("2024-W50", "2024-11") is False

    def test_same_frequency_equal(self):
        assert date_belongs_to("2024-12-15", "2024-12-15") is True

    def test_same_frequency_not_equal(self):
        assert date_belongs_to("2024-12-15", "2024-12-16") is False

    def test_same_monthly_equal(self):
        assert date_belongs_to("2024-12", "2024-12") is True

    def test_same_monthly_not_equal(self):
        assert date_belongs_to("2024-12", "2024-11") is False

    def test_coarse_cannot_belong_to_fine(self):
        assert date_belongs_to("2024-12", "2024-12-15") is False
```

- [ ] **Step 10: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_date_utils.py::TestDateBelongsTo -v`
Expected: FAIL with `ImportError`

- [ ] **Step 11: Implement `date_belongs_to`**

Append to `backend/services/backtest/date_utils.py`:

```python
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
    fine_converted = format_match_date(
        _to_representative_date(fine_date, fine_freq).isoformat(),
        coarse_freq,
    )
    if fine_freq == "daily":
        fine_converted = format_match_date(fine_date, coarse_freq)
    elif fine_freq == "weekly":
        rep = _to_representative_date(fine_date, fine_freq)
        fine_converted = format_match_date(rep.isoformat(), coarse_freq)
    elif fine_freq == "monthly":
        rep = _to_representative_date(fine_date, fine_freq)
        fine_converted = format_match_date(rep.isoformat(), coarse_freq)
    else:
        rep = _to_representative_date(fine_date, fine_freq)
        fine_converted = format_match_date(rep.isoformat(), coarse_freq)
    return fine_converted == coarse_date
```

- [ ] **Step 12: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_date_utils.py::TestDateBelongsTo -v`
Expected: PASS (20 tests)

- [ ] **Step 13: Run all date_utils tests together**

Run: `python -m pytest backend/tests/test_date_utils.py -v`
Expected: PASS (38 tests total)

- [ ] **Step 14: Commit**

```bash
git add backend/services/backtest/date_utils.py backend/tests/test_date_utils.py
git commit -m "feat: add date_utils with format_match_date, date_belongs_to, detect_frequency"
```
