"""Cycle de Paper Trading : décision, risque, exécution simulée et persistance.

Déroulé d'un cycle
==================
1. contrôle de cohérence de l'état restauré (aucune transaction si incohérent) ;
2. récupération des bougies et rejet des bougies non clôturées ;
3. sélection des bougies jamais traitées, dans l'ordre chronologique ;
4. pour chaque bougie : changement de jour UTC, limite de perte journalière,
   stop-loss, signal MM10/MM30, exécution simulée ;
5. écriture atomique (bougie traitée + décision + transaction + état) ;
6. résumé du portefeuille.

Prix d'exécution
================
* Une décision est prise **à la clôture** d'une bougie ; l'exécution simulée se
  fait à ce prix de clôture, dégradé par le slippage (achat plus cher, vente
  moins chère). C'est le seul prix observable au moment où la décision est
  prise en direct.
* Le backtest exécute le même type de signal à l'ouverture de la bougie
  suivante, pour ne jamais réutiliser un prix de clôture comme prix d'exécution
  dans une série historique (détail dans docs/09-paper-trading.md).
* Le stop-loss n'est jamais évalué sur la bougie d'entrée : le plus bas de cette
  bougie peut précéder l'achat.

Priorités de sortie
===================
1. stop-loss (protection du capital) ;
2. signal de vente MM ;
3. sortie sur limite de perte journalière, uniquement si
   ``CLOSE_POSITION_ON_DAILY_LOSS=true``.
La limite de perte journalière **bloque les entrées** ; elle ne ferme jamais une
position par défaut.

Garanties
=========
* Aucune opération si les données sont invalides (bougies, prix, état).
* Aucune opération si l'état du portefeuille est incohérent.
* Une bougie traitée n'est jamais retraitée, même après redémarrage.
"""

from __future__ import annotations

import datetime
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, replace

from tradebot.config import Settings
from tradebot.domain.models import (
    EXIT_DAILY_LOSS,
    EXIT_SIGNAL,
    EXIT_STOP_LOSS,
    Candle,
    Signal,
    utc_date_from_ms,
    validate_candles,
)
from tradebot.exchange.market import MarketDataError, MarketSource
from tradebot.paper.broker import SimulatedBroker
from tradebot.portfolio.virtual_portfolio import (
    ClosedTrade,
    PortfolioStateError,
    Position,
    VirtualPortfolio,
)
from tradebot.risk.manager import RiskLimits, assess_entry, daily_loss_limit_reached
from tradebot.safety import PAPER_MODE, assert_paper_mode
from tradebot.storage.sqlite_store import (
    STATUS_ERROR,
    STATUS_NOT_STARTED,
    STATUS_RUNNING,
    STATUS_STOPPED,
    BotState,
    CycleRecord,
    DuplicateCandleError,
    PaperStore,
    StorageError,
)
from tradebot.strategy.moving_average import crossover_signal

logger = logging.getLogger(__name__)

ACTION_BUY = "BUY"
ACTION_SELL = "SELL"
ACTION_HOLD = "HOLD"

#: Nombre maximal de bougies demandées en une fois à la source de marché.
MAX_FETCH_LIMIT = 1000


class PaperTradingError(RuntimeError):
    """Erreur fonctionnelle du cycle de Paper Trading."""


@dataclass(frozen=True)
class PortfolioSummary:
    """Photographie de l'état du portefeuille virtuel."""

    starting_balance: float
    cash: float
    equity: float
    mark_price: float
    realized_pnl: float
    unrealized_pnl: float
    total_return_pct: float
    drawdown_pct: float
    position: Position | None
    trade_count: int
    total_fees: float
    day_halted: bool
    status: str
    last_candle_ts: int | None

    @property
    def total_pnl(self) -> float:
        """PnL cumulé (réalisé + latent)."""
        return self.realized_pnl + self.unrealized_pnl


@dataclass(frozen=True)
class CycleOutcome:
    """Résultat d'un cycle de Paper Trading."""

    processed_candles: int
    last_candle_ts: int | None
    actions: tuple[str, ...]
    summary: PortfolioSummary


def _now_iso() -> str:
    """Horodatage UTC lisible."""
    return datetime.datetime.now(tz=datetime.UTC).isoformat(timespec="seconds")


class PaperTrader:
    """Orchestre le portefeuille virtuel, les risques et la persistance."""

    def __init__(
        self,
        settings: Settings,
        store: PaperStore,
        market: MarketSource | None,
        *,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        """Charge (ou initialise) l'état persisté.

        Args:
            settings: Configuration validée.
            store: Base SQLite du Paper Trading.
            market: Source de bougies clôturées ; ``None`` suffit pour ``status``.
            sleeper: Fonction d'attente, injectable dans les tests.

        Raises:
            PaperTradingError: État persisté incohérent avec la configuration.
            LiveTradingForbiddenError: Mode d'exécution non simulé.
        """
        assert_paper_mode(settings.execution_mode)
        self._settings = settings
        self._store = store
        self._market = market
        self._sleeper = sleeper
        self._limits = RiskLimits(
            max_position_fraction=settings.max_position_fraction,
            max_daily_loss_fraction=settings.max_daily_loss_fraction,
        )

        stored = store.load_state()
        self._assert_same_market(stored)
        self._state = stored if stored is not None else self._initial_state()
        self._portfolio = VirtualPortfolio(
            starting_balance=self._state.starting_balance,
            fee_rate=settings.fee_rate,
            cash=self._state.cash,
            realized_pnl=self._state.realized_pnl,
            peak_equity=self._state.peak_equity,
        )
        position = store.load_position()
        if position is not None:
            try:
                self._portfolio.load_position(position)
            except PortfolioStateError as exc:
                raise PaperTradingError(f"Position persistée invalide : {exc}") from exc
        self._broker = SimulatedBroker(self._portfolio, slippage_pct=settings.slippage_pct)

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _initial_state(self) -> BotState:
        """État d'un Paper Trading jamais démarré."""
        starting = self._settings.starting_balance
        return BotState(
            symbol=self._settings.symbol,
            timeframe=self._settings.timeframe,
            mode=PAPER_MODE,
            starting_balance=starting,
            cash=starting,
            realized_pnl=0.0,
            peak_equity=starting,
            day_start_equity=starting,
            day_start_date="",
            day_halted=False,
            last_processed_ts=None,
            last_price=0.0,
            status=STATUS_NOT_STARTED,
            stop_requested=False,
            last_cycle_at=None,
        )

    def _assert_same_market(self, state: BotState | None) -> None:
        """Refuse de continuer un état enregistré pour une autre paire/timeframe."""
        if state is None:
            return
        if state.symbol != self._settings.symbol or state.timeframe != self._settings.timeframe:
            raise PaperTradingError(
                f"État enregistré pour {state.symbol} {state.timeframe}, configuration "
                f"{self._settings.symbol} {self._settings.timeframe}. "
                "Utilisez « paper reset » pour repartir de zéro."
            )

    def start(self) -> None:
        """Persiste l'état initial et marque le bot comme en cours d'exécution."""
        if self._store.load_state() is None:
            self._store.save_state(self._state)
        self._store.set_status(STATUS_RUNNING, stop_requested=False)
        self._state = replace(self._state, status=STATUS_RUNNING, stop_requested=False)

    # ------------------------------------------------------------------
    # Cycle
    # ------------------------------------------------------------------

    def run_cycle(self) -> CycleOutcome:
        """Exécute un cycle complet.

        Returns:
            Le nombre de bougies traitées, les actions et le résumé du portefeuille.

        Raises:
            PortfolioStateError: État du portefeuille incohérent (aucune transaction).
            PaperTradingError: Données invalides ou source de marché absente.
            MarketDataError: Données de marché indisponibles.
            StorageError: Écriture impossible.
        """
        if self._market is None:
            raise PaperTradingError("Aucune source de marché configurée.")
        self._portfolio.assert_consistent(self._state.last_price or None)

        candles = self._fetch_candles()
        pending = self._pending_candles(candles)
        if not pending:
            logger.info("Aucune nouvelle bougie clôturée à traiter.")
            return CycleOutcome(0, self._state.last_processed_ts, (), self.summary())

        actions: list[str] = []
        for index, candle in pending:
            action = self._process_candle(index, candle, candles)
            if action is not None:
                actions.append(action)
        return CycleOutcome(
            processed_candles=len(pending),
            last_candle_ts=self._state.last_processed_ts,
            actions=tuple(actions),
            summary=self.summary(),
        )

    def _fetch_candles(self) -> list[Candle]:
        """Récupère et valide les bougies clôturées."""
        if self._market is None:  # pragma: no cover - vérifié par run_cycle
            raise PaperTradingError("Aucune source de marché configurée.")
        limit = min(
            MAX_FETCH_LIMIT,
            self._settings.long_window + 2 + self._settings.catchup_max_candles,
        )
        candles = self._market.fetch_closed_candles(limit)
        if not candles:
            raise PaperTradingError("Aucune bougie clôturée reçue.")
        try:
            validate_candles(candles)
        except ValueError as exc:
            raise PaperTradingError(f"Données de marché invalides : {exc}") from exc
        return candles

    def _pending_candles(self, candles: list[Candle]) -> list[tuple[int, Candle]]:
        """Sélectionne les bougies jamais traitées, les plus anciennes d'abord.

        Au premier démarrage, seule la dernière bougie clôturée est traitée :
        l'historique sert uniquement au calcul des moyennes mobiles.
        """
        indexed = list(enumerate(candles))
        last = self._state.last_processed_ts
        if last is None:
            return indexed[-1:]
        pending = [(index, candle) for index, candle in indexed if candle.timestamp > last]
        maximum = self._settings.catchup_max_candles
        # Traiter le plus ancien lot en premier : ne jamais sauter une période
        # lorsque le retard dépasse la limite de rattrapage d'un cycle.
        return pending[:maximum] if len(pending) > maximum else pending

    def _process_candle(
        self, index: int, candle: Candle, candles: list[Candle]
    ) -> str | None:
        """Traite une bougie clôturée : décision, exécution, persistance."""
        closes = [item.close for item in candles[: index + 1]]
        signal = crossover_signal(closes, self._settings.short_window, self._settings.long_window)
        self._roll_day(candle)

        equity_close = self._portfolio.equity(candle.close)
        if not self._state.day_halted and self._daily_loss_hit(equity_close):
            self._state = replace(self._state, day_halted=True)
            logger.warning(
                "Limite de perte journalière atteinte le %s : nouvelles entrées bloquées.",
                self._state.day_start_date,
            )

        action, reason, price, trade = self._decide(candle, signal)
        equity = self._portfolio.mark(candle.close)
        # L'état persisté est la photographie exacte du portefeuille : sans cette
        # synchronisation, un redémarrage repartirait d'une trésorerie périmée.
        new_state = replace(
            self._state,
            cash=self._portfolio.cash,
            realized_pnl=self._portfolio.realized_pnl,
            peak_equity=self._portfolio.peak_equity,
            last_processed_ts=candle.timestamp,
            last_price=candle.close,
            last_cycle_at=_now_iso(),
        )
        record = CycleRecord(
            state=new_state,
            position=self._portfolio.position,
            candle_ts=candle.timestamp,
            signal=str(signal),
            action=action,
            reason=reason,
            price=price,
            equity=equity,
            trade=trade,
        )
        try:
            self._store.record_cycle(record)
        except DuplicateCandleError:
            logger.warning("Bougie %s déjà enregistrée : ignorée.", candle.timestamp)
            return None
        self._state = new_state
        return None if action == ACTION_HOLD else action

    def _roll_day(self, candle: Candle) -> None:
        """Change la référence journalière UTC (et réarme la limite de perte)."""
        day = utc_date_from_ms(candle.timestamp).isoformat()
        if day == self._state.day_start_date:
            return
        self._state = replace(
            self._state,
            day_start_date=day,
            day_start_equity=self._portfolio.equity(candle.open),
            day_halted=False,
        )
        logger.info("Nouvelle journée UTC %s : référence d'equity %.2f.", day,
                    self._state.day_start_equity)

    def _daily_loss_hit(self, equity: float) -> bool:
        """Évalue la limite de perte journalière sans jamais interrompre le cycle."""
        try:
            return daily_loss_limit_reached(
                self._state.day_start_equity, equity, self._limits
            )
        except ValueError as exc:
            logger.error("Limite journalière non évaluable : %s", exc)
            return False

    def _decide(
        self, candle: Candle, signal: Signal
    ) -> tuple[str, str, float, ClosedTrade | None]:
        """Détermine l'action de la bougie et l'exécute si nécessaire.

        Returns:
            ``(action, motif, prix de référence, transaction éventuelle)``.
        """
        position = self._portfolio.position
        if position is not None:
            return self._decide_exit(candle, signal, position)

        if self._state.day_halted:
            return ACTION_HOLD, "limite de perte journalière atteinte", candle.close, None
        if signal is not Signal.BUY:
            return ACTION_HOLD, f"signal {signal}", candle.close, None

        fill_price = self._broker.buy_price(candle.close)
        assessment = assess_entry(
            equity=self._portfolio.equity(candle.close),
            cash=self._portfolio.cash,
            price=fill_price,
            fee_rate=self._portfolio.fee_rate,
            limits=self._limits,
        )
        if not assessment.allowed:
            return ACTION_HOLD, assessment.reason, candle.close, None

        fill = self._broker.buy(
            self._settings.symbol,
            candle.close,
            assessment.quantity,
            candle.timestamp,
            "croisement MM haussier",
        )
        logger.info(
            "Achat simulé : %.8f %s à %.2f (frais %.4f, equity %.2f).",
            fill.quantity,
            fill.symbol,
            fill.price,
            fill.fee,
            self._portfolio.equity(candle.close),
        )
        return ACTION_BUY, "croisement MM haussier", fill.price, None

    def _decide_exit(
        self, candle: Candle, signal: Signal, position: Position
    ) -> tuple[str, str, float, ClosedTrade | None]:
        """Applique les priorités de sortie : stop-loss, signal, limite journalière."""
        if candle.timestamp > position.entry_time:
            stop_level = position.entry_price * (1 - self._settings.stop_loss_fraction)
            stop_fill = self._broker.stop_fill_price(candle, stop_level)
            if stop_fill is not None:
                trade = self._broker.sell_at(stop_fill, candle.timestamp, EXIT_STOP_LOSS)
                logger.warning(
                    "Stop-loss exécuté à %.2f (entrée %.2f, PnL net %+.2f).",
                    trade.exit_price,
                    trade.entry_price,
                    trade.pnl_net,
                )
                return ACTION_SELL, EXIT_STOP_LOSS, trade.exit_price, trade

        if signal is Signal.SELL:
            trade = self._broker.sell(candle.close, candle.timestamp, EXIT_SIGNAL)
            logger.info("Vente simulée à %.2f (PnL net %+.2f).", trade.exit_price, trade.pnl_net)
            return ACTION_SELL, EXIT_SIGNAL, trade.exit_price, trade

        if self._state.day_halted and self._settings.close_on_daily_loss:
            trade = self._broker.sell(candle.close, candle.timestamp, EXIT_DAILY_LOSS)
            logger.warning(
                "Sortie sur limite journalière à %.2f (PnL net %+.2f).",
                trade.exit_price,
                trade.pnl_net,
            )
            return ACTION_SELL, EXIT_DAILY_LOSS, trade.exit_price, trade

        return ACTION_HOLD, "position ouverte", candle.close, None

    # ------------------------------------------------------------------
    # Exécution continue et résumé
    # ------------------------------------------------------------------

    def run_forever(
        self,
        *,
        poll_seconds: int | None = None,
        on_outcome: Callable[[CycleOutcome], None] | None = None,
    ) -> None:
        """Exécute des cycles successifs jusqu'à ``paper stop`` ou interruption.

        Une erreur de données de marché n'entraîne aucune transaction : le cycle
        est simplement retenté au suivant. ``on_outcome`` reçoit chaque cycle
        ayant traité au moins une bougie (affichage du résumé).
        """
        interval = self._settings.poll_seconds if poll_seconds is None else poll_seconds
        if interval <= 0:
            raise ValueError("poll_seconds doit être strictement positif.")
        self.start()
        failed = False
        try:
            while True:
                if self._store.stop_requested():
                    logger.info("Arrêt demandé : sortie propre.")
                    break
                try:
                    outcome = self.run_cycle()
                except MarketDataError as exc:
                    logger.warning("Cycle ignoré (données indisponibles) : %s", exc)
                else:
                    logger.info(
                        "Cycle terminé : %d bougie(s), actions %s.",
                        outcome.processed_candles,
                        ", ".join(outcome.actions) or "aucune",
                    )
                    if on_outcome is not None and outcome.processed_candles:
                        on_outcome(outcome)
                if self._store.stop_requested():
                    logger.info("Arrêt demandé : sortie propre.")
                    break
                self._sleeper(interval)
        except (PortfolioStateError, StorageError):
            failed = True
            self._store.set_status(STATUS_ERROR)
            raise
        finally:
            if not failed:
                self._store.set_status(STATUS_STOPPED)

    def run_once(self) -> CycleOutcome:
        """Exécute un seul cycle et marque le bot comme arrêté."""
        self.start()
        try:
            return self.run_cycle()
        finally:
            self._store.set_status(STATUS_STOPPED)
            self._state = replace(self._state, status=STATUS_STOPPED)

    def summary(self, mark_price: float | None = None) -> PortfolioSummary:
        """Résumé du portefeuille, sans accès réseau."""
        price = self._state.last_price if mark_price is None else mark_price
        starting = self._portfolio.starting_balance
        equity = self._portfolio.equity(price) if price > 0 else self._portfolio.cash
        unrealized = self._portfolio.unrealized_pnl(price) if price > 0 else 0.0
        return PortfolioSummary(
            starting_balance=starting,
            cash=self._portfolio.cash,
            equity=equity,
            mark_price=price,
            realized_pnl=self._portfolio.realized_pnl,
            unrealized_pnl=unrealized,
            total_return_pct=(equity / starting - 1) * 100 if starting > 0 else 0.0,
            drawdown_pct=self._portfolio.drawdown_pct(price) if price > 0 else 0.0,
            position=self._portfolio.position,
            trade_count=self._store.trade_count(),
            total_fees=self._store.total_fees(),
            day_halted=self._state.day_halted,
            status=self._state.status,
            last_candle_ts=self._state.last_processed_ts,
        )
