"""Conservative position sizing and daily loss guardrails."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskLimits:
    max_position_fraction: float = 0.10
    max_daily_loss_fraction: float = 0.05


def position_size(balance: float, price: float, limits: RiskLimits) -> float:
    if balance <= 0 or price <= 0:
        raise ValueError("Le solde et le prix doivent être positifs.")
    if not 0 < limits.max_position_fraction <= 1:
        raise ValueError("Fraction de position invalide.")
    quote_amount = balance * limits.max_position_fraction
    return quote_amount / price


def daily_loss_limit_reached(
    starting_day_balance: float, current_balance: float, limits: RiskLimits
) -> bool:
    if starting_day_balance <= 0 or current_balance < 0:
        raise ValueError("Soldes invalides.")
    if not 0 < limits.max_daily_loss_fraction < 1:
        raise ValueError("Fraction de perte journalière invalide.")
    loss_fraction = (starting_day_balance - current_balance) / starting_day_balance
    return loss_fraction >= limits.max_daily_loss_fraction
