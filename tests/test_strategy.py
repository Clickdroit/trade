import pytest

from tradebot.domain.models import Signal
from tradebot.strategy.moving_average import crossover_signal, moving_average


def test_moving_average():
    assert moving_average([1, 2, 3, 4], 2) == 3.5


def test_moving_average_rejects_insufficient_data():
    with pytest.raises(ValueError):
        moving_average([1, 2], 3)


def test_strategy_waits_without_enough_data():
    assert crossover_signal([1, 2, 3], 2, 4) == Signal.HOLD


def test_strategy_returns_hold_when_no_crossing():
    values = [float(value) for value in range(1, 40)]
    assert crossover_signal(values, 3, 8) == Signal.HOLD
