"""Application orchestration.

``run_once`` reste une analyse ponctuelle : elle lit des bougies publiques et
journalise un signal. Aucune exécution n'a lieu ici ; le cycle de simulation
complet vit dans :mod:`tradebot.paper.engine`.
"""

import logging
from pathlib import Path

from tradebot.config import Settings, setup_logging
from tradebot.domain.models import Signal
from tradebot.exchange.market import CcxtMarketData, MarketDataError
from tradebot.storage.journal import record_event
from tradebot.strategy.moving_average import crossover_signal

logger = logging.getLogger(__name__)

JOURNAL_PATH = Path("data/journal.csv")


def run_once(settings: Settings) -> Signal:
    """Calcule le signal de la dernière bougie clôturée et le journalise.

    Raises:
        MarketDataError: Données indisponibles ou invalides.
    """
    setup_logging(settings.log_level)
    market = CcxtMarketData(settings)
    try:
        candles = market.fetch_closed_candles(settings.long_window + 5)
    except MarketDataError:
        logger.exception("Impossible de récupérer les données de marché.")
        raise

    closes = [candle.close for candle in candles]
    signal = crossover_signal(closes, settings.short_window, settings.long_window)
    last_candle = candles[-1]
    logger.info("%s | dernier signal: %s", settings.symbol, signal)

    record_event(
        JOURNAL_PATH,
        symbol=settings.symbol,
        signal=str(signal),
        price=last_candle.close,
        reason="crossover_signal",
    )
    return signal
