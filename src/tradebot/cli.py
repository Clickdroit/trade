"""Command-line entry point for the educational trading bot and the backtester."""

from __future__ import annotations

import argparse
import datetime
import sys
import time
from pathlib import Path

from tradebot.app import run_once
from tradebot.backtesting.data_loader import (
    DataLoadError,
    load_from_csv,
    load_from_exchange,
    save_to_csv,
)
from tradebot.backtesting.engine import run_backtest
from tradebot.backtesting.metrics import format_report
from tradebot.config import Settings, setup_logging
from tradebot.domain.models import Candle
from tradebot.risk.manager import RiskLimits


def _parse_date(value: str) -> datetime.date:
    """Convertit une date ISO (AAAA-MM-JJ) en objet date pour argparse."""
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Date invalide : {value!r} (format attendu AAAA-MM-JJ)."
        ) from exc


def _date_to_ms(day: datetime.date) -> int:
    """Convertit une date UTC en timestamp millisecondes à minuit."""
    moment = datetime.datetime.combine(day, datetime.time.min, tzinfo=datetime.UTC)
    return int(moment.timestamp() * 1000)


def _format_timestamp(timestamp_ms: int) -> str:
    """Formate un timestamp millisecondes en date UTC lisible."""
    moment = datetime.datetime.fromtimestamp(timestamp_ms / 1000, tz=datetime.UTC)
    return moment.strftime("%Y-%m-%d %H:%M")


def _build_parser() -> argparse.ArgumentParser:
    """Construit le parseur d'arguments de la commande ``trade-bot``."""
    parser = argparse.ArgumentParser(
        description="Bot éducatif BTC/USDT — simulation et backtest, aucun ordre réel."
    )
    parser.add_argument(
        "--once", action="store_true", help="Récupère les données et calcule un signal."
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Exécute run_once en boucle avec un délai entre chaque itération.",
    )
    parser.add_argument(
        "--backtest",
        action="store_true",
        help="Lance un backtest historique, sans aucun envoi d'ordre.",
    )
    parser.add_argument(
        "--symbol",
        default=None,
        help=(
            "Paire testée (défaut : TRADING_SYMBOL, ex. BTC/USDT). "
            "En mode CSV, sert uniquement de libellé d'affichage."
        ),
    )
    parser.add_argument(
        "--timeframe",
        default=None,
        help=(
            "Timeframe des bougies (1m, 5m, 15m, 1h, 4h, 1d ; défaut : TRADING_TIMEFRAME). "
            "En mode CSV, libellé seulement : aucune conversion de bougies."
        ),
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Fichier CSV local (timestamp,open,high,low,close,volume en ms).",
    )
    parser.add_argument(
        "--save-csv",
        dest="save_csv",
        type=Path,
        default=None,
        help="Enregistre les données téléchargées dans un CSV réutilisable.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help=(
            "Profondeur historique téléchargée, en jours "
            "(téléchargement CCXT uniquement ; défaut : 30)."
        ),
    )
    parser.add_argument(
        "--start",
        type=_parse_date,
        default=None,
        metavar="AAAA-MM-JJ",
        help="Début de la période testée (inclus).",
    )
    parser.add_argument(
        "--end",
        type=_parse_date,
        default=None,
        metavar="AAAA-MM-JJ",
        help="Fin de la période testée (incluse).",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING"],
        default=None,
        help="Niveau de log (DEBUG, INFO, WARNING).",
    )
    return parser


def _filter_period(
    candles: list[Candle], start: datetime.date | None, end: datetime.date | None
) -> list[Candle]:
    """Restreint les bougies à une période UTC inclusive."""
    if start is None and end is None:
        return candles

    start_ms = _date_to_ms(start) if start is not None else None
    end_ms = _date_to_ms(end + datetime.timedelta(days=1)) if end is not None else None
    return [
        candle
        for candle in candles
        if (start_ms is None or candle.timestamp >= start_ms)
        and (end_ms is None or candle.timestamp < end_ms)
    ]


def _run_backtest(args: argparse.Namespace, settings: Settings) -> int:
    """Charge les données, exécute le backtest et affiche le rapport."""
    symbol = args.symbol or settings.symbol
    timeframe = args.timeframe or settings.timeframe

    if args.start is not None and args.end is not None and args.start > args.end:
        print("Erreur : --start doit précéder --end.", file=sys.stderr)
        return 1

    try:
        if args.csv is not None:
            if args.save_csv is not None:
                raise DataLoadError("--save-csv ne s'applique qu'aux données téléchargées.")
            candles = load_from_csv(args.csv)
            source = f"CSV local {args.csv}"
        else:
            if args.days is not None and args.days <= 0:
                raise DataLoadError("--days doit être strictement positif.")
            if args.start is not None:
                today = datetime.datetime.now(tz=datetime.UTC).date()
                since_days = max((today - args.start).days + 1, 1)
            else:
                since_days = args.days or 30
            candles = load_from_exchange(symbol, timeframe, since_days)
            source = f"CCXT Binance Testnet ({since_days} jours)"
            if args.save_csv is not None:
                save_to_csv(candles, args.save_csv)

        candles = _filter_period(candles, args.start, args.end)
        result = run_backtest(
            candles,
            short_window=settings.short_window,
            long_window=settings.long_window,
            starting_balance=settings.starting_balance,
            fee_rate=settings.fee_rate,
            stop_loss_pct=settings.stop_loss_fraction,
            slippage_pct=settings.slippage_pct,
            risk_limits=RiskLimits(
                max_position_fraction=settings.max_position_fraction,
                max_daily_loss_fraction=settings.max_daily_loss_fraction,
            ),
        )
    except (DataLoadError, ValueError, OSError) as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1

    print(f"Source    : {source}")
    print(f"Paire     : {symbol} | Timeframe : {timeframe} | Bougies : {len(candles)}")
    print(
        f"Période   : {_format_timestamp(candles[0].timestamp)} -> "
        f"{_format_timestamp(candles[-1].timestamp)} UTC"
    )
    print()
    print(format_report(result))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Point d'entrée CLI ; renvoie un code de sortie (0 succès, 1 erreur)."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        print(f"Configuration invalide : {exc}", file=sys.stderr)
        return 1
    setup_logging(args.log_level or settings.log_level)

    backtest_options = [
        args.symbol,
        args.timeframe,
        args.csv,
        args.save_csv,
        args.days,
        args.start,
        args.end,
    ]
    if not args.backtest and any(option is not None for option in backtest_options):
        parser.error("Les options --symbol/--timeframe/--csv/... nécessitent --backtest.")

    selected = sum((args.once, args.loop, args.backtest))
    if selected > 1:
        parser.error("Choisir une seule action : --once, --loop ou --backtest.")

    if args.backtest:
        return _run_backtest(args, settings)

    if args.once:
        run_once(settings)
        return 0

    if args.loop:
        try:
            while True:
                run_once(settings)
                time.sleep(settings.poll_seconds)
        except KeyboardInterrupt:
            print("\nArrêt propre du bot. À bientôt !")
            return 0

    parser.error("Aucune action demandée : utiliser --once, --loop ou --backtest.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
