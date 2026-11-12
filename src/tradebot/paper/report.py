"""Rendu terminal du Paper Trading (statut, historique, cycles)."""

from __future__ import annotations

from tradebot.domain.models import utc_datetime_from_ms
from tradebot.paper.engine import CycleOutcome, PortfolioSummary
from tradebot.portfolio.virtual_portfolio import ClosedTrade, Position
from tradebot.storage.sqlite_store import (
    STATUS_ERROR,
    STATUS_NOT_STARTED,
    STATUS_RUNNING,
    STATUS_STOPPED,
    DecisionRecord,
)

_LINE = "=" * 58

_STATUS_LABELS: dict[str, str] = {
    STATUS_NOT_STARTED: "non démarré",
    STATUS_RUNNING: "en cours",
    STATUS_STOPPED: "arrêté",
    STATUS_ERROR: "erreur (état à vérifier)",
}


def format_timestamp(timestamp_ms: int | None) -> str:
    """Formate un timestamp millisecondes en date UTC lisible."""
    if timestamp_ms is None:
        return "aucune"
    return utc_datetime_from_ms(timestamp_ms).strftime("%Y-%m-%d %H:%M")


def format_position(position: Position | None) -> str:
    """Décrit la position ouverte (quantité, prix d'entrée, horodatage)."""
    if position is None:
        return "aucune"
    return (
        f"{position.quantity:.8f} {position.symbol} @ {position.entry_price:,.2f} "
        f"(entrée {format_timestamp(position.entry_time)} UTC, "
        f"frais {position.entry_fee:,.4f} USDT)"
    )


def format_status(summary: PortfolioSummary) -> str:
    """Bloc de statut contenant tous les indicateurs demandés."""
    status = _STATUS_LABELS.get(summary.status, summary.status)
    lines = [
        _LINE,
        "            ÉTAT DU PAPER TRADING (100 % virtuel)",
        _LINE,
        f"  Capital initial          : {summary.starting_balance:,.2f} USDT",
        f"  Solde disponible         : {summary.cash:,.2f} USDT",
        f"  Valeur totale            : {summary.equity:,.2f} USDT",
        f"  PnL réalisé              : {summary.realized_pnl:+,.2f} USDT",
        f"  PnL latent               : {summary.unrealized_pnl:+,.2f} USDT",
        f"  Rendement total          : {summary.total_return_pct:+.2f} %",
        f"  Frais totaux             : {summary.total_fees:,.2f} USDT",
        f"  Drawdown                 : {summary.drawdown_pct:.2f} %",
        f"  Transactions             : {summary.trade_count}",
        f"  Position actuelle        : {format_position(summary.position)}",
        f"  Prix de référence        : {summary.mark_price:,.2f} USDT",
        f"  Dernière bougie traitée  : {format_timestamp(summary.last_candle_ts)} UTC",
        "  Limite journalière       : "
        + ("atteinte (entrées bloquées)" if summary.day_halted else "non atteinte"),
        f"  État du bot              : {status}",
        _LINE,
    ]
    lines.append(
        "  Rappel : simulation uniquement, aucun ordre réel, aucun fonds engagé."
    )
    return "\n".join(lines)


def format_cycle(outcome: CycleOutcome) -> str:
    """Résumé court d'un cycle."""
    return (
        f"Bougies traitées : {outcome.processed_candles} | "
        f"dernière bougie : {format_timestamp(outcome.last_candle_ts)} UTC | "
        f"actions : {', '.join(outcome.actions) or 'aucune'}"
    )


def format_history(
    trades: list[ClosedTrade], decisions: list[DecisionRecord], limit: int
) -> str:
    """Historique lisible des transactions et des décisions."""
    lines = [_LINE, "         HISTORIQUE DU PAPER TRADING (plus récent d'abord)", _LINE]
    lines.append(f"  Transactions ({len(trades)} / {limit} demandées) :")
    if not trades:
        lines.append("    aucune transaction clôturée")
    for index, trade in enumerate(trades, 1):
        lines.append(
            f"    #{index:>2d} {format_timestamp(trade.entry_time)} -> "
            f"{format_timestamp(trade.exit_time)} | "
            f"entrée {trade.entry_price:,.2f} | sortie {trade.exit_price:,.2f} | "
            f"qté {trade.quantity:.8f}"
        )
        lines.append(
            f"        PnL net {trade.pnl_net:+,.2f} USDT | PnL brut {trade.pnl_gross:+,.2f} | "
            f"frais {trade.fees:,.4f} | motif {trade.exit_reason}"
        )

    lines.append("")
    lines.append(f"  Décisions ({len(decisions)} / {limit} demandées) :")
    if not decisions:
        lines.append("    aucune décision enregistrée")
    for decision in decisions:
        lines.append(
            f"    {format_timestamp(decision.candle_ts)} | signal {decision.signal:<4} | "
            f"action {decision.action:<4} | prix {decision.price:,.2f} | "
            f"{decision.reason}"
        )
    lines.append(_LINE)
    return "\n".join(lines)
