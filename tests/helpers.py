"""Utilitaires de test déterministes : aucune connexion réseau."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

from tradebot.backtesting.engine import TradeRecord
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
