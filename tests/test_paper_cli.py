"""Tests des commandes CLI ``paper`` (aucun accès réseau)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import FakeMarket, make_candles
from tradebot import cli
from tradebot.storage.sqlite_store import PaperStore

BUY_CLOSES = [100.0, 100.0, 100.0, 100.0, 101.0]


@pytest.fixture(autouse=True)
def _paper_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> FakeMarket:
    """Environnement déterministe + source de marché factice."""
    for name, value in {
        "TRADING_SYMBOL": "BTC/USDT",
        "TRADING_TIMEFRAME": "1h",
        "SHORT_MA": "2",
        "LONG_MA": "3",
        "STARTING_BALANCE": "1000",
        "STOP_LOSS_PCT": "0.03",
        "FEE_RATE": "0.001",
        "SLIPPAGE_PCT": "0",
        "MAX_POSITION_FRACTION": "0.10",
        "MAX_DAILY_LOSS_FRACTION": "0.05",
        "DRY_RUN": "true",
        "LOG_LEVEL": "WARNING",
        "PAPER_DB_PATH": str(tmp_path / "paper.sqlite3"),
    }.items():
        monkeypatch.setenv(name, value)
    market = FakeMarket(make_candles(BUY_CLOSES))
    monkeypatch.setattr(cli, "_build_market", lambda settings: market)
    return market


def _store() -> PaperStore:
    from tradebot.config import Settings

    return PaperStore(Settings.from_env().paper_db_path)


def test_paper_start_once_prints_cycle_and_status(capsys: pytest.CaptureFixture) -> None:
    exit_code = cli.main(["paper", "start", "--once"])

    out = capsys.readouterr().out
    assert exit_code == 0
    # Premier démarrage : seule la dernière bougie clôturée est traitée.
    assert "Bougies traitées : 1" in out
    assert "BUY" in out
    assert "ÉTAT DU PAPER TRADING" in out
    assert "Capital initial" in out
    assert "Position actuelle" in out


def test_paper_status_before_start(capsys: pytest.CaptureFixture) -> None:
    exit_code = cli.main(["paper", "status"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "ÉTAT DU PAPER TRADING" in out
    assert "non démarré" in out
    assert "Transactions             : 0" in out


def test_paper_status_after_cycle(capsys: pytest.CaptureFixture) -> None:
    cli.main(["paper", "start", "--once"])
    capsys.readouterr()

    exit_code = cli.main(["paper", "status"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "BTC/USDT" in out
    assert "Transactions             : 0" in out
    assert "arrêté" in out


def test_paper_history_lists_decisions(capsys: pytest.CaptureFixture) -> None:
    cli.main(["paper", "start", "--once"])
    capsys.readouterr()

    exit_code = cli.main(["paper", "history", "--limit", "5"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "HISTORIQUE DU PAPER TRADING" in out
    assert "Décisions" in out
    assert "action BUY" in out


def test_paper_stop_sets_the_flag(capsys: pytest.CaptureFixture) -> None:
    cli.main(["paper", "start", "--once"])
    capsys.readouterr()

    exit_code = cli.main(["paper", "stop"])

    assert exit_code == 0
    with _store() as store:
        assert store.stop_requested() is True


def test_paper_reset_requires_confirmation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    cli.main(["paper", "start", "--once"])
    capsys.readouterr()
    monkeypatch.setattr("builtins.input", lambda *_: "non")

    exit_code = cli.main(["paper", "reset"])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "annulée" in out
    with _store() as store:
        assert store.load_state() is not None
        assert len(store.decisions()) == 1


def test_paper_reset_with_yes_clears_state(capsys: pytest.CaptureFixture) -> None:
    cli.main(["paper", "start", "--once"])
    capsys.readouterr()

    exit_code = cli.main(["paper", "reset", "--yes"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "réinitialisé" in out
    with _store() as store:
        assert store.load_state() is None
        assert store.trade_count() == 0


def test_paper_without_subcommand_is_refused() -> None:
    with pytest.raises(SystemExit):
        cli.main(["paper"])


def test_paper_reset_handles_closed_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    def _raise(*_: object) -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise)

    exit_code = cli.main(["paper", "reset"])

    assert exit_code == 1
    assert "rien n'a été supprimé" in capsys.readouterr().err
