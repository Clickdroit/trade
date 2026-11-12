"""Accès aux données de marché publiques : aucun ordre, aucune clé API.

Seules les bougies **clôturées** sont exposées. Une bougie en cours de formation
n'a pas de clôture définitive : l'utiliser reviendrait à connaître son prix final
avant la fin de la bougie et pourrait déclencher une transaction fictive.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Protocol

import ccxt

from tradebot.config import Settings
from tradebot.domain.models import Candle, timeframe_ms, validate_candles
from tradebot.exchange.binance_testnet import create_testnet_client
from tradebot.safety import assert_public_market_client

logger = logging.getLogger(__name__)


class MarketDataError(RuntimeError):
    """Données de marché indisponibles ou inutilisables."""


class MarketSource(Protocol):
    """Source de bougies clôturées (injectable dans les tests)."""

    def fetch_closed_candles(self, limit: int) -> list[Candle]:
        """Renvoie au plus ``limit`` bougies clôturées, chronologiques."""
        ...


def parse_ohlcv(rows: list[list]) -> list[Candle]:
    """Convertit des lignes OHLCV brutes en objets :class:`Candle`.

    Raises:
        MarketDataError: Ligne incomplète ou non numérique.
    """
    candles: list[Candle] = []
    for row in rows:
        if len(row) < 6:
            raise MarketDataError(f"Bougie incomplète : {row!r}")
        try:
            candles.append(
                Candle(
                    timestamp=int(row[0]),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
            )
        except (TypeError, ValueError) as exc:
            raise MarketDataError(f"Bougie illisible : {row!r}") from exc
    return candles


class CcxtMarketData:
    """Client CCXT restreint aux données publiques du Testnet Binance.

    Le client est toujours créé en mode sandbox, sans clé API (vérifié par
    :func:`tradebot.safety.assert_public_market_client`). Aucune méthode d'ordre
    n'est appelée par ce module.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        client_factory: Callable[[Settings], object] | None = None,
        clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._clock = clock
        self._sleeper = sleeper
        self._client = (client_factory or create_testnet_client)(settings)
        assert_public_market_client(self._client)

    def fetch_closed_candles(self, limit: int) -> list[Candle]:
        """Récupère les dernières bougies clôturées.

        Args:
            limit: Nombre maximum de bougies demandées.

        Returns:
            Bougies validées, strictement chronologiques, clôturées.

        Raises:
            ValueError: ``limit`` non positif.
            MarketDataError: Réponse vide, invalide, périmée, ou erreur réseau
                après épuisement des tentatives.
        """
        if limit <= 0:
            raise ValueError("limit doit être strictement positif.")

        rows = self._fetch(limit)
        if not rows:
            raise MarketDataError(f"Aucune bougie reçue pour {self._settings.symbol}.")

        candles = parse_ohlcv(rows)
        try:
            validate_candles(candles)
        except ValueError as exc:
            raise MarketDataError(f"Données de marché invalides : {exc}") from exc

        closed = self._drop_unfinished(candles)
        if not closed:
            raise MarketDataError(
                f"Aucune bougie clôturée pour {self._settings.symbol} "
                f"{self._settings.timeframe}."
            )
        return closed[-limit:]

    def _drop_unfinished(self, candles: list[Candle]) -> list[Candle]:
        """Exclut la bougie en cours de formation (période non terminée)."""
        duration = timeframe_ms(self._settings.timeframe)
        now_ms = int(self._clock() * 1000)
        return [candle for candle in candles if candle.timestamp + duration <= now_ms]

    def _fetch(self, limit: int) -> list[list]:
        """Appelle l'endpoint public avec retries et délais bornés."""
        attempts = max(1, self._settings.max_retries)
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return self._client.fetch_ohlcv(  # type: ignore[attr-defined]
                    self._settings.symbol,
                    timeframe=self._settings.timeframe,
                    limit=limit,
                )
            except (ccxt.BaseError, OSError, TimeoutError) as exc:
                last_error = exc
                logger.warning(
                    "Lecture OHLCV échouée (tentative %d/%d) : %s", attempt, attempts, exc
                )
                if attempt < attempts:
                    self._sleeper(self._settings.retry_backoff_seconds * attempt)
        raise MarketDataError(
            f"Lecture OHLCV impossible pour {self._settings.symbol} : {last_error}"
        )
