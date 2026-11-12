"""Moving-average crossover strategy, independent from any exchange."""

from collections.abc import Sequence

from tradebot.domain.models import Signal


def moving_average(values: Sequence[float], window: int) -> float:
    if window <= 0:
        raise ValueError("window doit être strictement positif.")
    if len(values) < window:
        raise ValueError("Pas assez de données pour calculer la moyenne mobile.")
    return sum(values[-window:]) / window


def crossover_signal(
    closes: Sequence[float], short_window: int = 10, long_window: int = 30
) -> Signal:
    """Return BUY/SELL only when a crossover occurred between the last two candles."""
    if short_window <= 0 or long_window <= short_window:
        raise ValueError("Il faut vérifier 0 < short_window < long_window.")
    required = long_window + 1
    if len(closes) < required:
        return Signal.HOLD

    previous = closes[:-1]
    current = closes
    previous_short = moving_average(previous, short_window)
    previous_long = moving_average(previous, long_window)
    current_short = moving_average(current, short_window)
    current_long = moving_average(current, long_window)

    if previous_short <= previous_long and current_short > current_long:
        return Signal.BUY
    if previous_short >= previous_long and current_short < current_long:
        return Signal.SELL
    return Signal.HOLD
