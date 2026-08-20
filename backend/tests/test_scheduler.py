from unittest.mock import MagicMock

import scheduler


def test_successful_refresh_calls_buy_opportunity_seam(monkeypatch):
    seam = MagicMock()
    monkeypatch.setattr(scheduler, "_evaluate_buy_opportunities_after_refresh", seam)

    record = MagicMock(status="completed", market_states={
        "A": {"update": {"status": "success"}, "view": {"status": "success"}, "cache": {"status": "success"}},
        "HK": {"update": {"status": "failed"}, "view": {"status": "success"}, "cache": {"status": "success"}},
        "US": {"update": {"status": "success"}, "view": {"status": "failed"}, "cache": {"status": "success"}},
    })
    scheduler._on_market_refresh_complete(record)

    seam.assert_called_once_with(record, {"A"})


def test_partial_refresh_does_not_call_buy_opportunity_seam(monkeypatch):
    seam = MagicMock()
    monkeypatch.setattr(scheduler, "_evaluate_buy_opportunities_after_refresh", seam)

    record = MagicMock(status="partial", market_states={})
    scheduler._on_market_refresh_complete(record)

    seam.assert_not_called()


def test_completed_record_with_derived_failure_does_not_evaluate_failed_market(monkeypatch):
    seam = MagicMock()
    monkeypatch.setattr(scheduler, "_evaluate_buy_opportunities_after_refresh", seam)
    record = MagicMock(status="completed", market_states={
        "A": {"update": {"status": "success"}, "view": {"status": "success"}, "cache": {"status": "failed"}},
        "HK": {"update": {"status": "success"}, "view": {"status": "success"}, "cache": {"status": "success"}},
    })

    scheduler._on_market_refresh_complete(record)

    seam.assert_called_once_with(record, {"HK"})
