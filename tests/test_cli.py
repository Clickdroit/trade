"""Tests de la commande ``trade-bot --backtest`` (aucun accès réseau)."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from tests.helpers import DEFAULT_START_MS, make_candles
from tradebot import cli
from tradebot.backtesting.data_loader import DataLoadError, save_to_csv


@pytest.fixture(autouse=True)
def _deterministic_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fige les paramètres lus depuis l'environnement (et le .env local)."""
    for name, value in {
        "TRADING_SYMBOL": "BTC/USDT",
        "TRADING_TIMEFRAME": "1h",
        "SHORT_MA": "10",
        "LONG_MA": "30",
        "STARTING_BALANCE": "1000",
        "STOP_LOSS_PCT": "0.03",
        "FEE_RATE": "0.001",
        "SLIPPAGE_PCT": "0.0005",
        "LOG_LEVEL": "WARNING",
    }.items():
        monkeypatch.setenv(name, value)


def _sine_closes(count: int = 120) -> list[float]:
    return [100 + 5 * math.sin(index / 5) for index in range(count)]


def _write_csv(path: Path, closes: list[float], **kwargs: object) -> Path:
    save_to_csv(make_candles(closes, **kwargs), path)  # type: ignore[arg-type]
    return path


def test_backtest_from_csv_prints_report(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    csv_path = _write_csv(tmp_path / "btc.csv", _sine_closes())

    exit_code = cli.main(["--backtest", "--csv", str(csv_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "RAPPORT DE BACKTEST" in captured.out
    assert "Bougies : 120" in captured.out
    assert "BTC/USDT" in captured.out
    assert captured.err == ""


def test_backtest_honours_symbol_and_timeframe(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    csv_path = _write_csv(tmp_path / "btc.csv", _sine_closes(60))

    exit_code = cli.main(
        ["--backtest", "--csv", str(csv_path), "--symbol", "ETH/USDT", "--timeframe", "4h"]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "ETH/USDT" in captured.out
    assert "4h" in captured.out


def test_backtest_filters_period(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    # 72 bougies horaires = 3 jours UTC à partir du 2019-01-01.
    csv_path = _write_csv(tmp_path / "btc.csv", _sine_closes(72))

    exit_code = cli.main(
        ["--backtest", "--csv", str(csv_path), "--start", "2019-01-02", "--end", "2019-01-03"]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Bougies : 48" in captured.out


def test_backtest_rejects_inverted_period(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    csv_path = _write_csv(tmp_path / "btc.csv", _sine_closes(60))

    exit_code = cli.main(
        ["--backtest", "--csv", str(csv_path), "--start", "2019-01-03", "--end", "2019-01-02"]
    )

    assert exit_code == 1
    assert "--start doit précéder --end" in capsys.readouterr().err


def test_missing_csv_is_reported(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    exit_code = cli.main(["--backtest", "--csv", str(tmp_path / "absent.csv")])

    assert exit_code == 1
    assert "introuvable" in capsys.readouterr().err


def test_empty_csv_is_reported(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("timestamp,open,high,low,close,volume\n", encoding="utf-8")

    exit_code = cli.main(["--backtest", "--csv", str(csv_path)])

    assert exit_code == 1
    assert "aucune bougie" in capsys.readouterr().err


def test_malformed_csv_is_reported(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("ts,o,h,l,c,v\n1,2,3,4,5,6\n", encoding="utf-8")

    exit_code = cli.main(["--backtest", "--csv", str(csv_path)])

    assert exit_code == 1
    assert "Colonnes manquantes" in capsys.readouterr().err


def test_unsorted_csv_is_reported(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    csv_path = tmp_path / "unsorted.csv"
    rows = [
        "timestamp,open,high,low,close,volume",
        "2000,1,1,1,1,1",
        "1000,1,1,1,1,1",
    ]
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    exit_code = cli.main(["--backtest", "--csv", str(csv_path)])

    assert exit_code == 1
    assert "chronologiques" in capsys.readouterr().err


def test_insufficient_data_is_reported(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    csv_path = _write_csv(tmp_path / "short.csv", [100.0] * 5)

    exit_code = cli.main(["--backtest", "--csv", str(csv_path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "insuffisantes" in captured.err


def test_exchange_download_errors_are_handled(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    def _fail(*args: object, **kwargs: object) -> list:
        raise DataLoadError("Binance indisponible")

    monkeypatch.setattr(cli, "load_from_exchange", _fail)

    exit_code = cli.main(["--backtest", "--days", "10"])

    assert exit_code == 1
    assert "Binance indisponible" in capsys.readouterr().err


def test_save_csv_persists_downloaded_candles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    candles = make_candles(_sine_closes(60))
    monkeypatch.setattr(cli, "load_from_exchange", lambda *args, **kwargs: candles)
    target = tmp_path / "cache" / "btc_usdt_1h.csv"

    exit_code = cli.main(["--backtest", "--days", "10", "--save-csv", str(target)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert target.exists()
    assert "RAPPORT DE BACKTEST" in captured.out


def test_invalid_configuration_is_reported(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    def _broken_settings(cls: object) -> None:
        raise ValueError("SHORT_MA invalide")

    monkeypatch.setattr(cli.Settings, "from_env", classmethod(_broken_settings))

    exit_code = cli.main(["--backtest"])

    assert exit_code == 1
    assert "Configuration invalide" in capsys.readouterr().err


def test_backtest_options_require_backtest_mode() -> None:
    with pytest.raises(SystemExit):
        cli.main(["--once", "--csv", "data/btc.csv"])


def test_days_must_be_positive(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(cli, "load_from_exchange", lambda *args, **kwargs: [])

    exit_code = cli.main(["--backtest", "--days", "0"])

    assert exit_code == 1
    assert "--days" in capsys.readouterr().err


def test_filtered_period_start_default() -> None:
    candles = make_candles([100.0] * 72)
    filtered = cli._filter_period(candles, None, None)
    assert filtered == candles

    import datetime

    start = datetime.datetime.fromtimestamp(DEFAULT_START_MS / 1000, tz=datetime.UTC).date()
    one_day = cli._filter_period(candles, start, start)
    assert len(one_day) == 24
