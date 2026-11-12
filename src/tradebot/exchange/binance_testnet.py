"""Binance Spot Testnet market-data adapter.

This adapter is deliberately limited to public market data in the starter version.
Do not add live endpoints or withdrawal permissions.
"""

import logging

import ccxt

from tradebot.config import Settings


def create_testnet_client(settings: Settings) -> ccxt.binance:
    """Crée un client Binance en mode sandbox avec le rate-limit activé."""
    client = ccxt.binance(
        {
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }
    )
    client.set_sandbox_mode(True)
    return client


def fetch_ohlcv(
    settings: Settings,
    limit: int = 100,
    logger: logging.Logger | None = None,
) -> list[list]:
    """Récupère les données OHLCV depuis le Testnet Binance.

    Args:
        settings: Configuration de l'application.
        limit: Nombre de bougies à récupérer.
        logger: Logger optionnel pour tracer les erreurs réseau.

    Returns:
        Liste de bougies au format [timestamp, open, high, low, close, volume].
    """
    _log = logger or logging.getLogger(__name__)
    client = create_testnet_client(settings)
    try:
        return client.fetch_ohlcv(settings.symbol, timeframe=settings.timeframe, limit=limit)
    except ccxt.NetworkError:
        _log.error("Erreur réseau lors de la récupération OHLCV pour %s.", settings.symbol)
        raise
    except ccxt.ExchangeNotAvailable:
        _log.error("Exchange indisponible lors de la récupération OHLCV pour %s.", settings.symbol)
        raise
