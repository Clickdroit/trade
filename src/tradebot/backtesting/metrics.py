"""Métriques de backtesting, documentées et sans valeur trompeuse.

Conventions
===========
* Les rendements sont exprimés en fraction (``0.05`` = 5 %) par les fonctions
  de calcul, et convertis en pourcentage uniquement dans le rapport.
* Une métrique qui n'a pas de sens mathématique (pas assez de données, aucun
  trade, écart-type nul…) vaut ``None`` plutôt que ``0.0``. Un ``0.0``
  affirmerait une performance neutre qui n'a pas été mesurée.
* Le profit factor vaut ``inf`` lorsqu'il n'y a aucune perte mais au moins un
  gain : c'est la limite mathématique de ``gains / |pertes|``.
"""

from __future__ import annotations

import datetime
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from tradebot.backtesting.engine import BacktestResult, TradeRecord

#: Nombre de bougies horaires dans une année (utilisé si le timeframe est inconnu).
HOURS_PER_YEAR = 8760.0


def compute_return_pct(starting_value: float, ending_value: float) -> float:
    """Rendement simple en pourcentage entre deux valeurs.

    Raises:
        ValueError: Si la valeur de départ n'est pas strictement positive
            (division par zéro).
    """
    if starting_value <= 0:
        raise ValueError("La valeur de départ doit être strictement positive.")
    return (ending_value / starting_value - 1) * 100


def compute_max_drawdown(equity_curve: Sequence[float]) -> float:
    """Drawdown maximal pic-à-creux, en fraction de la valeur du pic.

    ``max((pic - valeur) / pic)`` sur toute la courbe. Retourne ``0.0`` pour
    une courbe vide ou à un seul point : aucun drawdown n'a pu être mesuré.
    """
    if len(equity_curve) < 2:
        return 0.0

    peak = equity_curve[0]
    max_drawdown = 0.0
    for value in equity_curve[1:]:
        if value > peak:
            peak = value
        if peak <= 0:
            continue
        drawdown = (peak - value) / peak
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    return max_drawdown


def compute_sharpe_ratio(
    returns: Sequence[float],
    *,
    periods_per_year: float = HOURS_PER_YEAR,
    risk_free_rate: float = 0.0,
) -> float | None:
    """Ratio de Sharpe annualisé à partir de rendements par période.

    Formule : ``(moyenne - taux_sans_risque) / écart_type * sqrt(périodes/an)``.
    L'écart-type est l'estimateur d'échantillon (``n - 1``).

    Args:
        returns: Rendements par bougie (fractions).
        periods_per_year: Nombre de périodes dans une année (8760 en 1 h).
        risk_free_rate: Taux sans risque **par période** (0 par défaut).

    Returns:
        Le ratio, ou ``None`` s'il y a moins de deux rendements ou si
        l'écart-type est nul (ratio indéfini).

    Raises:
        ValueError: Si ``periods_per_year`` n'est pas strictement positif.
    """
    if periods_per_year <= 0:
        raise ValueError("periods_per_year doit être strictement positif.")
    if len(returns) < 2:
        return None

    n = len(returns)
    mean_return = sum(returns) / n
    excess = mean_return - risk_free_rate

    variance = sum((value - mean_return) ** 2 for value in returns) / (n - 1)
    if variance <= 0:
        return None
    std = math.sqrt(variance)

    return (excess / std) * math.sqrt(periods_per_year)


def compute_win_rate(trades: Sequence[TradeRecord]) -> float | None:
    """Part des trades au PnL net strictement positif.

    Les trades à PnL net nul ne sont ni gagnants ni perdants. Retourne ``None``
    s'il n'y a aucun trade.
    """
    if not trades:
        return None
    winners = sum(1 for trade in trades if trade.pnl_net > 0)
    return winners / len(trades)


def compute_profit_factor(trades: Sequence[TradeRecord]) -> float | None:
    """Somme des gains nets / valeur absolue de la somme des pertes nettes.

    Retourne ``None`` sans trade (ou si tous les trades sont à PnL nul) et
    ``inf`` s'il y a des gains mais aucune perte.
    """
    if not trades:
        return None

    gross_profit = sum(trade.pnl_net for trade in trades if trade.pnl_net > 0)
    gross_loss = -sum(trade.pnl_net for trade in trades if trade.pnl_net < 0)

    if gross_loss == 0:
        return math.inf if gross_profit > 0 else None
    return gross_profit / gross_loss


def compute_average_win(trades: Sequence[TradeRecord]) -> float | None:
    """Gain net moyen des trades gagnants, ou ``None`` s'il n'y en a aucun."""
    winners = [trade.pnl_net for trade in trades if trade.pnl_net > 0]
    if not winners:
        return None
    return sum(winners) / len(winners)


def compute_average_loss(trades: Sequence[TradeRecord]) -> float | None:
    """Perte nette moyenne des trades perdants (valeur négative), ou ``None``."""
    losers = [trade.pnl_net for trade in trades if trade.pnl_net < 0]
    if not losers:
        return None
    return sum(losers) / len(losers)


def _format_optional(value: float | None, template: str, suffix: str = "") -> str:
    """Formate une métrique optionnelle sans inventer de valeur."""
    if value is None:
        return "n/a"
    if math.isinf(value):
        return "infini (aucune perte)"
    return f"{template.format(value)}{suffix}"


def _format_timestamp(timestamp_ms: int) -> str:
    """Formate un timestamp millisecondes en UTC lisible."""
    moment = datetime.datetime.fromtimestamp(timestamp_ms / 1000, tz=datetime.UTC)
    return moment.strftime("%Y-%m-%d %H:%M")


def format_report(result: BacktestResult) -> str:
    """Génère un rapport de backtest lisible dans le terminal."""
    lines = [
        "=" * 58,
        "                RAPPORT DE BACKTEST",
        "=" * 58,
        f"  Capital initial          : {result.starting_balance:,.2f} USDT",
        f"  Capital final            : {result.final_equity:,.2f} USDT",
        f"  Rendement total          : {result.total_return_pct:+.2f} %",
        f"  Rendement buy & hold     : {result.buy_hold_return_pct:+.2f} %",
        f"  PnL net                  : {result.net_pnl:+,.2f} USDT",
        f"  PnL brut (hors frais)    : {result.gross_pnl:+,.2f} USDT",
        f"  Frais totaux             : {result.total_fees:,.2f} USDT",
        "-" * 58,
        f"  Nombre de trades         : {result.num_trades} "
        f"({result.winning_trades} gagnants / {result.losing_trades} perdants)",
        f"  Taux de réussite         : {_format_optional(result.win_rate, '{:.1%}')}",
        f"  Gain moyen par trade     : {_format_optional(result.avg_win, '{:+,.2f}', ' USDT')}",
        f"  Perte moyenne par trade  : {_format_optional(result.avg_loss, '{:+,.2f}', ' USDT')}",
        f"  Profit factor            : {_format_optional(result.profit_factor, '{:.2f}')}",
        f"  Drawdown maximal         : {result.max_drawdown_pct:.2f} %",
        f"  Ratio de Sharpe          : {_format_optional(result.sharpe_ratio, '{:.4f}')}",
        "=" * 58,
    ]

    if result.trades:
        lines.append("")
        lines.append("  Détail des trades :")
        lines.append("-" * 58)
        for index, trade in enumerate(result.trades, 1):
            lines.append(
                f"  #{index:>3d}  {_format_timestamp(trade.entry_time)} -> "
                f"{_format_timestamp(trade.exit_time)}  "
                f"entrée={trade.entry_price:,.2f}  sortie={trade.exit_price:,.2f}  "
                f"qté={trade.quantity:.6f}"
            )
            lines.append(
                f"       PnL net={trade.pnl_net:+,.2f}  PnL brut={trade.pnl_gross:+,.2f}  "
                f"frais={trade.fees:.2f}  motif={trade.exit_reason}"
            )
        lines.append("-" * 58)

    lines.append("")
    return "\n".join(lines)
