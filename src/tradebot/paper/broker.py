"""Exécution simulée du Paper Trading.

Ce broker ne possède aucun client d'exchange : il ne peut rien envoyer. Il
applique uniquement des exécutions simulées au :class:`VirtualPortfolio`.

Prix d'exécution
================
* Achat : ``prix de référence * (1 + slippage)`` — toujours plus cher.
* Vente : ``prix de référence * (1 - slippage)`` — toujours moins cher.
* Stop-loss : ``min(ouverture, niveau de stop)`` puis slippage défavorable.
  Si la bougie ouvre déjà sous le stop (gap), le seul prix réellement disponible
  est l'ouverture : on ne suppose jamais une exécution au niveau du stop.
* Les frais sont prélevés sur le notionnel, à l'achat **et** à la vente.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from tradebot.domain.models import Candle
from tradebot.portfolio.virtual_portfolio import ClosedTrade, VirtualPortfolio


@dataclass(frozen=True)
class Fill:
    """Exécution d'achat simulée."""

    side: str
    symbol: str
    price: float
    quantity: float
    notional: float
    fee: float
    timestamp: int
    reason: str


def _require_positive(value: float, label: str) -> float:
    """Valide un prix strictement positif et fini."""
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{label} doit être un nombre fini strictement positif.")
    return float(value)


class SimulatedBroker:
    """Passerelle d'exécution virtuelle : portefeuille en mémoire uniquement."""

    def __init__(self, portfolio: VirtualPortfolio, slippage_pct: float = 0.0005) -> None:
        """Initialise le broker simulé.

        Args:
            portfolio: Portefeuille virtuel à mettre à jour.
            slippage_pct: Slippage défavorable appliqué à chaque exécution.

        Raises:
            ValueError: Slippage hors bornes.
        """
        if not math.isfinite(slippage_pct) or not 0 <= slippage_pct < 1:
            raise ValueError("slippage_pct doit être compris dans [0, 1[.")
        self._portfolio = portfolio
        self._slippage_pct = float(slippage_pct)

    @property
    def portfolio(self) -> VirtualPortfolio:
        """Portefeuille piloté par ce broker."""
        return self._portfolio

    @property
    def slippage_pct(self) -> float:
        """Slippage appliqué aux exécutions."""
        return self._slippage_pct

    def buy_price(self, reference_price: float) -> float:
        """Prix d'achat simulé, slippage défavorable inclus."""
        return _require_positive(reference_price, "reference_price") * (1 + self._slippage_pct)

    def sell_price(self, reference_price: float) -> float:
        """Prix de vente simulé, slippage défavorable inclus."""
        return _require_positive(reference_price, "reference_price") * (1 - self._slippage_pct)

    def stop_fill_price(self, candle: Candle, stop_level: float) -> float | None:
        """Prix d'exécution d'un stop-loss sur la bougie, ou ``None`` si non atteint.

        Args:
            candle: Bougie évaluée.
            stop_level: Niveau de déclenchement (prix d'entrée moins le stop).

        Returns:
            Prix d'exécution avec slippage, ou ``None`` si le plus bas de la
            bougie reste au-dessus du stop.
        """
        level = _require_positive(stop_level, "stop_level")
        if candle.low > level:
            return None
        reference = candle.open if candle.open <= level else level
        return reference * (1 - self._slippage_pct)

    def buy(
        self,
        symbol: str,
        reference_price: float,
        quantity: float,
        timestamp: int,
        reason: str,
    ) -> Fill:
        """Ouvre une position simulée au prix de référence dégradé par le slippage.

        Raises:
            ValueError: Quantité, prix ou motif invalides, position déjà ouverte,
                ou solde insuffisant.
        """
        if not math.isfinite(quantity) or quantity <= 0:
            raise ValueError("quantity doit être un nombre fini strictement positif.")
        if not reason:
            raise ValueError("Le motif d'exécution est obligatoire.")
        price = self.buy_price(reference_price)
        position = self._portfolio.open_position(symbol, price, quantity, timestamp)
        notional = price * position.quantity
        return Fill(
            side="BUY",
            symbol=symbol,
            price=price,
            quantity=position.quantity,
            notional=notional,
            fee=position.entry_fee,
            timestamp=int(timestamp),
            reason=reason,
        )

    def sell(self, reference_price: float, timestamp: int, reason: str) -> ClosedTrade:
        """Ferme la position simulée au prix de référence dégradé par le slippage."""
        return self.sell_at(self.sell_price(reference_price), timestamp, reason)

    def sell_at(self, fill_price: float, timestamp: int, reason: str) -> ClosedTrade:
        """Ferme la position à un prix d'exécution déjà calculé (stop-loss)."""
        return self._portfolio.close_position(fill_price, timestamp, reason)
