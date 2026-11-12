import pytest

from tradebot.risk.manager import (
    RiskLimits,
    assess_entry,
    daily_loss_limit_reached,
    position_size,
)


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


def test_assess_entry_sizes_inside_fraction_and_fees() -> None:
    assessment = assess_entry(
        equity=1_000.0, cash=1_000.0, price=100.0, fee_rate=0.001, limits=RiskLimits()
    )

    assert assessment.allowed
    assert assessment.quantity * 100.0 * 1.001 <= 100.0 + 1e-9


def test_assess_entry_is_capped_by_available_cash() -> None:
    assessment = assess_entry(
        equity=1_000.0,
        cash=50.0,
        price=100.0,
        fee_rate=0.0,
        limits=RiskLimits(max_position_fraction=1.0),
    )

    assert assessment.allowed
    assert assessment.quantity == pytest.approx(0.5)


def test_assess_entry_blocks_duplicate_position() -> None:
    assessment = assess_entry(
        equity=1_000.0,
        cash=1_000.0,
        price=100.0,
        fee_rate=0.001,
        limits=RiskLimits(),
        has_position=True,
    )

    assert not assessment.allowed
    assert "position" in assessment.reason


def test_assess_entry_blocks_after_daily_loss() -> None:
    assessment = assess_entry(
        equity=1_000.0,
        cash=1_000.0,
        price=100.0,
        fee_rate=0.001,
        limits=RiskLimits(),
        daily_halted=True,
    )

    assert not assessment.allowed
    assert "journalière" in assessment.reason


def test_assess_entry_blocks_without_capital() -> None:
    assessment = assess_entry(
        equity=0.5, cash=0.5, price=100.0, fee_rate=0.001, limits=RiskLimits()
    )

    assert not assessment.allowed
    assert "capital" in assessment.reason


def test_assess_entry_rejects_invalid_data() -> None:
    assessment = assess_entry(
        equity=1_000.0,
        cash=1_000.0,
        price=float("nan"),
        fee_rate=0.001,
        limits=RiskLimits(),
    )

    assert not assessment.allowed
    assert "invalides" in assessment.reason
