"""Centralised, validated application settings."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv


def setup_logging(level: str = "INFO") -> None:
    """Configure le module logging avec un format lisible."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    )


@dataclass(frozen=True)
class Settings:
    """Paramètres de l'application, identiques pour le live simulé et le backtest."""

    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    short_window: int = 10
    long_window: int = 30
    starting_balance: float = 1_000.0
    max_position_fraction: float = 0.10
    max_daily_loss_fraction: float = 0.05
    stop_loss_fraction: float = 0.03
    fee_rate: float = 0.001
    slippage_pct: float = 0.0005
    poll_seconds: int = 60
    dry_run: bool = True
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> Settings:
        """Charge et valide la configuration depuis l'environnement et ``.env``."""
        load_dotenv()
        settings = cls(
            symbol=os.getenv("TRADING_SYMBOL", "BTC/USDT"),
            timeframe=os.getenv("TRADING_TIMEFRAME", "1h"),
            short_window=int(os.getenv("SHORT_MA", "10")),
            long_window=int(os.getenv("LONG_MA", "30")),
            starting_balance=float(os.getenv("STARTING_BALANCE", "1000")),
            stop_loss_fraction=float(os.getenv("STOP_LOSS_PCT", "0.03")),
            fee_rate=float(os.getenv("FEE_RATE", "0.001")),
            slippage_pct=float(os.getenv("SLIPPAGE_PCT", "0.0005")),
            dry_run=os.getenv("DRY_RUN", "true").lower() != "false",
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )
        if settings.short_window <= 0 or settings.long_window <= settings.short_window:
            raise ValueError("Les fenêtres doivent vérifier 0 < SHORT_MA < LONG_MA.")
        if settings.starting_balance <= 0:
            raise ValueError("STARTING_BALANCE doit être strictement positif.")
        if not 0 < settings.max_position_fraction <= 1:
            raise ValueError("La taille maximale de position doit être comprise entre 0 et 1.")
        if not 0 < settings.max_daily_loss_fraction < 1:
            raise ValueError("La limite de perte journalière doit être comprise entre 0 et 1.")
        if not 0 < settings.stop_loss_fraction < 1:
            raise ValueError("STOP_LOSS_PCT doit être compris entre 0 et 1.")
        if not 0 <= settings.fee_rate < 1:
            raise ValueError("FEE_RATE doit être compris entre 0 et 1.")
        if not 0 <= settings.slippage_pct < 1:
            raise ValueError("SLIPPAGE_PCT doit être compris entre 0 et 1.")
        return settings
