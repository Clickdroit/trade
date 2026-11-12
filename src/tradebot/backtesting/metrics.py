"""Fonctions de calcul de métriques pour le backtesting."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tradebot.backtesting.engine import BacktestResult, TradeRecord

# Nombre d'heures dans une année (données horaires).
_HOURS_PER_YEAR = 8760


def compute_max_drawdown(equity_curve: list[float]) -> float:
    """Calcule le drawdown maximal (pic-à-creux) en pourcentage.

    Retourne 0.0 si la courbe est vide ou ne comporte qu'un seul point.
    """
    if len(equity_curve) < 2:
        return 0.0

    peak = equity_curve[0]
    max_dd = 0.0
    for value in equity_curve[1:]:
        if value > peak:
            peak = value
        drawdown = (peak - value) / peak if peak > 0 else 0.0
        if drawdown > max_dd:
            max_dd = drawdown
    return max_dd


def compute_sharpe_ratio(
    returns: list[float], risk_free_rate: float = 0.0
) -> float:
    """Calcule le ratio de Sharpe annualisé pour des rendements horaires.

    Utilise sqrt(8760) comme facteur d'annualisation.
    Retourne 0.0 si l'écart-type est nul ou s'il y a moins de 2 rendements.
    """
    if len(returns) < 2:
        return 0.0

    n = len(returns)
    mean_r = sum(returns) / n
    excess = mean_r - risk_free_rate

    variance = sum((r - mean_r) ** 2 for r in returns) / (n - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0

    if std == 0.0:
        return 0.0

    return (excess / std) * math.sqrt(_HOURS_PER_YEAR)


def compute_win_rate(trades: list[TradeRecord]) -> float:
    """Calcule le taux de réussite (trades gagnants / total).

    Retourne 0.0 s'il n'y a aucun trade.
    """
    if not trades:
        return 0.0
    winners = sum(1 for t in trades if t.pnl > 0)
    return winners / len(trades)


def format_report(result: BacktestResult) -> str:
    """Génère un rapport de backtest lisible en français."""
    lines = [
        "=" * 50,
        "       RAPPORT DE BACKTEST",
        "=" * 50,
        f"  Rendement total          : {result.total_return_pct:+.2f} %",
        f"  Rendement buy & hold     : {result.buy_hold_return_pct:+.2f} %",
        f"  Nombre de trades         : {result.num_trades}",
        f"  Taux de réussite         : {result.win_rate:.1%}",
        f"  Drawdown maximal         : {result.max_drawdown_pct:.2f} %",
        f"  Ratio de Sharpe          : {result.sharpe_ratio:.4f}",
        "=" * 50,
    ]

    if result.trades:
        lines.append("")
        lines.append("  Détail des trades :")
        lines.append("-" * 50)
        for i, t in enumerate(result.trades, 1):
            pnl_sign = "+" if t.pnl >= 0 else ""
            lines.append(
                f"  #{i:>3d}  entrée={t.entry_price:.2f}  "
                f"sortie={t.exit_price:.2f}  qté={t.quantity:.6f}  "
                f"PnL={pnl_sign}{t.pnl:.2f}  frais={t.fees:.2f}"
            )
        lines.append("-" * 50)

    lines.append("")
    return "\n".join(lines)
