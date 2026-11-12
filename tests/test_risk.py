from tradebot.risk.manager import RiskLimits, daily_loss_limit_reached, position_size


def test_position_size_respects_maximum_fraction():
    assert position_size(1_000, 50_000, RiskLimits()) == 0.002


def test_daily_loss_guard_activates_at_limit():
    assert daily_loss_limit_reached(1_000, 950, RiskLimits())


def test_daily_loss_guard_stays_inactive_below_limit():
    assert not daily_loss_limit_reached(1_000, 980, RiskLimits())
