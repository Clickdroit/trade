"""Tests des métriques de backtesting."""

from __future__ import annotations

import math
import statistics

import pytest

from tests.helpers import make_candles, make_trade
from tradebot.backtesting.engine import run_backtest
from tradebot.backtesting.metrics import (
    compute_average_loss,
    compute_average_win,
    compute_max_drawdown,
    compute_profit_factor,
    compute_return_pct,
    compute_sharpe_ratio,
    compute_win_rate,
    format_report,
)


def test_return_pct() -> None:
    assert compute_return_pct(1000.0, 1100.0) == pytest.approx(10.0)
    assert compute_return_pct(1000.0, 900.0) == pytest.approx(-10.0)


def test_return_pct_rejects_zero_start() -> None:
    with pytest.raises(ValueError):
        compute_return_pct(0.0, 100.0)


def test_max_drawdown_peak_to_trough() -> None:
    assert compute_max_drawdown([100, 120, 90, 110]) == pytest.approx(0.25)


def test_max_drawdown_edge_cases() -> None:
    assert compute_max_drawdown([]) == 0.0
    assert compute_max_drawdown([100]) == 0.0
    assert compute_max_drawdown([100, 110, 120]) == 0.0


def test_sharpe_ratio_matches_sample_formula() -> None:
    returns = [0.01, -0.02, 0.03, 0.0]
    expected = statistics.mean(returns) / statistics.stdev(returns) * math.sqrt(4)
    assert compute_sharpe_ratio(returns, periods_per_year=4) == pytest.approx(expected)


def test_sharpe_ratio_annualisation_scales_with_frequency() -> None:
    returns = [0.01, -0.02, 0.03, 0.0]
    hourly = compute_sharpe_ratio(returns, periods_per_year=8760)
    daily = compute_sharpe_ratio(returns, periods_per_year=365)
    assert hourly is not None and daily is not None
    assert hourly == pytest.approx(daily * math.sqrt(8760 / 365))


def test_sharpe_ratio_returns_none_when_undefined() -> None:
    assert compute_sharpe_ratio([]) is None
    assert compute_sharpe_ratio([0.01]) is None
    assert compute_sharpe_ratio([0.01, 0.01, 0.01]) is None


def test_sharpe_ratio_rejects_invalid_periods() -> None:
    with pytest.raises(ValueError):
        compute_sharpe_ratio([0.01, 0.02], periods_per_year=0)


def test_win_rate_counts_only_positive_trades() -> None:
    trades = [make_trade(10.0), make_trade(-5.0), make_trade(0.0)]
    assert compute_win_rate(trades) == pytest.approx(1 / 3)
    assert compute_win_rate([]) is None


def test_profit_factor() -> None:
    assert compute_profit_factor([make_trade(10.0), make_trade(-5.0)]) == pytest.approx(2.0)
    assert compute_profit_factor([make_trade(-5.0)]) == pytest.approx(0.0)
    assert compute_profit_factor([]) is None
    assert compute_profit_factor([make_trade(0.0), make_trade(0.0)]) is None


def test_profit_factor_is_infinite_without_losses() -> None:
    assert math.isinf(compute_profit_factor([make_trade(10.0), make_trade(2.0)]) or 0.0)


def test_average_win_and_loss() -> None:
    trades = [make_trade(10.0), make_trade(20.0), make_trade(-4.0)]
    assert compute_average_win(trades) == pytest.approx(15.0)
    assert compute_average_loss(trades) == pytest.approx(-4.0)
    assert compute_average_win([make_trade(-1.0)]) is None
    assert compute_average_loss([make_trade(1.0)]) is None


def test_report_displays_na_instead_of_fake_values() -> None:
    result = run_backtest(make_candles([100.0] * 40), short_window=2, long_window=3)
    report = format_report(result)

    assert "RAPPORT DE BACKTEST" in report
    assert "n/a" in report
    assert "0 (0 gagnants / 0 perdants)" in report


def test_report_displays_infinite_profit_factor() -> None:
    closes = [100, 100, 100, 100, 101, 103, 105, 107, 105, 103, 101, 99, 97]
    result = run_backtest(
        make_candles(closes), short_window=2, long_window=3, fee_rate=0.0, slippage_pct=0.0
    )
    assert math.isinf(result.profit_factor or 0.0)
    assert "infini (aucune perte)" in format_report(result)
