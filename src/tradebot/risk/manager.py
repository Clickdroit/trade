"""Garde-fous de risque : dimensionnement et limite de perte journalière."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskLimits:
    """Limites conservatrices appliquées par l'application et le backtest.

    ``max_position_fraction`` est la part maximale de l'equity engagée sur une
    position (0.10 = 10 %). ``max_daily_loss_fraction`` est la perte maximale
    tolérée sur une journée UTC, mesurée sur l'equity (0.05 = 5 %).
    """

    max_position_fraction: float = 0.10
    max_daily_loss_fraction: float = 0.05


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
