import pytest

from tradebot.risk.manager import RiskLimits, daily_loss_limit_reached, position_size


def test_position_size_respects_maximum_fraction() -> None:
    assert position_size(1_000, 50_000, RiskLimits()) == 0.002


def test_position_size_with_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        position_size(0, 50_000, RiskLimits())
    with pytest.raises(ValueError):
        position_size(1_000, 0, RiskLimits())
    with pytest.raises(ValueError):
        position_size(1_000, 50_000, RiskLimits(max_position_fraction=0))


def test_daily_loss_guard_activates_at_limit() -> None:
    assert daily_loss_limit_reached(1_000, 950, RiskLimits())


def test_daily_loss_guard_stays_inactive_below_limit() -> None:
    assert not daily_loss_limit_reached(1_000, 980, RiskLimits())


def test_daily_loss_guard_uses_the_provided_equity() -> None:
    # Une position ouverte valorisée 940 fait franchir la limite de 5 %.
    assert daily_loss_limit_reached(1_000, 940, RiskLimits())
    assert not daily_loss_limit_reached(1_000, 951, RiskLimits())


def test_daily_loss_guard_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        daily_loss_limit_reached(0, 100, RiskLimits())
    with pytest.raises(ValueError):
        daily_loss_limit_reached(1_000, -1, RiskLimits())
    with pytest.raises(ValueError):
        daily_loss_limit_reached(1_000, 900, RiskLimits(max_daily_loss_fraction=1.0))
