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
    """Return BUY/SELL only when a crossover occurred between the last two candles.

    La comparaison porte sur les deux dernières clôtures : la moyenne précédente
    est calculée sur ``closes[:-1]`` et la moyenne courante sur ``closes``. Un
    signal n'est émis que si la position relative des deux moyennes s'inverse,
    pas si elle est simplement du même côté.

    Seules les ``long_window + 1`` dernières valeurs sont utilisées, ce qui
    garde un coût constant par appel dans le backtest.
    """
    if short_window <= 0 or long_window <= short_window:
        raise ValueError("Il faut vérifier 0 < short_window < long_window.")
    required = long_window + 1
    if len(closes) < required:
        return Signal.HOLD

    window = list(closes[-required:])
    previous = window[:-1]
    current = window[1:]
    previous_short = sum(previous[-short_window:]) / short_window
    previous_long = sum(previous) / long_window
    current_short = sum(current[-short_window:]) / short_window
    current_long = sum(current) / long_window

    if previous_short <= previous_long and current_short > current_long:
        return Signal.BUY
    if previous_short >= previous_long and current_short < current_long:
        return Signal.SELL
    return Signal.HOLD
