"""Application orchestration.

The first milestone only reads market data and prints decisions.
Order execution is intentionally absent until tests and risk controls are complete.
"""

from tradebot.config import Settings
from tradebot.domain.models import Signal
from tradebot.exchange.binance_testnet import fetch_ohlcv
from tradebot.strategy.moving_average import crossover_signal


def run_once(settings: Settings) -> Signal:
    candles = fetch_ohlcv(settings, limit=settings.long_window + 5)
    closes = [float(candle[4]) for candle in candles[:-1]]  # ignore unfinished candle
    signal = crossover_signal(closes, settings.short_window, settings.long_window)
    print(f"{settings.symbol} | dernier signal: {signal}")
    return signal
