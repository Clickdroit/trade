"""Command-line entry point: backtester, analysis and paper trading."""

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
from tradebot.exchange.market import CcxtMarketData, MarketDataError, MarketSource
from tradebot.paper.engine import CycleOutcome, PaperTrader, PaperTradingError
from tradebot.paper.report import format_cycle, format_history, format_status
from tradebot.portfolio.virtual_portfolio import PortfolioStateError
from tradebot.risk.manager import RiskLimits
from tradebot.storage.sqlite_store import (
    STATUS_ERROR,
    STATUS_RUNNING,
    PaperStore,
    StorageError,
)


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


def _add_log_level(parser: argparse.ArgumentParser) -> None:
    """Ajoute l'option de niveau de log à un parseur."""
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING"],
        default=None,
        help="Niveau de log (DEBUG, INFO, WARNING).",
    )


def _add_backtest_options(parser: argparse.ArgumentParser) -> None:
    """Ajoute les options communes aux deux formes de backtest."""
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


def _build_parser() -> argparse.ArgumentParser:
    """Construit le parseur d'arguments de la commande ``trade-bot``."""
    parser = argparse.ArgumentParser(
        description="Bot éducatif BTC/USDT — simulation et backtest, aucun ordre réel."
    )
    subparsers = parser.add_subparsers(dest="command")

    backtest = subparsers.add_parser(
        "backtest", help="Backteste la stratégie, sans aucun envoi d'ordre."
    )
    _add_backtest_options(backtest)
    _add_log_level(backtest)

    paper = subparsers.add_parser(
        "paper", help="Paper Trading : portefeuille virtuel et exécution simulée."
    )
    _add_log_level(paper)
    paper_commands = paper.add_subparsers(dest="paper_command", required=True)

    start = paper_commands.add_parser(
        "start", help="Démarre le cycle de Paper Trading (continu par défaut)."
    )
    start.add_argument(
        "--once", action="store_true", help="Exécute un seul cycle puis s'arrête."
    )
    start.add_argument(
        "--poll-seconds",
        dest="poll_seconds",
        type=int,
        default=None,
        help="Délai entre deux cycles (défaut : POLL_SECONDS).",
    )

    paper_commands.add_parser("status", help="Affiche l'état du portefeuille virtuel.")
    paper_commands.add_parser("stop", help="Demande l'arrêt propre d'une exécution continue.")

    history = paper_commands.add_parser(
        "history", help="Affiche les transactions et décisions enregistrées."
    )
    history.add_argument(
        "--limit", type=int, default=20, help="Nombre de lignes affichées (défaut : 20)."
    )

    reset = paper_commands.add_parser(
        "reset", help="Réinitialise le Paper Trading (confirmation obligatoire)."
    )
    reset.add_argument(
        "--yes",
        action="store_true",
        help="Confirme la réinitialisation sans invite interactive.",
    )

    # Formes historiques conservées : --once, --loop, --backtest.
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
    _add_backtest_options(parser)
    _add_log_level(parser)
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


def _build_market(settings: Settings) -> MarketSource:
    """Source de marché utilisée par le Paper Trading (surchargée dans les tests)."""
    return CcxtMarketData(settings)


def _run_paper(args: argparse.Namespace, settings: Settings) -> int:
    """Exécute une sous-commande ``paper``."""
    try:
        store = PaperStore(settings.paper_db_path)
    except (OSError, StorageError) as exc:
        print(f"Erreur : base de données inaccessible : {exc}", file=sys.stderr)
        return 1

    try:
        if args.paper_command == "status":
            return _paper_status(store, settings)
        if args.paper_command == "history":
            return _paper_history(store, max(1, args.limit))
        if args.paper_command == "stop":
            return _paper_stop(store)
        if args.paper_command == "reset":
            return _paper_reset(store, assume_yes=args.yes)
        return _paper_start(
            store,
            settings,
            once=args.once,
            poll_seconds=args.poll_seconds,
        )
    finally:
        store.close()


def _paper_status(store: PaperStore, settings: Settings) -> int:
    """Affiche l'état du portefeuille virtuel, sans accès réseau."""
    try:
        trader = PaperTrader(settings, store, market=None)
    except PaperTradingError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1
    print(format_status(trader.summary()))
    if store.stop_requested():
        print("  (un arrêt a été demandé : l'exécution continue va s'interrompre)")
    return 0


def _paper_history(store: PaperStore, limit: int) -> int:
    """Affiche l'historique des transactions et décisions."""
    print(format_history(store.trades(limit), store.decisions(limit), limit))
    return 0


def _paper_stop(store: PaperStore) -> int:
    """Pose le drapeau d'arrêt lu par l'exécution continue."""
    state = store.load_state()
    if state is None:
        print("Aucune exécution de Paper Trading enregistrée : rien à arrêter.")
        return 0
    store.request_stop()
    if state.status == STATUS_RUNNING:
        print("Arrêt demandé : le bot s'arrêtera à la fin de son cycle courant.")
    else:
        print("Aucune exécution continue active ; le drapeau d'arrêt est posé.")
    return 0


def _paper_reset(store: PaperStore, *, assume_yes: bool) -> int:
    """Réinitialise l'état et l'historique, après confirmation explicite."""
    if not assume_yes:
        try:
            answer = input(
                "Réinitialiser le Paper Trading (portefeuille, positions, transactions, "
                "décisions) ? Taper « oui » pour confirmer : "
            )
        except EOFError:
            print(
                "Confirmation impossible (entrée standard fermée) : rien n'a été supprimé.",
                file=sys.stderr,
            )
            return 1
        if answer.strip().lower() not in {"oui", "o", "yes", "y"}:
            print("Réinitialisation annulée : aucune donnée n'a été supprimée.")
            return 1

    counts = store.reset()
    print("Paper Trading réinitialisé :")
    for table, count in counts.items():
        print(f"  - {table} : {count} ligne(s) supprimée(s)")
    return 0


def _paper_start(
    store: PaperStore,
    settings: Settings,
    *,
    once: bool,
    poll_seconds: int | None,
) -> int:
    """Démarre un cycle unique ou une exécution continue."""
    try:
        trader = PaperTrader(settings, store, _build_market(settings))
    except (PaperTradingError, MarketDataError) as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1

    if once:
        try:
            outcome = trader.run_once()
        except (MarketDataError, PaperTradingError, PortfolioStateError, StorageError) as exc:
            store.set_status(STATUS_ERROR)
            print(f"Erreur : {exc}", file=sys.stderr)
            return 1
        print(format_cycle(outcome))
        print()
        print(format_status(outcome.summary))
        return 0

    def _show(outcome: CycleOutcome) -> None:
        print(format_cycle(outcome))
        print()
        print(format_status(outcome.summary))
        print()

    print("Paper Trading démarré (simulation uniquement). Ctrl+C ou « paper stop » pour arrêter.")
    print()
    try:
        trader.run_forever(poll_seconds=poll_seconds, on_outcome=_show)
    except KeyboardInterrupt:
        print("\nArrêt propre du Paper Trading. État sauvegardé.")
        return 0
    except (PortfolioStateError, StorageError, PaperTradingError, ValueError) as exc:
        print(f"Erreur bloquante, bot arrêté : {exc}", file=sys.stderr)
        return 1
    print("Paper Trading arrêté (état sauvegardé).")
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
    setup_logging(getattr(args, "log_level", None) or settings.log_level)

    if args.command == "paper":
        return _run_paper(args, settings)
    if args.command == "backtest":
        return _run_backtest(args, settings)

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

    parser.error("Aucune action demandée : utiliser --once, --loop, --backtest ou paper.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
