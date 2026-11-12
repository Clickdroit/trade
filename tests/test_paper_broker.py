"""Tests du broker d'exécution simulé."""

from __future__ import annotations

import pytest

from tests.helpers import make_candles
from tradebot.paper.broker import SimulatedBroker
from tradebot.portfolio.virtual_portfolio import VirtualPortfolio


def _broker(slippage: float = 0.001, starting: float = 1000.0) -> SimulatedBroker:
    return SimulatedBroker(VirtualPortfolio(starting_balance=starting, fee_rate=0.001), slippage)


def test_buy_applies_unfavourable_slippage_and_fees() -> None:
    broker = _broker()
    fill = broker.buy("BTC/USDT", 100.0, 1.0, 1_000, "test")

    assert fill.price == pytest.approx(100.1)
    assert fill.notional == pytest.approx(100.1)
    assert fill.fee == pytest.approx(0.1001)
    assert broker.portfolio.cash == pytest.approx(1000.0 - 100.1 - 0.1001)
    assert broker.portfolio.position is not None


def test_sell_applies_unfavourable_slippage_and_fees() -> None:
    broker = _broker()
    broker.buy("BTC/USDT", 100.0, 1.0, 1_000, "test")
    trade = broker.sell(110.0, 2_000, "signal")

    assert trade.exit_price == pytest.approx(110.0 * 0.999)
    assert trade.fees == pytest.approx(0.1001 + 110.0 * 0.999 * 0.001)
    assert broker.portfolio.position is None
    assert broker.portfolio.realized_pnl == pytest.approx(trade.pnl_net)


def test_zero_slippage_uses_reference_price() -> None:
    broker = _broker(slippage=0.0)

    assert broker.buy_price(100.0) == pytest.approx(100.0)
    assert broker.sell_price(100.0) == pytest.approx(100.0)


def test_stop_not_triggered_above_level() -> None:
    broker = _broker()
    candle = make_candles([100.0])[0]

    assert broker.stop_fill_price(candle, 97.0) is None


def test_stop_fills_at_level_with_slippage() -> None:
    broker = _broker(slippage=0.001)
    candle = make_candles([100.0], opens=[101.0], lows=[95.0])[0]

    assert broker.stop_fill_price(candle, 97.0) == pytest.approx(97.0 * 0.999)


def test_gap_below_stop_fills_at_open() -> None:
    broker = _broker(slippage=0.001)
    candle = make_candles([90.0], opens=[90.0], highs=[91.0], lows=[89.0])[0]

    assert broker.stop_fill_price(candle, 97.0) == pytest.approx(90.0 * 0.999)


def test_duplicate_buy_is_refused() -> None:
    broker = _broker()
    broker.buy("BTC/USDT", 100.0, 1.0, 1_000, "test")

    with pytest.raises(ValueError, match="déjà ouverte"):
        broker.buy("BTC/USDT", 100.0, 1.0, 2_000, "test")


def test_sell_without_position_is_refused() -> None:
    broker = _broker()

    with pytest.raises(ValueError, match="Aucune position"):
        broker.sell(100.0, 1_000, "signal")


def test_invalid_slippage_is_refused() -> None:
    portfolio = VirtualPortfolio()

    with pytest.raises(ValueError):
        SimulatedBroker(portfolio, slippage_pct=1.0)
    with pytest.raises(ValueError):
        SimulatedBroker(portfolio, slippage_pct=-0.1)


def test_invalid_reference_price_is_refused() -> None:
    broker = _broker()

    with pytest.raises(ValueError):
        broker.buy_price(0.0)
    with pytest.raises(ValueError):
        broker.sell_price(float("nan"))
