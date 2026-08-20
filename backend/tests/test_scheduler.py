from unittest.mock import MagicMock

import scheduler


def test_successful_refresh_calls_buy_opportunity_seam(monkeypatch):
    seam = MagicMock()
    monkeypatch.setattr(scheduler, "_evaluate_buy_opportunities_after_refresh", seam)

    record = MagicMock(status="completed", market_states={"A": {"update": {"detail": {}}}})
    scheduler._on_market_refresh_complete(record)

    seam.assert_called_once_with(record)


def test_partial_refresh_does_not_call_buy_opportunity_seam(monkeypatch):
    seam = MagicMock()
    monkeypatch.setattr(scheduler, "_evaluate_buy_opportunities_after_refresh", seam)

    record = MagicMock(status="partial", market_states={})
    scheduler._on_market_refresh_complete(record)

    seam.assert_not_called()
