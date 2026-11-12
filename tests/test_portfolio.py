"""Tests du portefeuille virtuel (comptabilité déterministe, hors ligne)."""

from __future__ import annotations

import pytest

from tradebot.portfolio.virtual_portfolio import (
    ClosedTrade,
    PortfolioStateError,
    Position,
    VirtualPortfolio,
)

SYMBOL = "BTC/USDT"
HOUR_MS = 3_600_000


def _portfolio(starting: float = 1000.0, fee_rate: float = 0.001) -> VirtualPortfolio:
    return VirtualPortfolio(starting_balance=starting, fee_rate=fee_rate)


def test_open_position_deducts_notional_and_fees() -> None:
    portfolio = _portfolio()
    position = portfolio.open_position(SYMBOL, 100.0, 1.0, 1_000)

    assert position.quantity == pytest.approx(1.0)
    assert position.entry_price == pytest.approx(100.0)
    assert position.entry_fee == pytest.approx(0.1)
    assert portfolio.cash == pytest.approx(899.9)
    assert portfolio.realized_pnl == pytest.approx(0.0)
    assert portfolio.equity(110.0) == pytest.approx(1009.9)
    assert portfolio.unrealized_pnl(110.0) == pytest.approx(9.9)


def test_close_position_realises_net_pnl() -> None:
    portfolio = _portfolio()
    portfolio.open_position(SYMBOL, 100.0, 1.0, 1_000)
    trade = portfolio.close_position(110.0, 2 * HOUR_MS, "signal")

    assert isinstance(trade, ClosedTrade)
    assert trade.pnl_gross == pytest.approx(10.0)
    assert trade.fees == pytest.approx(0.21)
    assert trade.pnl_net == pytest.approx(9.79)
    assert portfolio.realized_pnl == pytest.approx(9.79)
    assert portfolio.cash == pytest.approx(1009.79)
    assert portfolio.position is None
    assert portfolio.equity(110.0) == pytest.approx(1009.79)


def test_equity_equals_starting_plus_realised_plus_unrealised() -> None:
    portfolio = _portfolio()
    portfolio.open_position(SYMBOL, 250.0, 2.0, 1_000)

    for price in (240.0, 250.0, 260.0):
        assert portfolio.equity(price) == pytest.approx(
            portfolio.starting_balance + portfolio.realized_pnl + portfolio.unrealized_pnl(price)
        )
    portfolio.assert_consistent(260.0)


def test_duplicate_position_is_refused() -> None:
    portfolio = _portfolio()
    portfolio.open_position(SYMBOL, 100.0, 1.0, 1_000)

    with pytest.raises(ValueError, match="déjà ouverte"):
        portfolio.open_position(SYMBOL, 100.0, 1.0, 2 * HOUR_MS)


def test_buy_without_enough_cash_is_refused() -> None:
    portfolio = _portfolio(starting=100.0)

    with pytest.raises(ValueError, match="Solde insuffisant"):
        portfolio.open_position(SYMBOL, 100.0, 2.0, 1_000)
    assert portfolio.position is None
    assert portfolio.cash == pytest.approx(100.0)


def test_sell_without_position_is_refused() -> None:
    portfolio = _portfolio()

    with pytest.raises(ValueError, match="Aucune position"):
        portfolio.close_position(100.0, 1_000, "signal")


def test_exit_before_entry_is_refused() -> None:
    portfolio = _portfolio()
    portfolio.open_position(SYMBOL, 100.0, 1.0, 5_000)

    with pytest.raises(ValueError, match="précède"):
        portfolio.close_position(110.0, 4_000, "signal")


def test_drawdown_tracks_peak_equity() -> None:
    portfolio = _portfolio()
    portfolio.open_position(SYMBOL, 1.0, 10.0, 0)

    peak = portfolio.mark(12.0)
    portfolio.mark(10.0)

    expected = (peak - portfolio.equity(10.0)) / peak * 100
    assert portfolio.drawdown_pct(10.0) == pytest.approx(expected)
    assert portfolio.drawdown_pct(12.0) == pytest.approx(0.0)
    assert portfolio.peak_equity == pytest.approx(peak)


def test_restored_portfolio_matches_operations() -> None:
    original = _portfolio()
    original.open_position(SYMBOL, 100.0, 1.0, 1_000)

    restored = VirtualPortfolio(
        starting_balance=original.starting_balance,
        fee_rate=original.fee_rate,
        cash=original.cash,
        realized_pnl=original.realized_pnl,
        peak_equity=original.peak_equity,
    )
    position = original.position
    assert position is not None
    restored.load_position(position)

    restored.assert_consistent(120.0)
    assert restored.equity(120.0) == pytest.approx(original.equity(120.0))


def test_inconsistent_cash_is_detected() -> None:
    portfolio = VirtualPortfolio(starting_balance=1000.0, cash=5000.0)

    with pytest.raises(PortfolioStateError, match="Trésorerie incohérente"):
        portfolio.assert_consistent()


def test_invalid_position_is_detected_on_restore() -> None:
    portfolio = _portfolio()

    with pytest.raises(PortfolioStateError):
        portfolio.load_position(
            Position(symbol=SYMBOL, quantity=-1.0, entry_price=100.0, entry_time=0, entry_fee=0.1)
        )


def test_invalid_constructor_parameters_are_rejected() -> None:
    with pytest.raises(ValueError):
        VirtualPortfolio(starting_balance=0.0)
    with pytest.raises(ValueError):
        VirtualPortfolio(starting_balance=1000.0, fee_rate=1.0)
    with pytest.raises(ValueError):
        VirtualPortfolio(starting_balance=1000.0, cash=-1.0)


def test_stop_loss_detection() -> None:
    portfolio = _portfolio()
    portfolio.open_position(SYMBOL, 100.0, 1.0, 0)

    assert portfolio.check_stop_loss(97.0, 0.03)
    assert not portfolio.check_stop_loss(98.0, 0.03)
    with pytest.raises(ValueError):
        portfolio.check_stop_loss(0.0, 0.03)
