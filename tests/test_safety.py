"""Tests des protections interdisant toute exécution réelle."""

from __future__ import annotations

import pytest

from tradebot.config import Settings
from tradebot.safety import (
    LiveTradingForbiddenError,
    assert_no_real_funds,
    assert_paper_mode,
    assert_public_market_client,
)


def test_paper_mode_is_accepted() -> None:
    assert_paper_mode("paper")
    assert_paper_mode(" PAPER ")


@pytest.mark.parametrize("mode", ["live", "real", "prod", "production", "binance", "unknown"])
def test_any_other_mode_is_forbidden(mode: str) -> None:
    with pytest.raises(LiveTradingForbiddenError):
        assert_paper_mode(mode)


def test_dry_run_is_mandatory() -> None:
    assert_no_real_funds(True)
    with pytest.raises(LiveTradingForbiddenError):
        assert_no_real_funds(False)


class _Client:
    def __init__(self, api_key: str | None = None, secret: str | None = None) -> None:
        self.apiKey = api_key
        self.secret = secret


def test_public_client_is_accepted() -> None:
    assert_public_market_client(_Client())


@pytest.mark.parametrize("api_key, secret", [("key", None), (None, "secret")])
def test_authenticated_client_is_refused(api_key: str | None, secret: str | None) -> None:
    with pytest.raises(LiveTradingForbiddenError):
        assert_public_market_client(_Client(api_key, secret))


def test_settings_refuse_dry_run_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DRY_RUN", "false")

    with pytest.raises(ValueError, match="DRY_RUN"):
        Settings.from_env()


def test_settings_refuse_live_execution_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("EXECUTION_MODE", "live")

    with pytest.raises(ValueError, match="interdit"):
        Settings.from_env()


def test_settings_read_risk_limits_from_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("EXECUTION_MODE", "paper")
    monkeypatch.setenv("MAX_POSITION_FRACTION", "0.25")
    monkeypatch.setenv("MAX_DAILY_LOSS_FRACTION", "0.02")
    monkeypatch.setenv("PAPER_DB_PATH", str(tmp_path) + "/state.sqlite3")

    settings = Settings.from_env()

    assert settings.max_position_fraction == pytest.approx(0.25)
    assert settings.max_daily_loss_fraction == pytest.approx(0.02)
    assert settings.execution_mode == "paper"
    assert settings.paper_db_path.name == "state.sqlite3"


def test_settings_reject_unknown_timeframe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("TRADING_TIMEFRAME", "7m")

    with pytest.raises(ValueError, match="TRADING_TIMEFRAME"):
        Settings.from_env()
