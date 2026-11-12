"""Centralised, validated application settings."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from tradebot.domain.models import TIMEFRAME_MS
from tradebot.safety import LiveTradingForbiddenError, assert_no_real_funds, assert_paper_mode


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
    execution_mode: str = "paper"
    paper_db_path: Path = Path("data/paper_state.sqlite3")
    close_on_daily_loss: bool = False
    catchup_max_candles: int = 200
    request_timeout_ms: int = 10_000
    max_retries: int = 3
    retry_backoff_seconds: float = 2.0

    @classmethod
    def from_env(cls) -> Settings:
        """Charge et valide la configuration depuis l'environnement et ``.env``.

        Raises:
            ValueError: Configuration invalide, ou tentative d'exécution réelle
                (``DRY_RUN=false`` ou ``EXECUTION_MODE`` autre que ``paper``).
        """
        load_dotenv()
        settings = cls(
            symbol=os.getenv("TRADING_SYMBOL", "BTC/USDT"),
            timeframe=os.getenv("TRADING_TIMEFRAME", "1h"),
            short_window=int(os.getenv("SHORT_MA", "10")),
            long_window=int(os.getenv("LONG_MA", "30")),
            starting_balance=float(os.getenv("STARTING_BALANCE", "1000")),
            max_position_fraction=float(os.getenv("MAX_POSITION_FRACTION", "0.10")),
            max_daily_loss_fraction=float(os.getenv("MAX_DAILY_LOSS_FRACTION", "0.05")),
            stop_loss_fraction=float(os.getenv("STOP_LOSS_PCT", "0.03")),
            fee_rate=float(os.getenv("FEE_RATE", "0.001")),
            slippage_pct=float(os.getenv("SLIPPAGE_PCT", "0.0005")),
            poll_seconds=int(os.getenv("POLL_SECONDS", "60")),
            dry_run=os.getenv("DRY_RUN", "true").lower() != "false",
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            execution_mode=os.getenv("EXECUTION_MODE", "paper"),
            paper_db_path=Path(os.getenv("PAPER_DB_PATH", "data/paper_state.sqlite3")),
            close_on_daily_loss=os.getenv("CLOSE_POSITION_ON_DAILY_LOSS", "false").lower()
            == "true",
            catchup_max_candles=int(os.getenv("CATCHUP_MAX_CANDLES", "200")),
            request_timeout_ms=int(os.getenv("REQUEST_TIMEOUT_MS", "10000")),
            max_retries=int(os.getenv("MAX_RETRIES", "3")),
            retry_backoff_seconds=float(os.getenv("RETRY_BACKOFF_SECONDS", "2")),
        )
        _validate(settings)
        return settings


def _validate(settings: Settings) -> None:
    """Valide les paramètres ; refuse tout ce qui sortirait de la simulation.

    Raises:
        ValueError: Paramètre hors bornes ou mode d'exécution non supporté.
    """
    try:
        assert_paper_mode(settings.execution_mode)
        assert_no_real_funds(settings.dry_run)
    except LiveTradingForbiddenError as exc:
        raise ValueError(str(exc)) from exc

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
    if settings.timeframe not in TIMEFRAME_MS:
        choices = ", ".join(sorted(TIMEFRAME_MS))
        raise ValueError(
            f"TRADING_TIMEFRAME non supporté : {settings.timeframe!r}. Choix : {choices}."
        )
    if settings.poll_seconds <= 0:
        raise ValueError("POLL_SECONDS doit être strictement positif.")
    if settings.catchup_max_candles <= 0:
        raise ValueError("CATCHUP_MAX_CANDLES doit être strictement positif.")
    if settings.request_timeout_ms <= 0:
        raise ValueError("REQUEST_TIMEOUT_MS doit être strictement positif.")
    if settings.max_retries < 1:
        raise ValueError("MAX_RETRIES doit être au moins égal à 1.")
    if settings.retry_backoff_seconds < 0:
        raise ValueError("RETRY_BACKOFF_SECONDS doit être positif ou nul.")
