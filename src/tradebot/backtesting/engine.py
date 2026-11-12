"""Moteur de backtesting pour évaluer la stratégie de croisement de moyennes mobiles."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from tradebot.backtesting.metrics import (
    compute_max_drawdown,
    compute_sharpe_ratio,
    compute_win_rate,
)
from tradebot.domain.models import Candle, Signal
from tradebot.risk.manager import RiskLimits, daily_loss_limit_reached, position_size
from tradebot.strategy.moving_average import crossover_signal


@dataclass
class TradeRecord:
    """Enregistrement d'un trade exécuté pendant le backtest."""

    entry_time: int
    exit_time: int
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    fees: float


@dataclass
class BacktestResult:
    """Résultat agrégé d'une exécution de backtest."""

    total_return_pct: float
    buy_hold_return_pct: float
    num_trades: int
    win_rate: float
    max_drawdown_pct: float
    sharpe_ratio: float
    trades: list[TradeRecord] = field(default_factory=list)


def _utc_date_from_ts(ts_ms: int) -> datetime.date:
    """Convertit un timestamp en millisecondes en date UTC."""
    return datetime.datetime.fromtimestamp(
        ts_ms / 1000, tz=datetime.timezone.utc
    ).date()


def run_backtest(
    candles: list[Candle],
    short_window: int = 10,
    long_window: int = 30,
    starting_balance: float = 1000.0,
    fee_rate: float = 0.001,
    stop_loss_pct: float = 0.03,
    slippage_pct: float = 0.0005,
) -> BacktestResult:
    """Exécute un backtest complet sur une liste de bougies.

    Simule l'exécution de la stratégie de croisement de moyennes mobiles
    avec gestion du risque, stop-loss, frais et slippage.
    """
    if len(candles) < 2:
        return BacktestResult(
            total_return_pct=0.0,
            buy_hold_return_pct=0.0,
            num_trades=0,
            win_rate=0.0,
            max_drawdown_pct=0.0,
            sharpe_ratio=0.0,
        )

    risk_limits = RiskLimits()
    balance = starting_balance
    position_qty = 0.0
    entry_price = 0.0
    entry_time = 0

    trades: list[TradeRecord] = []
    equity_curve: list[float] = [starting_balance]
    period_returns: list[float] = []

    # Suivi de la limite de perte journalière.
    current_day: datetime.date | None = None
    day_start_balance = starting_balance
    day_halted = False

    for i in range(len(candles)):
        candle = candles[i]

        # Détection de changement de jour pour la limite de perte.
        candle_day = _utc_date_from_ts(candle.timestamp)
        if candle_day != current_day:
            current_day = candle_day
            day_start_balance = balance + (
                position_qty * candle.close if position_qty > 0 else 0.0
            )
            day_halted = False

        # Vérifier la limite de perte journalière.
        current_equity = balance + (
            position_qty * candle.close if position_qty > 0 else 0.0
        )
        if daily_loss_limit_reached(day_start_balance, current_equity, risk_limits):
            day_halted = True

        # Vérification du stop-loss si une position est ouverte.
        if position_qty > 0 and candle.low <= entry_price * (1 - stop_loss_pct):
            exit_price = entry_price * (1 - stop_loss_pct)
            exit_price_slipped = exit_price * (1 - slippage_pct)
            sell_fees = exit_price_slipped * position_qty * fee_rate
            proceeds = exit_price_slipped * position_qty - sell_fees
            pnl = proceeds - (entry_price * position_qty)

            trades.append(
                TradeRecord(
                    entry_time=entry_time,
                    exit_time=candle.timestamp,
                    entry_price=entry_price,
                    exit_price=exit_price_slipped,
                    quantity=position_qty,
                    pnl=pnl,
                    fees=sell_fees,
                )
            )
            balance += proceeds
            position_qty = 0.0
            entry_price = 0.0
            entry_time = 0

            # Mettre à jour l'equity après le stop-loss.
            current_equity = balance
            equity_curve.append(current_equity)
            prev_equity = equity_curve[-2] if len(equity_curve) >= 2 else current_equity
            ret = (
                (current_equity - prev_equity) / prev_equity
                if prev_equity > 0
                else 0.0
            )
            period_returns.append(ret)
            continue

        # Obtenir le signal de la stratégie.
        closes = [c.close for c in candles[: i + 1]]
        signal = crossover_signal(closes, short_window, long_window)

        if not day_halted:
            if signal == Signal.BUY and position_qty == 0:
                # Ouvrir une position.
                fill_price = candle.close * (1 + slippage_pct)
                qty = position_size(balance, fill_price, risk_limits)
                cost = fill_price * qty
                buy_fees = cost * fee_rate
                total_cost = cost + buy_fees

                if total_cost <= balance:
                    balance -= total_cost
                    position_qty = qty
                    entry_price = fill_price
                    entry_time = candle.timestamp

            elif signal == Signal.SELL and position_qty > 0:
                # Fermer la position.
                fill_price = candle.close * (1 - slippage_pct)
                sell_fees = fill_price * position_qty * fee_rate
                proceeds = fill_price * position_qty - sell_fees
                pnl = proceeds - (entry_price * position_qty)

                trades.append(
                    TradeRecord(
                        entry_time=entry_time,
                        exit_time=candle.timestamp,
                        entry_price=entry_price,
                        exit_price=fill_price,
                        quantity=position_qty,
                        pnl=pnl,
                        fees=sell_fees,
                    )
                )
                balance += proceeds
                position_qty = 0.0
                entry_price = 0.0
                entry_time = 0

        # Calculer l'equity et le rendement de la période.
        current_equity = balance + (
            position_qty * candle.close if position_qty > 0 else 0.0
        )
        equity_curve.append(current_equity)
        prev_equity = equity_curve[-2] if len(equity_curve) >= 2 else current_equity
        ret = (
            (current_equity - prev_equity) / prev_equity if prev_equity > 0 else 0.0
        )
        period_returns.append(ret)

    # Fermer toute position restante à la dernière bougie.
    if position_qty > 0:
        last_candle = candles[-1]
        fill_price = last_candle.close * (1 - slippage_pct)
        sell_fees = fill_price * position_qty * fee_rate
        proceeds = fill_price * position_qty - sell_fees
        pnl = proceeds - (entry_price * position_qty)

        trades.append(
            TradeRecord(
                entry_time=entry_time,
                exit_time=last_candle.timestamp,
                entry_price=entry_price,
                exit_price=fill_price,
                quantity=position_qty,
                pnl=pnl,
                fees=sell_fees,
            )
        )
        balance += proceeds
        position_qty = 0.0

    # Calcul des métriques finales.
    final_equity = balance
    total_return_pct = ((final_equity - starting_balance) / starting_balance) * 100

    buy_hold_return_pct = (
        ((candles[-1].close - candles[0].close) / candles[0].close) * 100
    )

    return BacktestResult(
        total_return_pct=total_return_pct,
        buy_hold_return_pct=buy_hold_return_pct,
        num_trades=len(trades),
        win_rate=compute_win_rate(trades),
        max_drawdown_pct=compute_max_drawdown(equity_curve) * 100,
        sharpe_ratio=compute_sharpe_ratio(period_returns),
        trades=trades,
    )
