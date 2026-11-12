"""Tests du chargement de données (CSV et adaptation CCXT simulée)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from tests.helpers import make_candles
from tradebot.backtesting import data_loader
from tradebot.backtesting.data_loader import (
    DataLoadError,
    load_from_csv,
    load_from_exchange,
    save_to_csv,
)


def test_csv_roundtrip(tmp_path: Path) -> None:
    candles = make_candles([100.0, 101.5, 99.0, 102.0])
    path = tmp_path / "nested" / "candles.csv"

    save_to_csv(candles, path)
    loaded = load_from_csv(path)

    assert loaded == candles


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(DataLoadError, match="introuvable"):
        load_from_csv(tmp_path / "absent.csv")


def test_missing_columns_raise(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("timestamp,close\n1,100\n", encoding="utf-8")

    with pytest.raises(DataLoadError, match="Colonnes manquantes"):
        load_from_csv(path)


def test_invalid_row_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text(
        "timestamp,open,high,low,close,volume\n1,100,101,99,100,1\n2,abc,101,99,100,1\n",
        encoding="utf-8",
    )

    with pytest.raises(DataLoadError, match="Ligne 3"):
        load_from_csv(path)


def test_duplicate_timestamps_raise(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.csv"
    path.write_text(
        "timestamp,open,high,low,close,volume\n1000,100,101,99,100,1\n1000,100,101,99,100,1\n",
        encoding="utf-8",
    )

    with pytest.raises(DataLoadError, match="chronologiques"):
        load_from_csv(path)


def test_header_only_csv_raises(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("timestamp,open,high,low,close,volume\n", encoding="utf-8")

    with pytest.raises(DataLoadError, match="aucune bougie"):
        load_from_csv(path)


def test_directory_is_not_a_csv(tmp_path: Path) -> None:
    with pytest.raises(DataLoadError, match="n'est pas un fichier"):
        load_from_csv(tmp_path)


def test_unsupported_timeframe_rejected_before_network() -> None:
    with pytest.raises(DataLoadError, match="Timeframe non supporté"):
        load_from_exchange("BTC/USDT", "2h", 10)


def test_invalid_symbol_rejected() -> None:
    with pytest.raises(DataLoadError, match="Symbole invalide"):
        load_from_exchange("BTCUSDT", "1h", 10)


def test_non_positive_depth_rejected() -> None:
    with pytest.raises(DataLoadError, match="profondeur"):
        load_from_exchange("BTC/USDT", "1h", 0)


class _FakeExchange:
    """Exchange factice renvoyant une pagination désordonnée avec doublon."""

    def __init__(self, rows: list[list]) -> None:
        self._rows = rows

    def set_sandbox_mode(self, enabled: bool) -> None:
        return None

    def fetch_ohlcv(self, *args: object, **kwargs: object) -> list[list]:
        return self._rows

    def close(self) -> None:
        return None


def test_exchange_data_are_sorted_and_deduplicated(monkeypatch: pytest.MonkeyPatch) -> None:
    base = int(time.time() * 1000) - 5 * 3_600_000
    rows = [
        [base + 3_600_000, 100, 101, 99, 100, 1],
        [base, 100, 101, 99, 100, 1],
        [base + 3_600_000, 100, 101, 99, 100, 1],
    ]
    fake = _FakeExchange(rows)
    monkeypatch.setattr(data_loader.ccxt, "binance", lambda config: fake)

    candles = load_from_exchange("BTC/USDT", "1h", 1)

    assert [candle.timestamp for candle in candles] == [base, base + 3_600_000]


def test_exchange_drops_the_unclosed_last_candle(monkeypatch: pytest.MonkeyPatch) -> None:
    base = int(time.time() * 1000) - 4 * 3_600_000
    rows = [
        [base, 100, 101, 99, 100, 1],
        [base + 3_600_000, 100, 101, 99, 100, 1],
        # Ouvre à l'instant : sa clôture n'est pas encore connue.
        [base + 4 * 3_600_000, 100, 101, 99, 100, 1],
    ]
    fake = _FakeExchange(rows)
    monkeypatch.setattr(data_loader.ccxt, "binance", lambda config: fake)

    candles = load_from_exchange("BTC/USDT", "1h", 1)

    assert [candle.timestamp for candle in candles] == [base, base + 3_600_000]


def test_exchange_errors_are_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BrokenExchange(_FakeExchange):
        def fetch_ohlcv(self, *args: object, **kwargs: object) -> list[list]:
            raise data_loader.ccxt.NetworkError("réseau coupé")

    monkeypatch.setattr(data_loader.ccxt, "binance", lambda config: _BrokenExchange([]))

    with pytest.raises(DataLoadError, match="impossible"):
        load_from_exchange("BTC/USDT", "1h", 1)


def test_empty_exchange_result_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data_loader.ccxt, "binance", lambda config: _FakeExchange([]))

    with pytest.raises(DataLoadError, match="Aucune bougie"):
        load_from_exchange("BTC/USDT", "1h", 1)
