"""Tests d'intégration du cycle de Paper Trading.

Toutes les données sont synthétiques : aucun réseau, aucune clé API, aucune
horloge réelle (les journées UTC viennent des timestamps des bougies).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from tests.helpers import DEFAULT_START_MS, FakeMarket, make_candles, paper_settings, replace_candle
from tradebot.config import Settings
from tradebot.domain.models import Candle
from tradebot.exchange.market import MarketDataError
from tradebot.paper.engine import PaperTrader, PaperTradingError
from tradebot.portfolio.virtual_portfolio import PortfolioStateError
from tradebot.storage.sqlite_store import (
    STATUS_STOPPED,
    BotState,
    PaperStore,
)

HOUR_MS = 3_600_000

#: Croisement haussier MM2/MM3 à la dernière bougie (clôture 101).
BUY_CLOSES = [100.0, 100.0, 100.0, 100.0, 101.0]

#: Achat à 101 puis signal de vente (clôture 99).
SELL_CLOSES = [*BUY_CLOSES, 100.0, 99.0]

#: Perte journalière puis nouveau signal d'achat, bloqué le même jour UTC.
DAILY_CLOSES = [
    100.0,
    100.0,
    100.0,
    100.0,
    101.0,
    101.0,
    103.0,
    105.0,
    100.0,
    99.0,
    98.0,
    97.0,
    99.0,
    102.0,
    105.0,
]


def _prime(store: PaperStore, settings: Settings, candles: Sequence[Candle]) -> None:
    """Simule un bot ayant déjà traité l'historique antérieur aux bougies fournies."""
    starting = settings.starting_balance
    store.save_state(
        BotState(
            symbol=settings.symbol,
            timeframe=settings.timeframe,
            mode="paper",
            starting_balance=starting,
            cash=starting,
            realized_pnl=0.0,
            peak_equity=starting,
            day_start_equity=starting,
            day_start_date="",
            day_halted=False,
            last_processed_ts=candles[0].timestamp - HOUR_MS,
            last_price=0.0,
            status=STATUS_STOPPED,
            stop_requested=False,
            last_cycle_at=None,
        )
    )


def _trader(tmp_path: Path, candles: Sequence[Candle], **overrides: object):
    settings = paper_settings(tmp_path / "paper.sqlite3", **overrides)
    store = PaperStore(settings.paper_db_path)
    _prime(store, settings, candles)
    market = FakeMarket(candles)
    return PaperTrader(settings, store, market), store, market


def _close(store: PaperStore) -> None:
    store.close()


# ---------------------------------------------------------------------------
# Ouverture / fermeture de position
# ---------------------------------------------------------------------------


def test_buy_signal_opens_position_at_candle_close(tmp_path: Path) -> None:
    candles = make_candles(BUY_CLOSES)
    trader, store, _ = _trader(tmp_path, candles)

    outcome = trader.run_cycle()
    summary = outcome.summary
    _close(store)

    assert outcome.processed_candles == 5
    assert outcome.actions == ("BUY",)
    assert summary.position is not None
    assert summary.position.entry_price == pytest.approx(101.0)
    assert summary.position.entry_time == candles[-1].timestamp
    # Taille limitée à 10 % de l'equity, frais inclus.
    assert summary.position.entry_notional <= 100.0 + 1e-6
    assert 899.0 < summary.cash <= 900.0
    assert summary.realized_pnl == pytest.approx(0.0)
    assert summary.trade_count == 0


def test_buy_applies_slippage(tmp_path: Path) -> None:
    candles = make_candles(BUY_CLOSES)
    trader, store, _ = _trader(tmp_path, candles, slippage_pct=0.001)

    summary = trader.run_cycle().summary
    _close(store)

    assert summary.position is not None
    assert summary.position.entry_price == pytest.approx(101.0 * 1.001)


def test_sell_signal_closes_position(tmp_path: Path) -> None:
    candles = make_candles(SELL_CLOSES)
    trader, store, _ = _trader(tmp_path, candles)

    summary = trader.run_cycle().summary
    trades = store.trades()
    _close(store)

    assert summary.position is None
    assert len(trades) == 1
    trade = trades[0]
    assert trade.exit_reason == "signal"
    assert trade.exit_price == pytest.approx(99.0)
    assert trade.pnl_net < 0
    assert summary.equity == pytest.approx(1000.0 + trade.pnl_net)
    assert summary.realized_pnl == pytest.approx(trade.pnl_net)
    assert summary.unrealized_pnl == pytest.approx(0.0)


def test_position_is_not_duplicated_on_new_buy_signal(tmp_path: Path) -> None:
    candles = make_candles([*BUY_CLOSES, 101.0, 101.0, 101.0, 102.0])
    trader, store, _ = _trader(tmp_path, candles)

    summary = trader.run_cycle().summary
    decisions = store.decisions(1)
    _close(store)

    assert len(decisions) == 1
    assert decisions[0].action == "HOLD"
    assert "position ouverte" in decisions[0].reason
    assert summary.trade_count == 0
    assert summary.position is not None
    assert summary.position.entry_time == candles[4].timestamp


def test_buy_is_refused_without_capital(tmp_path: Path) -> None:
    candles = make_candles(BUY_CLOSES)
    trader, store, _ = _trader(tmp_path, candles, starting_balance=0.5)

    summary = trader.run_cycle().summary
    decisions = store.decisions(1)
    _close(store)

    assert summary.position is None
    assert decisions[0].action == "HOLD"
    assert "capital" in decisions[0].reason


def test_catchup_processes_oldest_candles_in_batches(tmp_path: Path) -> None:
    candles = make_candles([100.0, 100.0, 100.0, 100.0, 101.0, 102.0, 103.0])
    trader, store, _ = _trader(tmp_path, candles, catchup_max_candles=2)

    first = trader.run_cycle()
    second = trader.run_cycle()
    third = trader.run_cycle()
    fourth = trader.run_cycle()
    decisions = store.decisions(20)
    _close(store)

    assert first.processed_candles == 2
    assert first.last_candle_ts == candles[1].timestamp
    assert second.processed_candles == 2
    assert second.last_candle_ts == candles[3].timestamp
    assert third.processed_candles == 2
    assert third.last_candle_ts == candles[5].timestamp
    assert fourth.processed_candles == 1
    assert fourth.last_candle_ts == candles[-1].timestamp
    assert len(decisions) == len(candles)


# ---------------------------------------------------------------------------
# Stop-loss
# ---------------------------------------------------------------------------


def test_stop_loss_takes_priority_over_sell_signal(tmp_path: Path) -> None:
    candles = make_candles(SELL_CLOSES, lows=[100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 90.0])
    trader, store, _ = _trader(tmp_path, candles)

    trader.run_cycle()
    trades = store.trades()
    _close(store)

    assert len(trades) == 1
    assert trades[0].exit_reason == "stop_loss"
    # Niveau de stop depuis l'entrée (slippage nul), pas le prix de clôture 99.
    assert trades[0].exit_price == pytest.approx(101.0 * (1 - 0.03))


def test_stop_loss_gap_fills_at_open(tmp_path: Path) -> None:
    candles = make_candles(SELL_CLOSES)
    candles = replace_candle(candles, 6, open=90.0, high=91.0, low=89.0, close=90.0)
    trader, store, _ = _trader(tmp_path, candles)

    trader.run_cycle()
    trades = store.trades()
    _close(store)

    assert trades[0].exit_reason == "stop_loss"
    assert trades[0].exit_price == pytest.approx(90.0)


def test_stop_loss_is_not_evaluated_on_entry_candle(tmp_path: Path) -> None:
    candles = make_candles(BUY_CLOSES, lows=[100.0, 100.0, 100.0, 100.0, 50.0])
    trader, store, _ = _trader(tmp_path, candles)

    summary = trader.run_cycle().summary
    _close(store)

    assert summary.position is not None
    assert summary.trade_count == 0


# ---------------------------------------------------------------------------
# Limite de perte journalière
# ---------------------------------------------------------------------------

_DAILY_SETTINGS = {
    "max_position_fraction": 1.0,
    "max_daily_loss_fraction": 0.005,
    "fee_rate": 0.0,
    "stop_loss_fraction": 0.5,
}


def test_daily_loss_limit_blocks_entries_and_persists(tmp_path: Path) -> None:
    candles = make_candles(DAILY_CLOSES)
    trader, store, _ = _trader(tmp_path, candles, **_DAILY_SETTINGS)

    summary = trader.run_cycle().summary
    decisions = store.decisions(100)
    blocked = [d for d in decisions if d.candle_ts == candles[13].timestamp]
    _close(store)

    assert summary.trade_count == 1
    assert summary.position is None
    assert summary.day_halted is True
    assert blocked, "la décision de la bougie 13 doit être enregistrée"
    assert blocked[0].action == "HOLD"
    assert "journalière" in blocked[0].reason

    # L'état de blocage survit à un redémarrage dans la même journée UTC.
    settings = paper_settings(tmp_path / "paper.sqlite3", **_DAILY_SETTINGS)
    with PaperStore(settings.paper_db_path) as reopened:
        restored = PaperTrader(settings, reopened, market=None)
        assert restored.summary().day_halted is True


def test_daily_loss_limit_resets_at_next_utc_day(tmp_path: Path) -> None:
    # Départ à 13:00 UTC : la bougie 11 tombe à 00:00 le lendemain.
    start = DEFAULT_START_MS + 13 * HOUR_MS
    candles = make_candles(DAILY_CLOSES, start=start)
    trader, store, _ = _trader(tmp_path, candles, **_DAILY_SETTINGS)

    summary = trader.run_cycle().summary
    _close(store)

    assert summary.position is not None
    assert summary.position.entry_time == candles[13].timestamp
    assert summary.day_halted is False


def test_daily_loss_limit_does_not_close_position_by_default(tmp_path: Path) -> None:
    candles = make_candles([100.0, 100.0, 100.0, 100.0, 101.0, 99.0])
    trader, store, _ = _trader(tmp_path, candles, **_DAILY_SETTINGS)

    summary = trader.run_cycle().summary
    _close(store)

    assert summary.day_halted is True
    assert summary.position is not None
    assert summary.trade_count == 0


def test_daily_loss_can_close_position_when_configured(tmp_path: Path) -> None:
    candles = make_candles([100.0, 100.0, 100.0, 100.0, 101.0, 99.0])
    trader, store, _ = _trader(
        tmp_path, candles, close_on_daily_loss=True, **_DAILY_SETTINGS
    )

    summary = trader.run_cycle().summary
    trades = store.trades()
    _close(store)

    assert summary.position is None
    assert len(trades) == 1
    assert trades[0].exit_reason == "daily_loss_limit"


# ---------------------------------------------------------------------------
# Idempotence, redémarrage et erreurs
# ---------------------------------------------------------------------------


def test_processed_candle_is_not_processed_twice(tmp_path: Path) -> None:
    candles = make_candles(SELL_CLOSES)
    trader, store, _ = _trader(tmp_path, candles)

    trader.run_cycle()
    trades_after_first = store.trade_count()
    decisions_after_first = len(store.decisions(100))

    second = trader.run_cycle()
    assert second.processed_candles == 0
    assert store.trade_count() == trades_after_first
    assert len(store.decisions(100)) == decisions_after_first
    _close(store)


def test_restart_resumes_portfolio_without_duplicating(tmp_path: Path) -> None:
    settings = paper_settings(tmp_path / "paper.sqlite3")
    initial = make_candles(BUY_CLOSES)

    store = PaperStore(settings.paper_db_path)
    _prime(store, settings, initial)
    first = PaperTrader(settings, store, FakeMarket(initial))
    first_summary = first.run_cycle().summary
    store.close()

    # Redémarrage : mêmes bougies, aucun nouveau traitement.
    store = PaperStore(settings.paper_db_path)
    resumed = PaperTrader(settings, store, FakeMarket(initial))
    assert resumed.run_cycle().processed_candles == 0
    assert resumed.summary().position is not None
    assert resumed.summary().cash == pytest.approx(first_summary.cash)

    # Le cycle suivant reprend la position et clôture au signal de vente.
    extended = make_candles(SELL_CLOSES)
    second = PaperTrader(settings, store, FakeMarket(extended))
    summary = second.run_cycle().summary
    trades = store.trades()
    store.close()

    assert len(trades) == 1
    assert trades[0].entry_price == pytest.approx(first_summary.position.entry_price)  # type: ignore[union-attr]
    assert summary.position is None


def test_market_error_never_creates_a_trade(tmp_path: Path) -> None:
    candles = make_candles(BUY_CLOSES)
    trader, store, market = _trader(tmp_path, candles)
    market.error = MarketDataError("délai d'attente dépassé")

    with pytest.raises(MarketDataError):
        trader.run_cycle()

    assert store.trade_count() == 0
    assert store.decisions() == []
    state = store.load_state()
    assert state is not None
    assert state.last_processed_ts == candles[0].timestamp - HOUR_MS
    _close(store)


def test_invalid_candles_are_refused(tmp_path: Path) -> None:
    candles = make_candles(BUY_CLOSES)
    invalid = replace_candle(candles, 4, close=-1.0, low=-1.0)
    trader, store, _ = _trader(tmp_path, invalid)

    with pytest.raises(PaperTradingError, match="invalides"):
        trader.run_cycle()

    assert store.trade_count() == 0
    _close(store)


def test_inconsistent_portfolio_state_blocks_trading(tmp_path: Path) -> None:
    candles = make_candles(BUY_CLOSES)
    settings = paper_settings(tmp_path / "paper.sqlite3")
    store = PaperStore(settings.paper_db_path)
    starting = settings.starting_balance
    store.save_state(
        BotState(
            symbol=settings.symbol,
            timeframe=settings.timeframe,
            mode="paper",
            starting_balance=starting,
            cash=5000.0,  # incohérent avec le capital initial
            realized_pnl=0.0,
            peak_equity=starting,
            day_start_equity=starting,
            day_start_date="",
            day_halted=False,
            last_processed_ts=candles[0].timestamp - HOUR_MS,
            last_price=0.0,
            status=STATUS_STOPPED,
            stop_requested=False,
            last_cycle_at=None,
        )
    )
    trader = PaperTrader(settings, store, FakeMarket(candles))

    with pytest.raises(PortfolioStateError):
        trader.run_cycle()

    assert store.trade_count() == 0
    store.close()


def test_state_from_another_market_is_refused(tmp_path: Path) -> None:
    candles = make_candles(BUY_CLOSES)
    settings = paper_settings(tmp_path / "paper.sqlite3")
    store = PaperStore(settings.paper_db_path)
    _prime(store, settings, candles)
    state = store.load_state()

    with_pytest = settings
    store.save_state(
        BotState(
            symbol="ETH/USDT",
            timeframe=with_pytest.timeframe,
            mode="paper",
            starting_balance=with_pytest.starting_balance,
            cash=with_pytest.starting_balance,
            realized_pnl=0.0,
            peak_equity=with_pytest.starting_balance,
            day_start_equity=with_pytest.starting_balance,
            day_start_date="",
            day_halted=False,
            last_processed_ts=state.last_processed_ts if state else None,
            last_price=0.0,
            status=STATUS_STOPPED,
            stop_requested=False,
            last_cycle_at=None,
        )
    )

    with pytest.raises(PaperTradingError, match="État enregistré"):
        PaperTrader(settings, store, FakeMarket(candles))
    store.close()


def test_summary_exposes_required_indicators(tmp_path: Path) -> None:
    candles = make_candles(BUY_CLOSES)
    trader, store, _ = _trader(tmp_path, candles)

    summary = trader.run_cycle().summary
    _close(store)

    assert summary.starting_balance == pytest.approx(1000.0)
    assert summary.cash > 0
    assert summary.equity > 0
    assert summary.mark_price == pytest.approx(101.0)
    assert summary.unrealized_pnl != 0
    # Le drawdown inclut les frais d'achat (equity légèrement sous le pic initial).
    assert 0.0 <= summary.drawdown_pct < 0.05
    assert summary.status == STATUS_STOPPED
    assert summary.last_candle_ts == candles[-1].timestamp


def test_stop_flag_is_honoured_by_run_forever(tmp_path: Path) -> None:
    candles = make_candles(BUY_CLOSES)
    settings = paper_settings(tmp_path / "paper.sqlite3", poll_seconds=1)
    store = PaperStore(settings.paper_db_path)
    waited: list[float] = []

    def _sleeper(seconds: float) -> None:
        # Simule un « paper stop » reçu entre deux cycles.
        waited.append(seconds)
        store.request_stop()

    trader = PaperTrader(settings, store, FakeMarket(candles), sleeper=_sleeper)

    outcomes = []
    trader.run_forever(poll_seconds=1, on_outcome=outcomes.append)
    state = store.load_state()
    market_calls = trader._market.calls if trader._market is not None else 0  # type: ignore[attr-defined]
    store.close()

    assert waited == [1]
    assert len(outcomes) == 1
    # Premier démarrage : seule la dernière bougie clôturée est traitée.
    assert outcomes[0].processed_candles == 1
    assert state is not None
    assert state.status == STATUS_STOPPED
    assert state.last_processed_ts == candles[-1].timestamp
    assert market_calls == 1
