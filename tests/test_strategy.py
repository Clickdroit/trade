import pytest

from tradebot.domain.models import Signal
from tradebot.strategy.moving_average import crossover_signal, moving_average


def test_moving_average() -> None:
    assert moving_average([1, 2, 3, 4], 2) == 3.5


def test_moving_average_rejects_insufficient_data() -> None:
    with pytest.raises(ValueError):
        moving_average([1, 2], 3)


def test_moving_average_rejects_invalid_window() -> None:
    with pytest.raises(ValueError):
        moving_average([1, 2, 3], 0)


def test_strategy_waits_without_enough_data() -> None:
    assert crossover_signal([1, 2, 3], 2, 4) == Signal.HOLD


def test_strategy_returns_hold_when_no_crossing() -> None:
    values = [float(value) for value in range(1, 40)]
    assert crossover_signal(values, 3, 8) == Signal.HOLD


def test_strategy_detects_bullish_crossover() -> None:
    # MM2 passe de 10,00 à 10,50 au-dessus de la MM3 (10,00 → 10,33).
    assert crossover_signal([10, 10, 10, 10, 11], 2, 3) == Signal.BUY


def test_strategy_detects_bearish_crossover() -> None:
    assert crossover_signal([10, 10, 10, 10, 9], 2, 3) == Signal.SELL


def test_strategy_does_not_repeat_signal_without_new_crossing() -> None:
    # Le croisement a eu lieu avant ; l'état reste haussier mais ce n'est pas un signal.
    assert crossover_signal([10, 10, 10, 10, 11, 12], 2, 3) == Signal.HOLD


@pytest.mark.parametrize(
    ("short_window", "long_window"),
    [(0, 3), (3, 3), (4, 3), (-1, 3)],
)
def test_strategy_rejects_invalid_windows(short_window: int, long_window: int) -> None:
    with pytest.raises(ValueError):
        crossover_signal([1, 2, 3, 4, 5], short_window, long_window)
