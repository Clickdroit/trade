"""Chargement et sauvegarde de données OHLCV pour le backtesting."""

from __future__ import annotations

import csv
import time
from pathlib import Path

import ccxt

from tradebot.domain.models import Candle

# Nombre maximal de bougies par requête (limite courante des exchanges).
_CHUNK_SIZE = 1000

# Millisecondes dans un jour.
_MS_PER_DAY = 86_400_000

# Correspondance timeframe → durée en millisecondes.
_TIMEFRAME_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


def load_from_exchange(
    symbol: str,
    timeframe: str = "1h",
    since_days: int = 30,
    sandbox: bool = True,
) -> list[Candle]:
    """Récupère les données historiques OHLCV depuis un exchange via ccxt.

    Télécharge les données en morceaux pour respecter les limites de l'API.
    Utilise le mode sandbox par défaut pour éviter les appels en production.
    """
    exchange = ccxt.binance({"enableRateLimit": True})
    if sandbox:
        exchange.set_sandbox_mode(True)

    since_ms = int((time.time() - since_days * 86_400) * 1000)
    tf_ms = _TIMEFRAME_MS.get(timeframe, 3_600_000)

    candles: list[Candle] = []
    current_since = since_ms

    while True:
        raw = exchange.fetch_ohlcv(
            symbol, timeframe, since=current_since, limit=_CHUNK_SIZE
        )
        if not raw:
            break

        for row in raw:
            candles.append(
                Candle(
                    timestamp=int(row[0]),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
            )

        # Avancer le curseur après la dernière bougie récupérée.
        current_since = int(raw[-1][0]) + tf_ms

        if len(raw) < _CHUNK_SIZE:
            break

    return candles


def load_from_csv(path: Path) -> list[Candle]:
    """Charge des données OHLCV depuis un fichier CSV.

    Le CSV doit contenir les colonnes :
    timestamp, open, high, low, close, volume.
    """
    candles: list[Candle] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            candles.append(
                Candle(
                    timestamp=int(row["timestamp"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
            )
    return candles


def save_to_csv(candles: list[Candle], path: Path) -> None:
    """Sauvegarde une liste de bougies au format CSV pour mise en cache."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["timestamp", "open", "high", "low", "close", "volume"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for c in candles:
            writer.writerow(
                {
                    "timestamp": c.timestamp,
                    "open": c.open,
                    "high": c.high,
                    "low": c.low,
                    "close": c.close,
                    "volume": c.volume,
                }
            )
