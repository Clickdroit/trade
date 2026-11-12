"""Command-line entry point."""

import argparse
import time

from tradebot.app import run_once
from tradebot.config import Settings, setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Bot éducatif BTC/USDT — Binance Testnet.")
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
        help="Lance un back-test historique.",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING"],
        default=None,
        help="Niveau de log (DEBUG, INFO, WARNING).",
    )
    args = parser.parse_args()
    settings = Settings.from_env()

    # Appliquer le niveau de log CLI s'il est fourni
    log_level = args.log_level or settings.log_level
    setup_logging(log_level)

    if args.backtest:
        print("Not yet implemented")
        return

    if args.once:
        run_once(settings)
    elif args.loop:
        try:
            while True:
                run_once(settings)
                time.sleep(settings.poll_seconds)
        except KeyboardInterrupt:
            print("\nArrêt propre du bot. À bientôt !")
    else:
        parser.error("Pour le moment, seules les options --once, --loop et --backtest sont disponibles.")


if __name__ == "__main__":
    main()
