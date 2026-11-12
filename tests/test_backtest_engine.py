"""Tests du moteur de backtesting.

Toutes les données sont synthétiques et déterministes : aucune connexion
réseau, aucun appel à Binance.
"""

from __future__ import annotations

import datetime
import math

import pytest

from tests.helpers import make_candles, replace_candle
from tradebot.backtesting.engine import (
    EXIT_END_OF_DATA,
    EXIT_SIGNAL,
    EXIT_STOP_LOSS,
    run_backtest,
)
from tradebot.domain.models import Candle
from tradebot.risk.manager import RiskLimits

SHORT_WINDOW = 2
LONG_WINDOW = 3

#: Entrée à l'ouverture de la bougie 5 (101) puis sortie sur signal à la
#: bougie 10 (ouverture 103).
TREND_CLOSES = [100, 100, 100, 100, 101, 103, 105, 107, 105, 103, 101, 99, 97]

#: Marché plat : les moyennes restent égales, aucun croisement.
FLAT_CLOSES = [100.0] * 40


def _run(closes: list[float], **kwargs: object):
    defaults = {
        "short_window": SHORT_WINDOW,
        "long_window": LONG_WINDOW,
        "starting_balance": 1000.0,
        "fee_rate": 0.001,
        "stop_loss_pct": 0.03,
        "slippage_pct": 0.0,
    }
    defaults.update(kwargs)
    return run_backtest(make_candles(closes), **defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Scénarios de trades
# ---------------------------------------------------------------------------


def test_flat_market_produces_no_trade() -> None:
    result = _run(FLAT_CLOSES)

    assert result.num_trades == 0
    assert result.total_return_pct == pytest.approx(0.0)
    assert result.final_equity == pytest.approx(1000.0)
    assert result.net_pnl == pytest.approx(0.0)
    assert result.win_rate is None
    assert result.profit_factor is None
    assert result.sharpe_ratio is None


def test_winning_trade_enters_at_next_open() -> None:
    result = _run(TREND_CLOSES)
    candles = make_candles(TREND_CLOSES)

    assert result.num_trades == 1
    trade = result.trades[0]
    # Signal produit par la clôture 101 (bougie 4), exécuté à l'ouverture suivante.
    assert trade.entry_price == pytest.approx(101.0)
    assert trade.entry_time == candles[5].timestamp
    # Signal de vente produit par la clôture de la bougie 9, exécuté à l'ouverture 10.
    assert trade.exit_price == pytest.approx(103.0)
    assert trade.exit_time == candles[10].timestamp
    assert trade.exit_reason == EXIT_SIGNAL
    assert trade.pnl_net > 0
    assert result.win_rate == pytest.approx(1.0)
    assert result.winning_trades == 1
    assert result.losing_trades == 0


def test_entry_uses_next_open_not_the_signal_close() -> None:
    candles = make_candles(TREND_CLOSES)
    # La bougie 5 ouvre à 106 alors que la clôture qui a produit le signal vaut 101.
    candles = replace_candle(candles, 5, open=106.0, high=106.5, low=103.0, close=103.0)

    result = run_backtest(
        candles, short_window=SHORT_WINDOW, long_window=LONG_WINDOW, slippage_pct=0.0
    )

    trade = result.trades[0]
    assert trade.entry_time == candles[5].timestamp
    assert trade.entry_price == pytest.approx(106.0)
    assert trade.entry_price != pytest.approx(candles[4].close)


def test_exit_uses_next_open_not_the_signal_close() -> None:
    candles = make_candles(TREND_CLOSES)
    # Le signal de vente vient de la clôture 103 ; l'ouverture suivante vaut 100.
    candles = replace_candle(candles, 10, open=100.0, high=104.0, low=99.0, close=101.0)

    result = run_backtest(
        candles, short_window=SHORT_WINDOW, long_window=LONG_WINDOW, slippage_pct=0.0
    )

    trade = result.trades[0]
    assert trade.exit_time == candles[10].timestamp
    assert trade.exit_price == pytest.approx(100.0)
    assert trade.exit_price != pytest.approx(candles[9].close)


def test_losing_trade_has_negative_net_pnl() -> None:
    # Stop désactivé pour isoler la sortie sur signal baissier.
    closes = [100, 100, 100, 100, 101, 100, 99, 98, 97, 96]
    result = _run(closes, stop_loss_pct=0.5)

    assert result.num_trades == 1
    trade = result.trades[0]
    assert trade.entry_price == pytest.approx(101.0)
    assert trade.exit_price == pytest.approx(99.0)
    assert trade.pnl_net < 0
    assert trade.pnl_gross < 0
    assert result.win_rate == pytest.approx(0.0)
    assert result.losing_trades == 1
    assert result.profit_factor == pytest.approx(0.0)


def test_position_size_never_exceeds_ten_percent() -> None:
    result = _run(TREND_CLOSES)

    trade = result.trades[0]
    notional = trade.entry_price * trade.quantity
    assert notional <= 1000.0 * 0.10 + 1e-9
    assert notional == pytest.approx(100.0)


def test_solvency_is_preserved_on_extreme_gap() -> None:
    candles = make_candles([100, 100, 100, 100, 101, 101, 10])
    result = run_backtest(
        candles,
        short_window=SHORT_WINDOW,
        long_window=LONG_WINDOW,
        fee_rate=0.01,
        slippage_pct=0.0,
        risk_limits=RiskLimits(max_position_fraction=1.0, max_daily_loss_fraction=0.99),
    )

    assert result.final_equity >= 0
    assert result.final_equity == pytest.approx(1000.0 + result.net_pnl)


# ---------------------------------------------------------------------------
# Stop-loss
# ---------------------------------------------------------------------------


def test_stop_loss_triggers_at_stop_level_with_slippage() -> None:
    candles = make_candles(TREND_CLOSES)
    # La bougie 6 ouvre au-dessus du stop (103) puis touche 97 en cours de route.
    candles = replace_candle(candles, 6, low=97.0, high=105.0, close=103.0)

    result = run_backtest(
        candles,
        short_window=SHORT_WINDOW,
        long_window=LONG_WINDOW,
        fee_rate=0.001,
        stop_loss_pct=0.03,
        slippage_pct=0.0005,
    )

    trade = result.trades[0]
    # Le stop est calculé depuis le prix d'entrée, slippage d'achat inclus.
    stop_level = 101.0 * (1 + 0.0005) * (1 - 0.03)
    assert trade.exit_reason == EXIT_STOP_LOSS
    assert trade.exit_time == candles[6].timestamp
    assert trade.exit_price == pytest.approx(stop_level * (1 - 0.0005))
    assert trade.pnl_net < 0


def test_gap_below_stop_fills_at_open_not_at_stop() -> None:
    candles = make_candles(TREND_CLOSES)
    # Gap d'ouverture à 90, très en dessous du stop à 97,97.
    candles = replace_candle(candles, 6, open=90.0, high=91.0, low=89.0, close=90.5)

    result = run_backtest(
        candles,
        short_window=SHORT_WINDOW,
        long_window=LONG_WINDOW,
        fee_rate=0.001,
        stop_loss_pct=0.03,
        slippage_pct=0.0005,
    )

    trade = result.trades[0]
    assert trade.exit_reason == EXIT_STOP_LOSS
    assert trade.exit_price == pytest.approx(90.0 * (1 - 0.0005))
    # Le prix de sortie est bien pire que le niveau de stop : pas d'hypothèse favorable.
    assert trade.exit_price < 101.0 * (1 - 0.03)


# ---------------------------------------------------------------------------
# Frais
# ---------------------------------------------------------------------------


def test_fees_are_charged_on_entry_and_exit() -> None:
    result = _run(TREND_CLOSES)
    trade = result.trades[0]

    entry_fee = trade.entry_price * trade.quantity * 0.001
    exit_fee = trade.exit_price * trade.quantity * 0.001  # type: ignore[attr-defined]

    assert trade.fees == pytest.approx(entry_fee + exit_fee)
    assert trade.pnl_gross == pytest.approx(
        (trade.exit_price - trade.entry_price) * trade.quantity  # type: ignore[attr-defined]
    )
    assert trade.pnl_net == pytest.approx(trade.pnl_gross - trade.fees)
    assert result.total_fees == pytest.approx(trade.fees)
    assert result.net_pnl == pytest.approx(trade.pnl_net)
    assert result.final_equity == pytest.approx(1000.0 + trade.pnl_net)


def test_zero_fees_make_net_equal_gross() -> None:
    result = _run(TREND_CLOSES, fee_rate=0.0)

    trade = result.trades[0]
    assert trade.fees == pytest.approx(0.0)
    assert trade.pnl_net == pytest.approx(trade.pnl_gross)


# ---------------------------------------------------------------------------
# Fin de période et trades successifs
# ---------------------------------------------------------------------------


def test_open_position_is_closed_at_end_of_data() -> None:
    closes = [100, 100, 100, 100, 101, 103, 105, 107, 109, 111, 113]
    candles = make_candles(closes)
    result = _run(closes)

    assert result.num_trades == 1
    trade = result.trades[0]
    assert trade.exit_reason == EXIT_END_OF_DATA
    assert trade.exit_time == candles[-1].timestamp
    assert trade.exit_price == pytest.approx(candles[-1].close)
    assert result.final_equity == pytest.approx(1000.0 + result.net_pnl)


def test_end_of_data_exit_applies_slippage() -> None:
    closes = [100, 100, 100, 100, 101, 103, 105, 107, 109, 111, 113]
    candles = make_candles(closes)
    result = _run(closes, slippage_pct=0.001)

    trade = result.trades[0]
    assert trade.exit_price == pytest.approx(candles[-1].close * (1 - 0.001))


def test_multiple_trades_keep_consistent_accounting() -> None:
    closes = [100 + 4 * math.sin(index / 4) for index in range(80)]
    result = _run(closes)

    assert result.num_trades >= 2
    assert result.final_equity == pytest.approx(1000.0 + sum(t.pnl_net for t in result.trades))

    previous_exit = -1
    for trade in result.trades:
        assert trade.exit_time > trade.entry_time
        assert trade.entry_time >= previous_exit
        previous_exit = trade.exit_time


# ---------------------------------------------------------------------------
# Limite de perte journalière
# ---------------------------------------------------------------------------

#: Perte d'environ 1 % sur un trade, puis signal d'achat à la bougie 11.
DAILY_CLOSES = [100, 100, 100, 100, 101, 101, 103, 105, 100, 100, 101, 103, 105, 107]


def _daily_candles(start: int) -> list[Candle]:
    return make_candles(DAILY_CLOSES, start=start)


def test_daily_loss_limit_blocks_new_entries() -> None:
    permissive = run_backtest(
        _daily_candles(1_546_300_800_000),
        short_window=SHORT_WINDOW,
        long_window=LONG_WINDOW,
        fee_rate=0.0,
        slippage_pct=0.0,
        stop_loss_pct=0.5,
        risk_limits=RiskLimits(max_position_fraction=1.0, max_daily_loss_fraction=0.99),
    )
    halted = run_backtest(
        _daily_candles(1_546_300_800_000),
        short_window=SHORT_WINDOW,
        long_window=LONG_WINDOW,
        fee_rate=0.0,
        slippage_pct=0.0,
        stop_loss_pct=0.5,
        risk_limits=RiskLimits(max_position_fraction=1.0, max_daily_loss_fraction=0.005),
    )

    candidate = _daily_candles(1_546_300_800_000)
    # Le signal d'achat de la bougie 11 est bien exécuté sans blocage...
    assert any(t.entry_time == candidate[11].timestamp for t in permissive.trades)
    # ...mais bloqué le reste de la journée UTC une fois la limite atteinte.
    assert all(t.entry_time != candidate[11].timestamp for t in halted.trades)


def test_daily_loss_limit_resets_at_next_utc_day() -> None:
    # Départ à 13:00 UTC : la bougie 11 tombe à 00:00 le lendemain.
    start = 1_546_300_800_000 + 13 * 3_600_000
    candles = _daily_candles(start)

    result = run_backtest(
        candles,
        short_window=SHORT_WINDOW,
        long_window=LONG_WINDOW,
        fee_rate=0.0,
        slippage_pct=0.0,
        stop_loss_pct=0.5,
        risk_limits=RiskLimits(max_position_fraction=1.0, max_daily_loss_fraction=0.005),
    )

    assert any(t.entry_time == candles[11].timestamp for t in result.trades)
    halt_day = datetime.datetime.fromtimestamp(candles[9].timestamp / 1000, tz=datetime.UTC).date()
    entry_day = datetime.datetime.fromtimestamp(
        candles[11].timestamp / 1000, tz=datetime.UTC
    ).date()
    assert entry_day > halt_day


# ---------------------------------------------------------------------------
# Validation des données et des paramètres
# ---------------------------------------------------------------------------


def test_empty_candles_are_rejected() -> None:
    with pytest.raises(ValueError, match="insuffisantes"):
        run_backtest([], short_window=SHORT_WINDOW, long_window=LONG_WINDOW)


def test_insufficient_candles_are_rejected() -> None:
    candles = make_candles([100] * (LONG_WINDOW + 1))
    with pytest.raises(ValueError, match="insuffisantes"):
        run_backtest(candles, short_window=SHORT_WINDOW, long_window=LONG_WINDOW)


def test_minimum_candle_count_is_accepted() -> None:
    candles = make_candles([100] * (LONG_WINDOW + 2))
    result = run_backtest(candles, short_window=SHORT_WINDOW, long_window=LONG_WINDOW)
    assert result.num_trades == 0


def test_unsorted_candles_are_rejected() -> None:
    candles = make_candles(FLAT_CLOSES)
    candles[3], candles[4] = candles[4], candles[3]
    with pytest.raises(ValueError, match="chronologiques"):
        run_backtest(candles, short_window=SHORT_WINDOW, long_window=LONG_WINDOW)


def test_duplicate_timestamps_are_rejected() -> None:
    candles = make_candles(FLAT_CLOSES)
    candles = replace_candle(candles, 4, timestamp=candles[3].timestamp)
    with pytest.raises(ValueError, match="chronologiques"):
        run_backtest(candles, short_window=SHORT_WINDOW, long_window=LONG_WINDOW)


def test_non_positive_price_is_rejected() -> None:
    candles = replace_candle(make_candles(FLAT_CLOSES), 4, close=0.0, low=0.0)
    with pytest.raises(ValueError, match="invalide"):
        run_backtest(candles, short_window=SHORT_WINDOW, long_window=LONG_WINDOW)


def test_inconsistent_ohlc_is_rejected() -> None:
    candles = replace_candle(make_candles(FLAT_CLOSES), 4, low=200.0)
    with pytest.raises(ValueError, match="incohérente"):
        run_backtest(candles, short_window=SHORT_WINDOW, long_window=LONG_WINDOW)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"short_window": 0, "long_window": 3},
        {"short_window": 3, "long_window": 3},
        {"starting_balance": 0.0},
        {"starting_balance": -100.0},
        {"fee_rate": -0.01},
        {"fee_rate": 1.0},
        {"slippage_pct": -0.01},
        {"slippage_pct": 1.0},
        {"stop_loss_pct": 0.0},
        {"stop_loss_pct": 1.0},
    ],
)
def test_invalid_parameters_are_rejected(kwargs: dict[str, float]) -> None:
    calls = {
        "short_window": SHORT_WINDOW,
        "long_window": LONG_WINDOW,
        "starting_balance": 1000.0,
        "fee_rate": 0.001,
        "slippage_pct": 0.0005,
        "stop_loss_pct": 0.03,
    }
    calls.update(kwargs)
    with pytest.raises(ValueError):
        run_backtest(make_candles(FLAT_CLOSES), **calls)


def test_invalid_risk_limits_are_rejected() -> None:
    with pytest.raises(ValueError):
        run_backtest(
            make_candles(FLAT_CLOSES),
            short_window=SHORT_WINDOW,
            long_window=LONG_WINDOW,
            risk_limits=RiskLimits(max_position_fraction=0.0),
        )
    with pytest.raises(ValueError):
        run_backtest(
            make_candles(FLAT_CLOSES),
            short_window=SHORT_WINDOW,
            long_window=LONG_WINDOW,
            risk_limits=RiskLimits(max_daily_loss_fraction=1.0),
        )
