"""Garde-fous de risque : dimensionnement, perte journalière et autorisation d'entrée."""

from __future__ import annotations

import math
from dataclasses import dataclass

#: Notionnel minimal d'une entrée : en dessous, les frais rendent la position absurde.
MIN_ENTRY_NOTIONAL = 1.0


@dataclass(frozen=True)
class RiskLimits:
    """Limites conservatrices appliquées par le Paper Trading et le backtest.

    ``max_position_fraction`` est la part maximale de l'equity engagée sur une
    position (0.10 = 10 %). ``max_daily_loss_fraction`` est la perte maximale
    tolérée sur une journée UTC, mesurée sur l'equity (0.05 = 5 %).
    """

    max_position_fraction: float = 0.10
    max_daily_loss_fraction: float = 0.05


@dataclass(frozen=True)
class EntryAssessment:
    """Décision de risque pour une entrée : autorisée ou non, avec motif."""

    allowed: bool
    reason: str
    quantity: float = 0.0


def position_size(balance: float, price: float, limits: RiskLimits) -> float:
    """Quantité à acheter pour respecter la fraction maximale de capital.

    Args:
        balance: Capital disponible en devise de cotation.
        price: Prix d'exécution (slippage inclus).
        limits: Limites de risque.

    Returns:
        Quantité (en actif) dont le notionnel vaut au plus la fraction permise.
        Les frais ne sont pas inclus : l'appelant doit vérifier la solvabilité.

    Raises:
        ValueError: Si le solde, le prix ou la fraction sont invalides.
    """
    if balance <= 0 or price <= 0:
        raise ValueError("Le solde et le prix doivent être positifs.")
    if not 0 < limits.max_position_fraction <= 1:
        raise ValueError("Fraction de position invalide.")
    quote_amount = balance * limits.max_position_fraction
    return quote_amount / price


def daily_loss_limit_reached(
    starting_day_balance: float, current_balance: float, limits: RiskLimits
) -> bool:
    """Indique si la perte journalière atteint la limite.

    Les deux valeurs doivent être des **equity** (trésorerie + position valorisée),
    pas des soldes de trésorerie : une position ouverte non réalisée compte donc
    dans la limite.

    Raises:
        ValueError: Si les soldes sont invalides ou si la fraction est hors bornes.
    """
    if starting_day_balance <= 0 or current_balance < 0:
        raise ValueError("Soldes invalides.")
    if not 0 < limits.max_daily_loss_fraction < 1:
        raise ValueError("Fraction de perte journalière invalide.")
    loss_fraction = (starting_day_balance - current_balance) / starting_day_balance
    return loss_fraction >= limits.max_daily_loss_fraction


def assess_entry(
    *,
    equity: float,
    cash: float,
    price: float,
    fee_rate: float,
    limits: RiskLimits,
    daily_halted: bool = False,
    has_position: bool = False,
) -> EntryAssessment:
    """Autorise ou refuse une entrée, et calcule la quantité à acheter.

    La quantité est dimensionnée pour que ``prix * quantité * (1 + frais)``
    reste dans le budget, lui-même borné par la fraction maximale de l'equity
    **et** par la trésorerie disponible. Un achat impossible faute de capital
    est donc refusé, jamais redimensionné silencieusement au-delà du solde.

    Args:
        equity: Valeur totale du portefeuille (mark-to-market).
        cash: Trésorerie disponible.
        price: Prix d'exécution (slippage inclus).
        fee_rate: Frais sur le notionnel.
        limits: Limites de risque.
        daily_halted: La limite de perte journalière est-elle atteinte ?
        has_position: Une position est-elle déjà ouverte ?

    Returns:
        Une :class:`EntryAssessment` avec un motif lisible en cas de refus.
    """
    if has_position:
        return EntryAssessment(False, "position déjà ouverte")
    if daily_halted:
        return EntryAssessment(False, "limite de perte journalière atteinte")
    values = (equity, cash, price, fee_rate)
    if any(not math.isfinite(value) for value in values):
        return EntryAssessment(False, "données invalides pour le dimensionnement")
    if equity <= 0 or cash <= 0 or price <= 0:
        return EntryAssessment(False, "capital ou prix insuffisant")
    if not 0 <= fee_rate < 1:
        return EntryAssessment(False, "taux de frais invalide")
    if not 0 < limits.max_position_fraction <= 1:
        return EntryAssessment(False, "fraction de position invalide")

    budget = min(equity * limits.max_position_fraction, cash)
    if budget < MIN_ENTRY_NOTIONAL:
        return EntryAssessment(
            False,
            f"capital insuffisant (notionnel minimal {MIN_ENTRY_NOTIONAL:.2f} USDT)",
        )

    quantity = budget / (price * (1 + fee_rate))
    if not math.isfinite(quantity) or quantity <= 0:
        return EntryAssessment(False, "capital insuffisant")
    return EntryAssessment(True, "entrée autorisée", quantity)
