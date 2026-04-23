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
