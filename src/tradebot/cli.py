"""Command-line entry point."""

import argparse

from tradebot.app import run_once
from tradebot.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Bot éducatif BTC/USDT — Binance Testnet.")
    parser.add_argument("--once", action="store_true", help="Récupère les données et calcule un signal.")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.once:
        run_once(settings)
    else:
        parser.error("Pour le moment, seule l'option --once est disponible.")


if __name__ == "__main__":
    main()
