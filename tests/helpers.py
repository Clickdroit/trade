"""Utilitaires de test déterministes : aucune connexion réseau."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from pathlib import Path

from tradebot.backtesting.engine import TradeRecord
from tradebot.config import Settings
from tradebot.domain.models import Candle

HOUR_MS = 3_600_000
#: 2019-01-01 00:00:00 UTC, un mardi, pour des jours UTC prévisibles.
DEFAULT_START_MS = 1_546_300_800_000


def make_candles(
    closes: Sequence[float],
    *,
    start: int = DEFAULT_START_MS,
    step_ms: int = HOUR_MS,
    opens: Sequence[float] | None = None,
    highs: Sequence[float] | None = None,
    lows: Sequence[float] | None = None,
) -> list[Candle]:
    """Construit des bougies à partir de clôtures explicites.

    Par défaut, l'ouverture d'une bougie est la clôture précédente (la première
    ouvre sur elle-même) et les mèches sont nulles.
    """
    candles: list[Candle] = []
    for index, close in enumerate(closes):
        close = float(close)
        if opens is not None:
            open_price = float(opens[index])
        elif index == 0:
            open_price = close
        else:
            open_price = float(closes[index - 1])

        high = float(highs[index]) if highs is not None else max(open_price, close)
        low = float(lows[index]) if lows is not None else min(open_price, close)
        candles.append(
            Candle(
                timestamp=start + index * step_ms,
                open=open_price,
                high=max(high, open_price, close),
                low=min(low, open_price, close),
                close=close,
                volume=1.0,
            )
        )
    return candles


def replace_candle(candles: list[Candle], index: int, **changes: float) -> list[Candle]:
    """Renvoie une copie de la liste avec une bougie modifiée."""
    return [
        dataclasses.replace(candle, **changes) if position == index else candle
        for position, candle in enumerate(candles)
    ]


class FakeMarket:
    """Source de bougies déterministe : aucun accès réseau, aucun aléa."""

    def __init__(self, candles: Sequence[Candle]) -> None:
        self.candles = list(candles)
        self.calls = 0
        self.error: Exception | None = None

    def fetch_closed_candles(self, limit: int) -> list[Candle]:
        """Renvoie les ``limit`` dernières bougies, ou l'erreur configurée."""
        self.calls += 1
        if self.error is not None:
            raise self.error
        if limit <= 0:
            return []
        return self.candles[-limit:]

    def set_candles(self, candles: Sequence[Candle]) -> None:
        """Remplace les bougies disponibles (simulation du temps qui passe)."""
        self.candles = list(candles)


def paper_settings(db_path: Path, **overrides: object) -> Settings:
    """Paramètres Paper Trading déterministes pour les tests."""
    values: dict[str, object] = {
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "short_window": 2,
        "long_window": 3,
        "starting_balance": 1000.0,
        "max_position_fraction": 0.10,
        "max_daily_loss_fraction": 0.05,
        "stop_loss_fraction": 0.03,
        "fee_rate": 0.001,
        "slippage_pct": 0.0,
        "poll_seconds": 60,
        "paper_db_path": db_path,
        "max_retries": 2,
        "retry_backoff_seconds": 0.0,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def make_trade(
    pnl_net: float,
    *,
    pnl_gross: float | None = None,
    fees: float = 0.0,
    exit_reason: str = "signal",
) -> TradeRecord:
    """Construit un :class:`TradeRecord` minimal pour tester les métriques."""
    return TradeRecord(
        entry_time=0,
        exit_time=HOUR_MS,
        entry_price=100.0,
        exit_price=100.0,
        quantity=1.0,
        pnl_gross=pnl_net if pnl_gross is None else pnl_gross,
        pnl_net=pnl_net,
        fees=fees,
        exit_reason=exit_reason,
    )
