"""Tests de l'adaptateur de données de marché (aucun accès réseau)."""

from __future__ import annotations

from pathlib import Path

import ccxt
import pytest

from tests.helpers import DEFAULT_START_MS, make_candles, paper_settings
from tradebot.domain.models import Candle
from tradebot.exchange.market import CcxtMarketData, MarketDataError, parse_ohlcv
from tradebot.safety import LiveTradingForbiddenError

HOUR_MS = 3_600_000


class _FakeClient:
    """Client CCXT minimal : réponses scriptées, aucune entrée/sortie réseau."""

    def __init__(self, responses: list[object], api_key: str | None = None) -> None:
        self.responses = responses
        self.calls = 0
        self.apiKey = api_key
        self.secret = None

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list]:
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        response = self.responses[index]
        if isinstance(response, Exception):
            raise response
        return response  # type: ignore[return-value]


def _rows(candles: list[Candle]) -> list[list]:
    return [
        [c.timestamp, c.open, c.high, c.low, c.close, c.volume]
        for c in candles
    ]


def _market(
    tmp_path: Path, client: _FakeClient, clock: float, **overrides: object
) -> CcxtMarketData:
    settings = paper_settings(tmp_path / "paper.sqlite3", **overrides)
    return CcxtMarketData(
        settings,
        client_factory=lambda _: client,
        clock=lambda: clock,
        sleeper=lambda _: None,
    )


def test_unfinished_candle_is_excluded(tmp_path: Path) -> None:
    candles = make_candles([100.0, 101.0, 102.0])
    client = _FakeClient([_rows(candles)])
    # Fin exacte de la 2e bougie : la 3e est encore en formation.
    clock = (DEFAULT_START_MS + 2 * HOUR_MS) / 1000

    closed = _market(tmp_path, client, clock).fetch_closed_candles(10)

    assert [c.close for c in closed] == [100.0, 101.0]


def test_only_unfinished_candles_is_an_error(tmp_path: Path) -> None:
    candles = make_candles([100.0])
    client = _FakeClient([_rows(candles)])
    clock = DEFAULT_START_MS / 1000

    with pytest.raises(MarketDataError, match="clôturée"):
        _market(tmp_path, client, clock).fetch_closed_candles(10)


def test_network_error_is_retried(tmp_path: Path) -> None:
    candles = make_candles([100.0, 101.0])
    client = _FakeClient([ccxt.NetworkError("boom"), _rows(candles)])
    clock = (DEFAULT_START_MS + 5 * HOUR_MS) / 1000

    closed = _market(tmp_path, client, clock, max_retries=2).fetch_closed_candles(10)

    assert client.calls == 2
    assert len(closed) == 2


def test_persistent_network_error_is_reported(tmp_path: Path) -> None:
    client = _FakeClient([ccxt.NetworkError("boom")])
    clock = (DEFAULT_START_MS + 5 * HOUR_MS) / 1000

    with pytest.raises(MarketDataError, match="impossible"):
        _market(tmp_path, client, clock, max_retries=3).fetch_closed_candles(10)
    assert client.calls == 3


def test_empty_response_is_reported(tmp_path: Path) -> None:
    client = _FakeClient([[]])
    clock = (DEFAULT_START_MS + 5 * HOUR_MS) / 1000

    with pytest.raises(MarketDataError, match="Aucune bougie"):
        _market(tmp_path, client, clock).fetch_closed_candles(10)


def test_invalid_values_are_rejected(tmp_path: Path) -> None:
    client = _FakeClient([[[DEFAULT_START_MS, 100, 100, 100, -1, 1]]])
    clock = (DEFAULT_START_MS + 5 * HOUR_MS) / 1000

    with pytest.raises(MarketDataError, match="invalides"):
        _market(tmp_path, client, clock).fetch_closed_candles(10)


def test_unsorted_candles_are_rejected(tmp_path: Path) -> None:
    rows = _rows(make_candles([100.0, 101.0]))
    client = _FakeClient([list(reversed(rows))])
    clock = (DEFAULT_START_MS + 5 * HOUR_MS) / 1000

    with pytest.raises(MarketDataError, match="invalides"):
        _market(tmp_path, client, clock).fetch_closed_candles(10)


def test_authenticated_client_is_refused(tmp_path: Path) -> None:
    client = _FakeClient([[]], api_key="secret")

    with pytest.raises(LiveTradingForbiddenError):
        _market(tmp_path, client, 0.0)


def test_parse_ohlcv_rejects_incomplete_rows() -> None:
    with pytest.raises(MarketDataError, match="incomplète"):
        parse_ohlcv([[1, 2, 3]])


def test_parse_ohlcv_builds_candles() -> None:
    candles = parse_ohlcv([[1000, "1", "2", "0.5", "1.5", "10"]])

    assert candles[0].timestamp == 1000
    assert candles[0].close == pytest.approx(1.5)


def test_non_positive_limit_is_refused(tmp_path: Path) -> None:
    client = _FakeClient([[]])

    with pytest.raises(ValueError):
        _market(tmp_path, client, 0.0).fetch_closed_candles(0)
