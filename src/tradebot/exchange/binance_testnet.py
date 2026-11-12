"""Binance Spot Testnet market-data adapter.

This adapter is deliberately limited to public market data in the starter version.
Do not add live endpoints or withdrawal permissions.
"""

import ccxt

from tradebot.config import Settings


def create_testnet_client(settings: Settings) -> ccxt.binance:
    client = ccxt.binance(
        {
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }
    )
    client.set_sandbox_mode(True)
    return client


def fetch_ohlcv(settings: Settings, limit: int = 100) -> list[list[float]]:
    client = create_testnet_client(settings)
    return client.fetch_ohlcv(settings.symbol, timeframe=settings.timeframe, limit=limit)
