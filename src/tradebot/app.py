"""Application orchestration.

The first milestone only reads market data and prints decisions.
Order execution is intentionally absent until tests and risk controls are complete.
"""

import logging
import time
from pathlib import Path

from tradebot.config import Settings, setup_logging
from tradebot.domain.models import Candle, Signal
from tradebot.exchange.binance_testnet import fetch_ohlcv
from tradebot.storage.journal import record_event
from tradebot.strategy.moving_average import crossover_signal

logger = logging.getLogger(__name__)

JOURNAL_PATH = Path("data/journal.csv")


def _parse_candles(raw: list[list]) -> list[Candle]:
    """Convertit les données OHLCV brutes en objets Candle."""
    return [
        Candle(
            timestamp=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
        )
        for row in raw
    ]


def run_once(settings: Settings) -> Signal:
    setup_logging(settings.log_level)

    # Récupération des données avec retry (max 3 tentatives)
    raw: list[list] | None = None
    for attempt in range(1, 4):
        try:
            raw = fetch_ohlcv(settings, limit=settings.long_window + 5, logger=logger)
            break
        except Exception:
            logger.warning(
                "Tentative %d/3 de fetch_ohlcv échouée, nouvelle tentative dans 2 s…",
                attempt,
            )
            if attempt < 3:
                time.sleep(2)
            else:
                logger.error("Impossible de récupérer les données après 3 tentatives.")
                raise

    candles = _parse_candles(raw)
    closes = [c.close for c in candles[:-1]]  # ignore unfinished candle
    signal = crossover_signal(closes, settings.short_window, settings.long_window)
    logger.info("%s | dernier signal: %s", settings.symbol, signal)

    # Journal de la décision
    record_event(
        JOURNAL_PATH,
        symbol=settings.symbol,
        signal=str(signal),
        price=candles[-2].close if len(candles) >= 2 else 0.0,
        reason="crossover_signal",
    )

    return signal
