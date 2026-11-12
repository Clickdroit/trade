"""Small domain objects shared by the application."""

from __future__ import annotations

import datetime
import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


class Signal(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(frozen=True)
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class TradeDecision:
    signal: Signal
    reason: str
    price: float


#: Durée de chaque timeframe supportée, en millisecondes.
TIMEFRAME_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}

#: Motifs de sortie d'une position, partagés par le backtest et le Paper Trading.
EXIT_SIGNAL = "signal"
EXIT_STOP_LOSS = "stop_loss"
EXIT_END_OF_DATA = "end_of_data"
EXIT_DAILY_LOSS = "daily_loss_limit"


def timeframe_ms(timeframe: str) -> int:
    """Durée d'un timeframe en millisecondes.

    Raises:
        ValueError: Timeframe inconnu.
    """
    try:
        return TIMEFRAME_MS[timeframe]
    except KeyError as exc:
        supported = ", ".join(sorted(TIMEFRAME_MS))
        raise ValueError(f"Timeframe non supporté : {timeframe!r}. Choix : {supported}.") from exc


def utc_datetime_from_ms(timestamp_ms: int) -> datetime.datetime:
    """Convertit un timestamp millisecondes en datetime UTC."""
    return datetime.datetime.fromtimestamp(timestamp_ms / 1000, tz=datetime.UTC)


def utc_date_from_ms(timestamp_ms: int) -> datetime.date:
    """Convertit un timestamp millisecondes en date UTC (journée de référence)."""
    return utc_datetime_from_ms(timestamp_ms).date()


def validate_candles(candles: Sequence[Candle], *, minimum: int = 1) -> None:
    """Vérifie quantité, ordre, unicité et cohérence OHLC des bougies.

    Raises:
        ValueError: Données insuffisantes, non chronologiques, dupliquées ou
            incohérentes. Aucune correction silencieuse n'est appliquée.
    """
    if len(candles) < minimum:
        raise ValueError(
            f"Données insuffisantes : {len(candles)} bougies fournies, "
            f"au moins {minimum} sont nécessaires."
        )

    previous_timestamp: int | None = None
    for candle in candles:
        if previous_timestamp is not None and candle.timestamp <= previous_timestamp:
            raise ValueError(
                "Bougies non strictement chronologiques "
                f"(timestamp {candle.timestamp} après {previous_timestamp})."
            )
        if not math.isfinite(candle.timestamp):
            raise ValueError(f"Horodatage invalide : {candle.timestamp!r}.")
        for name in ("open", "high", "low", "close"):
            value = getattr(candle, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"Prix {name} invalide à {candle.timestamp} : {value!r}.")
        if not math.isfinite(candle.volume) or candle.volume < 0:
            raise ValueError(f"Volume invalide à {candle.timestamp} : {candle.volume!r}.")
        if candle.high < max(candle.open, candle.close) or candle.low > min(
            candle.open, candle.close
        ):
            raise ValueError(
                f"Bougie incohérente à {candle.timestamp} : high/low incompatibles "
                "avec open/close."
            )
        previous_timestamp = candle.timestamp
