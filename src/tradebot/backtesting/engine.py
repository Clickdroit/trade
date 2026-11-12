"""Moteur de backtesting déterministe pour la stratégie de croisement de moyennes mobiles.

Convention temporelle (absence de look-ahead bias)
==================================================
* Le signal n'est calculé qu'à partir de bougies **clôturées**.
* Un signal produit par la clôture de la bougie ``i - 1`` est exécuté à
  l'**ouverture** de la bougie ``i``. Le prix de clôture qui a produit le
  signal n'est donc jamais réutilisé comme prix d'exécution.
* Le stop-loss est évalué sur chaque bougie pendant laquelle la position est
  détenue, bougie d'entrée incluse : le plus bas d'une bougie se produit
  nécessairement après son ouverture, donc après l'achat.
* Si un stop-loss et un signal de vente concernent la même bougie, le
  stop-loss est prioritaire. C'est l'hypothèse la plus défavorable des deux.

Hypothèses d'exécution
======================
* Slippage défavorable systématique : achat à ``prix * (1 + slippage)``,
  vente à ``prix * (1 - slippage)``.
* Frais ``fee_rate`` prélevés sur le notionnel, à l'achat **et** à la vente :
  ``pnl_net = pnl_gross - frais_entrée - frais_sortie``.
* Gap sous le stop : si l'ouverture est déjà sous le niveau de stop, la vente
  se fait à l'ouverture (seul prix réellement disponible), jamais au niveau
  de stop.
* Aucune position n'est ré-ouverte sur la bougie d'une sortie.
* Une position encore ouverte à la dernière bougie est liquidée à sa clôture
  (avec slippage et frais), motif ``end_of_data``.

Gestion du risque
=================
* Taille de position : ``max_position_fraction`` de l'equity disponible
  (10 % par défaut), frais d'achat inclus dans le budget.
* Limite de perte journalière : mesurée sur l'**equity** (mark-to-market,
  position ouverte incluse). La référence est l'equity à l'ouverture de la
  première bougie du jour UTC. Une fois la limite atteinte, aucune nouvelle
  position n'est ouverte jusqu'au prochain jour UTC ; le stop-loss continue
  de protéger la position éventuellement en cours.
* Le solde de trésorerie ne peut pas devenir négatif : un achat est refusé ou
  redimensionné si les frais ne tiennent pas dans le budget.
"""

from __future__ import annotations

import datetime
import math
import statistics
from dataclasses import dataclass, field

from tradebot.backtesting.metrics import (
    compute_average_loss,
    compute_average_win,
    compute_max_drawdown,
    compute_profit_factor,
    compute_return_pct,
    compute_sharpe_ratio,
    compute_win_rate,
)
from tradebot.domain.models import (
    EXIT_END_OF_DATA,
    EXIT_SIGNAL,
    EXIT_STOP_LOSS,
    Candle,
    Signal,
)
from tradebot.risk.manager import RiskLimits, daily_loss_limit_reached, position_size
from tradebot.strategy.moving_average import crossover_signal

#: Millisecondes dans une année civile, pour l'annualisation du Sharpe.
_MS_PER_YEAR = 365 * 24 * 60 * 60 * 1000.0


@dataclass(frozen=True)
class TradeRecord:
    """Trade clôturé, avec PnL brut et net clairement distingués.

    ``pnl_gross`` ignore les frais, ``pnl_net`` les déduit (entrée et sortie).
    ``fees`` contient la somme des frais d'achat et de vente.
    """

    entry_time: int
    exit_time: int
    entry_price: float
    exit_price: float
    quantity: float
    pnl_gross: float
    pnl_net: float
    fees: float
    exit_reason: str

    @property
    def pnl(self) -> float:
        """Alias historique de ``pnl_net`` (le PnL affiché est toujours net)."""
        return self.pnl_net


@dataclass
class BacktestResult:
    """Résultat agrégé d'une exécution de backtest."""

    starting_balance: float
    final_equity: float
    total_return_pct: float
    buy_hold_return_pct: float
    num_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float | None
    max_drawdown_pct: float
    sharpe_ratio: float | None
    profit_factor: float | None
    net_pnl: float
    gross_pnl: float
    total_fees: float
    avg_win: float | None
    avg_loss: float | None
    trades: list[TradeRecord] = field(default_factory=list)


@dataclass
class _OpenPosition:
    """État interne d'une position ouverte pendant la simulation."""

    quantity: float
    entry_price: float
    entry_time: int
    entry_index: int
    entry_fee: float

    @property
    def entry_notional(self) -> float:
        """Notionnel d'entrée, hors frais."""
        return self.entry_price * self.quantity


def _utc_date_from_ts(ts_ms: int) -> datetime.date:
    """Convertit un timestamp en millisecondes en date UTC."""
    return datetime.datetime.fromtimestamp(ts_ms / 1000, tz=datetime.UTC).date()


def _validate_params(
    *,
    short_window: int,
    long_window: int,
    starting_balance: float,
    fee_rate: float,
    slippage_pct: float,
    stop_loss_pct: float,
    limits: RiskLimits,
) -> None:
    """Valide les paramètres du backtest avant toute simulation."""
    if short_window <= 0 or long_window <= short_window:
        raise ValueError(
            "Fenêtres de moyennes mobiles invalides : il faut 0 < short_window < long_window."
        )
    if not math.isfinite(starting_balance) or starting_balance <= 0:
        raise ValueError("Le capital initial doit être un nombre fini strictement positif.")
    if not 0 <= fee_rate < 1:
        raise ValueError("fee_rate doit être compris dans [0, 1).")
    if not 0 <= slippage_pct < 1:
        raise ValueError("slippage_pct doit être compris dans [0, 1).")
    if not 0 < stop_loss_pct < 1:
        raise ValueError("stop_loss_pct doit être compris dans ]0, 1[.")
    if not 0 < limits.max_position_fraction <= 1:
        raise ValueError("max_position_fraction doit être compris dans ]0, 1].")
    if not 0 < limits.max_daily_loss_fraction < 1:
        raise ValueError("max_daily_loss_fraction doit être compris dans ]0, 1[.")


def _validate_candles(candles: list[Candle], long_window: int) -> None:
    """Vérifie la quantité, l'ordre, l'unicité et la cohérence des bougies."""
    minimum = long_window + 2
    if len(candles) < minimum:
        raise ValueError(
            f"Données insuffisantes : {len(candles)} bougies fournies, "
            f"au moins {minimum} sont nécessaires (fenêtre longue = {long_window})."
        )

    previous_timestamp: int | None = None
    for candle in candles:
        if previous_timestamp is not None and candle.timestamp <= previous_timestamp:
            raise ValueError(
                "Les bougies doivent être strictement chronologiques et sans doublon "
                f"(timestamp {candle.timestamp} après {previous_timestamp})."
            )
        for name in ("open", "high", "low", "close"):
            value = getattr(candle, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"Prix {name} invalide à {candle.timestamp} : {value!r}.")
        if candle.high < max(candle.open, candle.close) or candle.low > min(
            candle.open, candle.close
        ):
            raise ValueError(
                f"Bougie incohérente à {candle.timestamp} : high/low incompatibles avec open/close."
            )
        previous_timestamp = candle.timestamp


def _mark_to_market(balance: float, position: _OpenPosition | None, price: float) -> float:
    """Valeur totale du portefeuille (trésorerie + position au prix donné)."""
    if position is None:
        return balance
    return balance + position.quantity * price


def _stop_fill_price(candle: Candle, stop_price: float, slippage_pct: float) -> float | None:
    """Prix d'exécution d'un stop-loss, ou ``None`` si le stop n'est pas atteint.

    Si la bougie ouvre déjà sous le stop (gap), le prix disponible est
    l'ouverture. Sinon, le stop est traité comme un ordre au marché au niveau
    du stop. Dans les deux cas, un slippage défavorable est appliqué.
    """
    if candle.low > stop_price:
        return None
    reference = candle.open if candle.open <= stop_price else stop_price
    return reference * (1 - slippage_pct)


def _exit_decision(
    position: _OpenPosition,
    candle: Candle,
    signal: Signal,
    stop_loss_pct: float,
    slippage_pct: float,
) -> tuple[float, str] | None:
    """Détermine si la position doit être fermée sur cette bougie et à quel prix.

    Ordre des priorités : gap d'ouverture sous le stop, signal de vente à
    l'ouverture, puis stop atteint en cours de bougie.
    """
    stop_price = position.entry_price * (1 - stop_loss_pct)

    if candle.open <= stop_price:
        return candle.open * (1 - slippage_pct), EXIT_STOP_LOSS

    if signal == Signal.SELL:
        return candle.open * (1 - slippage_pct), EXIT_SIGNAL

    if candle.low <= stop_price:
        return stop_price * (1 - slippage_pct), EXIT_STOP_LOSS

    return None


def _close_position(
    position: _OpenPosition,
    exit_time: int,
    exit_price: float,
    fee_rate: float,
    exit_reason: str,
) -> tuple[TradeRecord, float]:
    """Clôture une position et renvoie le trade enregistré et le cash encaissé."""
    gross_proceeds = exit_price * position.quantity
    exit_fee = gross_proceeds * fee_rate
    net_proceeds = gross_proceeds - exit_fee

    pnl_gross = gross_proceeds - position.entry_notional
    pnl_net = pnl_gross - position.entry_fee - exit_fee

    trade = TradeRecord(
        entry_time=position.entry_time,
        exit_time=exit_time,
        entry_price=position.entry_price,
        exit_price=exit_price,
        quantity=position.quantity,
        pnl_gross=pnl_gross,
        pnl_net=pnl_net,
        fees=position.entry_fee + exit_fee,
        exit_reason=exit_reason,
    )
    return trade, net_proceeds


def _open_position(
    candle: Candle,
    balance: float,
    index: int,
    fee_rate: float,
    slippage_pct: float,
    limits: RiskLimits,
) -> tuple[_OpenPosition, float] | None:
    """Ouvre une position à l'ouverture de la bougie et renvoie le cash engagé."""
    if balance <= 0:
        return None

    fill_price = candle.open * (1 + slippage_pct)
    quantity = position_size(balance, fill_price, limits)

    total_cost = fill_price * quantity * (1 + fee_rate)
    if total_cost > balance:
        # Le dimensionnement doit tenir compte des frais pour rester solvable.
        quantity = balance / (fill_price * (1 + fee_rate))

    notional = fill_price * quantity
    entry_fee = notional * fee_rate
    cash_out = min(notional + entry_fee, balance)
    if quantity <= 0 or cash_out <= 0:
        return None

    position = _OpenPosition(
        quantity=quantity,
        entry_price=fill_price,
        entry_time=candle.timestamp,
        entry_index=index,
        entry_fee=entry_fee,
    )
    return position, cash_out


def _periods_per_year(candles: list[Candle]) -> float:
    """Estime le nombre de bougies par an à partir de l'espacement médian."""
    deltas = [
        current.timestamp - previous.timestamp
        for previous, current in zip(candles, candles[1:], strict=False)
    ]
    deltas = [delta for delta in deltas if delta > 0]
    if not deltas:
        return 8760.0
    median_ms = statistics.median(deltas)
    return _MS_PER_YEAR / median_ms


def _daily_loss_hit(day_start_equity: float, current_equity: float, limits: RiskLimits) -> bool:
    """Applique la limite de perte journalière sur l'equity mark-to-market."""
    if day_start_equity <= 0 or current_equity < 0:
        return False
    return daily_loss_limit_reached(day_start_equity, current_equity, limits)


def run_backtest(
    candles: list[Candle],
    short_window: int = 10,
    long_window: int = 30,
    starting_balance: float = 1000.0,
    fee_rate: float = 0.001,
    stop_loss_pct: float = 0.03,
    slippage_pct: float = 0.0005,
    risk_limits: RiskLimits | None = None,
) -> BacktestResult:
    """Exécute un backtest complet sur une liste de bougies.

    Args:
        candles: Bougies OHLCV strictement chronologiques, sans doublon.
        short_window: Fenêtre de la moyenne mobile rapide.
        long_window: Fenêtre de la moyenne mobile lente.
        starting_balance: Capital virtuel initial (strictement positif).
        fee_rate: Frais par transaction, sur le notionnel (0.001 = 0,1 %).
        stop_loss_pct: Baisse déclenchant le stop-loss (0.03 = 3 %).
        slippage_pct: Slippage défavorable appliqué à chaque exécution.
        risk_limits: Limites de taille de position et de perte journalière.

    Returns:
        Un :class:`BacktestResult` avec métriques, trades et PnL net.

    Raises:
        ValueError: Données insuffisantes, invalides, non chronologiques,
            dupliquées, ou paramètres hors bornes.
    """
    limits = risk_limits or RiskLimits()
    _validate_params(
        short_window=short_window,
        long_window=long_window,
        starting_balance=starting_balance,
        fee_rate=fee_rate,
        slippage_pct=slippage_pct,
        stop_loss_pct=stop_loss_pct,
        limits=limits,
    )
    _validate_candles(candles, long_window)

    balance = starting_balance
    position: _OpenPosition | None = None
    trades: list[TradeRecord] = []

    equity_curve: list[float] = [starting_balance]
    closes: list[float] = []

    current_day: datetime.date | None = None
    day_start_equity = starting_balance
    day_halted = False

    for index, candle in enumerate(candles):
        candle_day = _utc_date_from_ts(candle.timestamp)
        if candle_day != current_day:
            current_day = candle_day
            day_start_equity = _mark_to_market(balance, position, candle.open)
            day_halted = False

        equity_at_open = _mark_to_market(balance, position, candle.open)
        if not day_halted and _daily_loss_hit(day_start_equity, equity_at_open, limits):
            day_halted = True

        # Signal calculé sur les bougies déjà clôturées : `closes` s'arrête à
        # la bougie précédente, jamais à la bougie en cours.
        signal = Signal.HOLD
        if len(closes) >= long_window + 1:
            signal = crossover_signal(closes, short_window, long_window)

        exited_this_candle = False
        if position is not None:
            decision = _exit_decision(position, candle, signal, stop_loss_pct, slippage_pct)
            if decision is not None:
                fill_price, exit_reason = decision
                trade, proceeds = _close_position(
                    position,
                    exit_time=candle.timestamp,
                    exit_price=fill_price,
                    fee_rate=fee_rate,
                    exit_reason=exit_reason,
                )
                trades.append(trade)
                balance += proceeds
                position = None
                exited_this_candle = True

        if position is None and not day_halted and not exited_this_candle and signal == Signal.BUY:
            opened = _open_position(candle, balance, index, fee_rate, slippage_pct, limits)
            if opened is not None:
                position, cash_out = opened
                balance -= cash_out

                # Le plus bas de la bougie d'entrée survient après l'achat :
                # un stop peut donc être touché dès cette bougie.
                stop_fill = _stop_fill_price(
                    candle, position.entry_price * (1 - stop_loss_pct), slippage_pct
                )
                if stop_fill is not None:
                    trade, proceeds = _close_position(
                        position,
                        exit_time=candle.timestamp,
                        exit_price=stop_fill,
                        fee_rate=fee_rate,
                        exit_reason=EXIT_STOP_LOSS,
                    )
                    trades.append(trade)
                    balance += proceeds
                    position = None

        if balance < 0:
            raise RuntimeError(
                f"Solde négatif à {candle.timestamp} : {balance:.8f}. "
                "Le moteur a violé sa contrainte de solvabilité."
            )

        closes.append(candle.close)
        equity_curve.append(_mark_to_market(balance, position, candle.close))

        if not day_halted and _daily_loss_hit(day_start_equity, equity_curve[-1], limits):
            day_halted = True

    if position is not None:
        last_candle = candles[-1]
        fill_price = last_candle.close * (1 - slippage_pct)
        trade, proceeds = _close_position(
            position,
            exit_time=last_candle.timestamp,
            exit_price=fill_price,
            fee_rate=fee_rate,
            exit_reason=EXIT_END_OF_DATA,
        )
        trades.append(trade)
        balance += proceeds
        position = None
        equity_curve[-1] = balance

    final_equity = balance
    net_pnl = sum(trade.pnl_net for trade in trades)
    winning_trades = sum(1 for trade in trades if trade.pnl_net > 0)
    losing_trades = sum(1 for trade in trades if trade.pnl_net < 0)

    period_returns = [
        (current - previous) / previous if previous > 0 else 0.0
        for previous, current in zip(equity_curve, equity_curve[1:], strict=False)
    ]

    return BacktestResult(
        starting_balance=starting_balance,
        final_equity=final_equity,
        total_return_pct=compute_return_pct(starting_balance, final_equity),
        buy_hold_return_pct=compute_return_pct(candles[0].open, candles[-1].close),
        num_trades=len(trades),
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=compute_win_rate(trades),
        max_drawdown_pct=compute_max_drawdown(equity_curve) * 100,
        sharpe_ratio=compute_sharpe_ratio(
            period_returns, periods_per_year=_periods_per_year(candles)
        ),
        profit_factor=compute_profit_factor(trades),
        net_pnl=net_pnl,
        gross_pnl=sum(trade.pnl_gross for trade in trades),
        total_fees=sum(trade.fees for trade in trades),
        avg_win=compute_average_win(trades),
        avg_loss=compute_average_loss(trades),
        trades=trades,
    )
