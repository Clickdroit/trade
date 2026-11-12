"""Tests de la persistance SQLite du Paper Trading."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tradebot.portfolio.virtual_portfolio import ClosedTrade, Position
from tradebot.storage.sqlite_store import (
    STATUS_RUNNING,
    STATUS_STOPPED,
    BotState,
    CycleRecord,
    DuplicateCandleError,
    PaperStore,
    StorageError,
)

HOUR_MS = 3_600_000


def _state(**overrides: object) -> BotState:
    values: dict[str, object] = {
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "mode": "paper",
        "starting_balance": 1000.0,
        "cash": 1000.0,
        "realized_pnl": 0.0,
        "peak_equity": 1000.0,
        "day_start_equity": 1000.0,
        "day_start_date": "2019-01-01",
        "day_halted": False,
        "last_processed_ts": None,
        "last_price": 100.0,
        "status": STATUS_STOPPED,
        "stop_requested": False,
        "last_cycle_at": None,
    }
    values.update(overrides)
    return BotState(**values)  # type: ignore[arg-type]


def _trade(entry_time: int = 0, exit_time: int = HOUR_MS, pnl: float = 1.0) -> ClosedTrade:
    return ClosedTrade(
        symbol="BTC/USDT",
        entry_time=entry_time,
        exit_time=exit_time,
        entry_price=100.0,
        exit_price=101.0,
        quantity=0.1,
        pnl_gross=pnl,
        pnl_net=pnl,
        fees=0.1,
        exit_reason="signal",
    )


def _cycle(
    candle_ts: int,
    *,
    state: BotState | None = None,
    trade: ClosedTrade | None = None,
) -> CycleRecord:
    return CycleRecord(
        state=_state(last_processed_ts=candle_ts),
        position=None,
        candle_ts=candle_ts,
        signal="BUY",
        action="BUY",
        reason="test",
        price=100.0,
        equity=1000.0,
        trade=trade,
    )


def test_state_and_position_survive_restart(tmp_path: Path) -> None:
    path = tmp_path / "paper.sqlite3"
    store = PaperStore(path)
    store.save_state(_state(cash=899.9, status=STATUS_RUNNING))
    store.record_cycle(
        CycleRecord(
            state=_state(cash=899.9, last_processed_ts=42),
            position=Position("BTC/USDT", 1.0, 100.1, 42, 0.1),
            candle_ts=42,
            signal="BUY",
            action="BUY",
            reason="test",
            price=100.1,
            equity=999.9,
        )
    )
    store.close()

    reopened = PaperStore(path)
    state = reopened.load_state()
    position = reopened.load_position()
    reopened.close()

    assert state is not None
    assert state.cash == pytest.approx(899.9)
    assert state.last_processed_ts == 42
    assert position is not None
    assert position.entry_price == pytest.approx(100.1)
    assert position.quantity == pytest.approx(1.0)


def test_missing_state_returns_none(tmp_path: Path) -> None:
    with PaperStore(tmp_path / "empty.sqlite3") as store:
        assert store.load_state() is None
        assert store.load_position() is None
        assert store.trade_count() == 0


def test_duplicate_candle_is_refused(tmp_path: Path) -> None:
    with PaperStore(tmp_path / "paper.sqlite3") as store:
        store.record_cycle(_cycle(HOUR_MS, trade=_trade()))

        with pytest.raises(DuplicateCandleError):
            store.record_cycle(_cycle(HOUR_MS, trade=_trade()))

        assert store.trade_count() == 1
        assert len(store.decisions()) == 1


def test_duplicate_trade_rolls_back_the_whole_cycle(tmp_path: Path) -> None:
    with PaperStore(tmp_path / "paper.sqlite3") as store:
        store.record_cycle(_cycle(HOUR_MS, trade=_trade()))
        decisions_before = len(store.decisions())

        with pytest.raises(StorageError):
            # Même transaction (entrée/sortie) sur une autre bougie : contrainte UNIQUE.
            store.record_cycle(_cycle(2 * HOUR_MS, trade=_trade()))

        assert len(store.decisions()) == decisions_before
        assert store.trade_count() == 1
        state = store.load_state()
        assert state is not None
        assert state.last_processed_ts == HOUR_MS


def test_status_and_stop_flag(tmp_path: Path) -> None:
    with PaperStore(tmp_path / "paper.sqlite3") as store:
        store.save_state(_state(status=STATUS_RUNNING))
        assert not store.stop_requested()

        store.request_stop()
        assert store.stop_requested()

        store.set_status(STATUS_STOPPED, stop_requested=False)
        assert not store.stop_requested()
        state = store.load_state()
        assert state is not None
        assert state.status == STATUS_STOPPED


def test_reset_clears_all_tables(tmp_path: Path) -> None:
    with PaperStore(tmp_path / "paper.sqlite3") as store:
        store.record_cycle(_cycle(HOUR_MS, trade=_trade()))
        counts = store.reset()

        assert counts["trades"] == 1
        assert counts["decisions"] == 1
        assert counts["processed_candles"] == 1
        assert store.load_state() is None
        assert store.trade_count() == 0


def test_equity_history_is_recorded(tmp_path: Path) -> None:
    with PaperStore(tmp_path / "paper.sqlite3") as store:
        store.record_cycle(_cycle(HOUR_MS))
        points = store.equity_points()

        assert points == [(HOUR_MS, 1000.0)]


def test_newer_schema_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "future.sqlite3"
    PaperStore(path).close()

    connection = sqlite3.connect(path)
    connection.execute("PRAGMA user_version = 99")
    connection.close()

    with pytest.raises(StorageError, match="plus récente"):
        PaperStore(path)
