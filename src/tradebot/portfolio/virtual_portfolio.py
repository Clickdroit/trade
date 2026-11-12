"""Portefeuille virtuel du Paper Trading.

Conventions comptables
======================
* ``starting_balance`` : capital virtuel initial, jamais modifié.
* ``cash`` : trésorerie disponible en devise de cotation (jamais négative).
* ``realized_pnl`` : somme des PnL nets des positions clôturées, frais déduits.
* ``unrealized_pnl(price)`` : ``quantité * prix - (notionnel d'entrée + frais d'achat)``.
  Le PnL latent est donc net des frais d'achat et **brut** des frais de sortie,
  qui ne seront prélevés qu'à la clôture.
* Invariant garanti par :meth:`VirtualPortfolio.assert_consistent` :
  ``equity(price) == starting_balance + realized_pnl + unrealized_pnl(price)``.
* Les prix reçus ici sont déjà ajustés du slippage : le portefeuille ne connaît
  que le prix d'exécution et le taux de frais. Une seule position à la fois.

Le portefeuille est volontairement indépendant de tout exchange : il ne peut
pas passer d'ordre, seulement appliquer des exécutions simulées.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


class PortfolioStateError(RuntimeError):
    """État du portefeuille incohérent : toute opération doit être refusée."""


@dataclass(frozen=True)
class Position:
    """Position ouverte, valorisée au prix d'exécution (slippage inclus)."""

    symbol: str
    quantity: float
    entry_price: float
    entry_time: int  # millisecondes UTC
    entry_fee: float

    @property
    def entry_notional(self) -> float:
        """Notionnel d'entrée, hors frais."""
        return self.entry_price * self.quantity

    @property
    def cost_basis(self) -> float:
        """Coût total de la position, frais d'achat inclus."""
        return self.entry_notional + self.entry_fee


@dataclass(frozen=True)
class ClosedTrade:
    """Transaction clôturée, PnL brut et net distingués."""

    symbol: str
    entry_time: int
    exit_time: int
    entry_price: float
    exit_price: float
    quantity: float
    pnl_gross: float
    pnl_net: float
    fees: float
    exit_reason: str


def _require_positive(value: float, label: str) -> float:
    """Valide un prix ou une quantité strictement positif et fini."""
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"{label} doit être un nombre.")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric <= 0:
        raise ValueError(f"{label} doit être un nombre fini strictement positif.")
    return numeric


class VirtualPortfolio:
    """Portefeuille virtuel : solde, position unique, frais et performance."""

    def __init__(
        self,
        starting_balance: float = 1000.0,
        fee_rate: float = 0.001,
        *,
        cash: float | None = None,
        realized_pnl: float = 0.0,
        peak_equity: float | None = None,
    ) -> None:
        """Initialise un portefeuille, éventuellement restauré depuis un état sauvegardé.

        Args:
            starting_balance: Capital virtuel initial.
            fee_rate: Frais par transaction sur le notionnel (0.001 = 0,1 %).
            cash: Trésorerie à restaurer (par défaut le capital initial).
            realized_pnl: PnL réalisé à restaurer.
            peak_equity: Plus haute valeur observée, pour le drawdown.

        Raises:
            ValueError: Paramètre hors bornes.
        """
        self._starting_balance = _require_positive(starting_balance, "starting_balance")
        if not 0 <= fee_rate < 1:
            raise ValueError("fee_rate doit être compris dans [0, 1[.")

        restored_cash = self._starting_balance if cash is None else float(cash)
        if not math.isfinite(restored_cash) or restored_cash < 0:
            raise ValueError("cash doit être un nombre fini positif ou nul.")
        if not math.isfinite(realized_pnl):
            raise ValueError("realized_pnl doit être un nombre fini.")

        self._fee_rate = float(fee_rate)
        self._cash = restored_cash
        self._realized_pnl = float(realized_pnl)
        self._position: Position | None = None
        self._peak_equity = (
            float(peak_equity)
            if peak_equity is not None
            else max(self._starting_balance, restored_cash)
        )
        if not math.isfinite(self._peak_equity) or self._peak_equity <= 0:
            raise ValueError("peak_equity doit être un nombre fini strictement positif.")

    # ------------------------------------------------------------------
    # Propriétés
    # ------------------------------------------------------------------

    @property
    def starting_balance(self) -> float:
        """Capital virtuel initial."""
        return self._starting_balance

    @property
    def cash(self) -> float:
        """Solde disponible en devise de cotation."""
        return self._cash

    @property
    def fee_rate(self) -> float:
        """Taux de frais appliqué à chaque transaction."""
        return self._fee_rate

    @property
    def position(self) -> Position | None:
        """Position ouverte, ou ``None``."""
        return self._position

    @property
    def realized_pnl(self) -> float:
        """PnL réalisé cumulé, frais déduits."""
        return self._realized_pnl

    @property
    def peak_equity(self) -> float:
        """Plus haute valeur totale observée."""
        return self._peak_equity

    # ------------------------------------------------------------------
    # Valorisation
    # ------------------------------------------------------------------

    def equity(self, price: float) -> float:
        """Valeur totale du portefeuille au prix courant.

        Args:
            price: Prix de référence (dernière clôture connue).

        Returns:
            Trésorerie + valeur marchande de la position ouverte.
        """
        if not math.isfinite(price) or price < 0:
            raise ValueError("Prix de valorisation invalide.")
        if self._position is None:
            return self._cash
        return self._cash + self._position.quantity * price

    def unrealized_pnl(self, price: float) -> float:
        """PnL latent : valorisation au prix courant moins coût d'entrée (frais inclus)."""
        if not math.isfinite(price) or price < 0:
            raise ValueError("Prix de valorisation invalide.")
        if self._position is None:
            return 0.0
        return self._position.quantity * price - self._position.cost_basis

    def drawdown_pct(self, price: float) -> float:
        """Drawdown courant depuis le plus haut de la valeur totale, en pourcentage."""
        equity = self.equity(price)
        if self._peak_equity <= 0:
            return 0.0
        return max(0.0, (self._peak_equity - equity) / self._peak_equity * 100)

    def mark(self, price: float) -> float:
        """Valorise le portefeuille et met à jour le plus haut (drawdown)."""
        equity = self.equity(price)
        if equity > self._peak_equity:
            self._peak_equity = equity
        return equity

    # ------------------------------------------------------------------
    # Opérations simulées
    # ------------------------------------------------------------------

    def open_position(
        self, symbol: str, price: float, quantity: float, timestamp: int
    ) -> Position:
        """Ouvre une position en déduisant notionnel et frais du solde.

        Args:
            symbol: Paire négociée (ex. ``BTC/USDT``).
            price: Prix d'exécution, slippage déjà appliqué.
            quantity: Quantité achetée.
            timestamp: Horodatage de l'exécution, en millisecondes UTC.

        Returns:
            La position créée.

        Raises:
            ValueError: Position déjà ouverte, solde insuffisant ou paramètre invalide.
        """
        if not symbol:
            raise ValueError("Le symbole est obligatoire.")
        execution_price = _require_positive(price, "price")
        amount = _require_positive(quantity, "quantity")
        if timestamp < 0:
            raise ValueError("timestamp doit être positif ou nul.")
        if self._position is not None:
            raise ValueError(
                "Une position est déjà ouverte ; la fermer avant d'en ouvrir une autre."
            )

        notional = execution_price * amount
        fee = notional * self._fee_rate
        total_cost = notional + fee
        # Tolérance uniquement pour l'arrondi flottant, jamais pour un vrai manque.
        if total_cost > self._cash + 1e-9:
            raise ValueError(
                f"Solde insuffisant : {self._cash:.2f} disponible, {total_cost:.2f} requis."
            )

        self._cash = max(0.0, self._cash - total_cost)
        self._position = Position(
            symbol=symbol,
            quantity=amount,
            entry_price=execution_price,
            entry_time=int(timestamp),
            entry_fee=fee,
        )
        return self._position

    def close_position(self, price: float, timestamp: int, reason: str = "signal") -> ClosedTrade:
        """Ferme la position ouverte et encaisse le produit net de la vente.

        Args:
            price: Prix d'exécution, slippage déjà appliqué.
            timestamp: Horodatage de l'exécution, en millisecondes UTC.
            reason: Motif de sortie (``signal``, ``stop_loss``, ``daily_loss_limit``).

        Returns:
            La transaction clôturée, avec PnL brut et net.

        Raises:
            ValueError: Aucune position ouverte, sortie antérieure à l'entrée, ou
                paramètre invalide.
        """
        position = self._position
        if position is None:
            raise ValueError("Aucune position ouverte à fermer.")
        execution_price = _require_positive(price, "price")
        if timestamp < position.entry_time:
            raise ValueError("L'horodatage de sortie précède celui de l'entrée.")
        if not reason:
            raise ValueError("Le motif de sortie est obligatoire.")

        gross_proceeds = execution_price * position.quantity
        exit_fee = gross_proceeds * self._fee_rate
        net_proceeds = gross_proceeds - exit_fee
        pnl_gross = gross_proceeds - position.entry_notional
        pnl_net = pnl_gross - position.entry_fee - exit_fee

        self._cash += net_proceeds
        self._realized_pnl += pnl_net
        self._position = None
        return ClosedTrade(
            symbol=position.symbol,
            entry_time=position.entry_time,
            exit_time=int(timestamp),
            entry_price=position.entry_price,
            exit_price=execution_price,
            quantity=position.quantity,
            pnl_gross=pnl_gross,
            pnl_net=pnl_net,
            fees=position.entry_fee + exit_fee,
            exit_reason=reason,
        )

    # ------------------------------------------------------------------
    # Risque, restauration et contrôle
    # ------------------------------------------------------------------

    def check_stop_loss(self, current_price: float, stop_loss_fraction: float) -> bool:
        """Indique si le prix a chuté d'au moins ``stop_loss_fraction`` sous l'entrée.

        Raises:
            ValueError: Prix ou fraction invalides.
        """
        _require_positive(current_price, "current_price")
        if not 0 < stop_loss_fraction < 1:
            raise ValueError("stop_loss_fraction doit être compris dans ]0, 1[.")
        if self._position is None:
            return False
        drop = (self._position.entry_price - current_price) / self._position.entry_price
        return drop >= stop_loss_fraction

    def load_position(self, position: Position) -> None:
        """Restaure une position persistée (redémarrage).

        Raises:
            PortfolioStateError: Position invalide ou déjà présente.
        """
        if self._position is not None:
            raise PortfolioStateError("Une position est déjà chargée.")
        if position.quantity <= 0 or position.entry_price <= 0 or position.entry_fee < 0:
            raise PortfolioStateError(f"Position persistée invalide : {position!r}.")
        if position.entry_time < 0:
            raise PortfolioStateError("Horodatage d'entrée négatif.")
        self._position = position

    def assert_consistent(self, price: float | None = None) -> None:
        """Vérifie les invariants comptables, y compris après restauration.

        Args:
            price: Prix de valorisation optionnel pour contrôler l'égalité
                ``equity == capital initial + PnL réalisé + PnL latent``.

        Raises:
            PortfolioStateError: Solde négatif, valeurs non finies, ou incohérence
                entre trésorerie, position et PnL.
        """
        if not math.isfinite(self._cash) or self._cash < 0:
            raise PortfolioStateError(f"Trésorerie incohérente : {self._cash!r}.")
        if not math.isfinite(self._realized_pnl):
            raise PortfolioStateError(f"PnL réalisé incohérent : {self._realized_pnl!r}.")
        if not math.isfinite(self._peak_equity) or self._peak_equity <= 0:
            raise PortfolioStateError(f"Plus haut incohérent : {self._peak_equity!r}.")
        if self._position is not None:
            position = self._position
            if not math.isfinite(position.quantity) or position.quantity <= 0:
                raise PortfolioStateError(f"Quantité détenue incohérente : {position.quantity!r}.")
            if not math.isfinite(position.entry_price) or position.entry_price <= 0:
                raise PortfolioStateError(f"Prix d'entrée incohérent : {position.entry_price!r}.")
            if not math.isfinite(position.entry_fee) or position.entry_fee < 0:
                raise PortfolioStateError(f"Frais d'entrée incohérents : {position.entry_fee!r}.")

        # Invariant structurel : la trésorerie doit refléter exactement
        # capital initial + PnL réalisé - coût de la position ouverte.
        expected_cash = self._starting_balance + self._realized_pnl
        if self._position is not None:
            expected_cash -= self._position.cost_basis
        tolerance = 1e-6 * max(1.0, abs(expected_cash))
        if abs(self._cash - expected_cash) > tolerance:
            raise PortfolioStateError(
                f"Trésorerie incohérente : {self._cash:.8f} au lieu de {expected_cash:.8f} "
                "(capital initial + PnL réalisé - coût de la position)."
            )

        if price is not None:
            equity = self.equity(price)
            expected_equity = self._starting_balance + self._realized_pnl + self.unrealized_pnl(
                price
            )
            if abs(equity - expected_equity) > 1e-6 * max(1.0, abs(equity)):
                raise PortfolioStateError(
                    f"Valeur totale incohérente : {equity:.8f} au lieu de {expected_equity:.8f}."
                )

    def to_dict(self) -> dict:
        """Sérialise le portefeuille pour les logs et le diagnostic."""
        return {
            "starting_balance": self._starting_balance,
            "cash": self._cash,
            "fee_rate": self._fee_rate,
            "realized_pnl": self._realized_pnl,
            "peak_equity": self._peak_equity,
            "position": None if self._position is None else {
                "symbol": self._position.symbol,
                "quantity": self._position.quantity,
                "entry_price": self._position.entry_price,
                "entry_time": self._position.entry_time,
                "entry_fee": self._position.entry_fee,
            },
        }
