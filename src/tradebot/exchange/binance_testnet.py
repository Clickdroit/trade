"""Binance Spot Testnet — données publiques uniquement.

Ce module ne contient **aucun** endpoint d'ordre ni de retrait. Le client est
toujours créé en sandbox et sans credentials : les endpoints publics de données
de marché ne demandent aucune authentification.
"""

from __future__ import annotations

import ccxt

from tradebot.config import Settings

#: Timeout par défaut d'une requête HTTP (millisecondes).
DEFAULT_TIMEOUT_MS = 10_000


def create_testnet_client(settings: Settings | None = None) -> ccxt.binance:
    """Crée un client Binance sandbox, public et rate-limité.

    Args:
        settings: Configuration fournissant le timeout ; valeurs par défaut sinon.

    Returns:
        Un client CCXT en mode sandbox, sans clé API.
    """
    timeout = DEFAULT_TIMEOUT_MS if settings is None else settings.request_timeout_ms
    client = ccxt.binance(
        {
            "enableRateLimit": True,
            "timeout": timeout,
            "options": {"defaultType": "spot"},
        }
    )
    client.set_sandbox_mode(True)
    return client
