"""Gestionnaire de portefeuille virtuel pour simuler des trades sans risque réel."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class Position:
    """Représente une position ouverte sur un symbole."""

    symbol: str
    quantity: float
    entry_price: float
    entry_time: str  # ISO 8601


class VirtualPortfolio:
    """Portefeuille virtuel pour le paper trading.

    Gère le solde, les positions ouvertes, les frais et le suivi
    quotidien des pertes et profits.
    """

    def __init__(self, starting_balance: float = 1000.0, fee_rate: float = 0.001) -> None:
        """Initialise le portefeuille avec un solde de départ et un taux de frais.

        Args:
            starting_balance: Solde initial en devise de cotation.
            fee_rate: Taux de frais appliqué à chaque transaction (ex. 0.001 = 0.1 %).
        """
        self._balance: float = starting_balance
        self._fee_rate: float = fee_rate
        self._position: Position | None = None
        self._day_start_balance: float = starting_balance

    # ------------------------------------------------------------------
    # Propriétés
    # ------------------------------------------------------------------

    @property
    def balance(self) -> float:
        """Solde disponible en devise de cotation."""
        return self._balance

    @property
    def position(self) -> Position | None:
        """Position actuellement ouverte, ou None."""
        return self._position

    def equity(self, price: float) -> float:
        """Calcule la valeur totale du portefeuille au prix courant.

        Args:
            price: Prix actuel de l'actif.

        Returns:
            Somme du solde et de la valeur marchande de la position ouverte.
        """
        if self._position is None:
            return self._balance
        return self._balance + self._position.quantity * price

    def daily_pnl_pct(self, price: float) -> float:
        """Rendement quotidien en pourcentage par rapport au début de la journée.

        Args:
            price: Prix actuel de l'actif.

        Returns:
            Variation en pourcentage depuis le début de la journée.
        """
        if self._day_start_balance == 0:
            return 0.0
        current_equity = self.equity(price)
        return (current_equity - self._day_start_balance) / self._day_start_balance * 100

    # ------------------------------------------------------------------
    # Opérations
    # ------------------------------------------------------------------

    def open_position(self, symbol: str, price: float, quantity: float) -> None:
        """Ouvre une nouvelle position en déduisant le coût et les frais du solde.

        Args:
            symbol: Symbole de l'actif (ex. ``BTC/USDT``).
            price: Prix d'entrée.
            quantity: Quantité à acheter.

        Raises:
            ValueError: Si une position est déjà ouverte ou si le solde est insuffisant.
        """
        if self._position is not None:
            msg = "Une position est déjà ouverte ; fermez-la avant d'en ouvrir une autre."
            raise ValueError(msg)

        cost = price * quantity
        fees = cost * self._fee_rate
        total_cost = cost + fees

        if total_cost > self._balance:
            msg = f"Solde insuffisant : {self._balance:.2f} disponible, {total_cost:.2f} requis."
            raise ValueError(msg)

        self._balance -= total_cost
        self._position = Position(
            symbol=symbol,
            quantity=quantity,
            entry_price=price,
            entry_time=datetime.now(tz=UTC).isoformat(),
        )

    def close_position(self, price: float) -> float:
        """Ferme la position ouverte et renvoie le PnL réalisé.

        Args:
            price: Prix de sortie.

        Returns:
            Profit ou perte réalisé(e) après frais.

        Raises:
            ValueError: Si aucune position n'est ouverte.
        """
        if self._position is None:
            msg = "Aucune position ouverte à fermer."
            raise ValueError(msg)

        proceeds = price * self._position.quantity
        fees = proceeds * self._fee_rate
        net_proceeds = proceeds - fees

        entry_cost = self._position.entry_price * self._position.quantity
        pnl = net_proceeds - entry_cost

        self._balance += net_proceeds
        self._position = None
        return pnl

    def check_stop_loss(self, current_price: float, stop_loss_fraction: float) -> bool:
        """Vérifie si le stop-loss est atteint.

        Args:
            current_price: Prix actuel de l'actif.
            stop_loss_fraction: Fraction de baisse déclenchant le stop-loss (ex. 0.03 = 3 %).

        Returns:
            True si le prix a chuté d'au moins *stop_loss_fraction* sous le prix d'entrée.
        """
        if self._position is None:
            return False
        drop = (self._position.entry_price - current_price) / self._position.entry_price
        return drop >= stop_loss_fraction

    def reset_daily_tracking(self, current_price: float = 0.0) -> None:
        """Réinitialise le suivi quotidien au début d'une nouvelle journée.

        Enregistre l'équité courante comme référence pour le calcul du PnL quotidien.

        Args:
            current_price: Prix actuel pour évaluer l'équité ; ignoré si aucune
                position n'est ouverte.
        """
        self._day_start_balance = self.equity(current_price)

    def to_dict(self) -> dict:
        """Sérialise le portefeuille sous forme de dictionnaire.

        Returns:
            Dictionnaire contenant le solde, les frais et la position éventuelle.
        """
        position_data: dict | None = None
        if self._position is not None:
            position_data = {
                "symbol": self._position.symbol,
                "quantity": self._position.quantity,
                "entry_price": self._position.entry_price,
                "entry_time": self._position.entry_time,
            }

        return {
            "balance": self._balance,
            "fee_rate": self._fee_rate,
            "day_start_balance": self._day_start_balance,
            "position": position_data,
        }
