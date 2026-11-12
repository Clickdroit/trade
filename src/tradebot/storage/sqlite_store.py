"""Persistance SQLite de l'état du Paper Trading.

Le fichier SQLite est la source de vérité : portefeuille, position ouverte,
transactions, décisions, bougies traitées, historique d'equity et état du bot.
Toutes les écritures d'un cycle sont regroupées dans **une seule transaction** :
une interruption ne peut pas laisser un portefeuille à moitié mis à jour.

Garanties
=========
* ``processed_candles`` a pour clé primaire (symbole, timeframe, horodatage) :
  une bougie ne peut être traitée qu'une seule fois, même après redémarrage.
* ``decisions`` et ``equity_history`` sont uniques par bougie.
* ``trades`` interdit deux transactions identiques (symbole, entrée, sortie).
* ``PRAGMA synchronous=FULL`` + transactions explicites : pas de perte silencieuse.
"""

from __future__ import annotations

import datetime
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from tradebot.portfolio.virtual_portfolio import ClosedTrade, Position

SCHEMA_VERSION = 1

STATUS_NOT_STARTED = "not_started"
STATUS_RUNNING = "running"
STATUS_STOPPED = "stopped"
STATUS_ERROR = "error"


class StorageError(RuntimeError):
    """Lecture ou écriture de la base impossible."""


class DuplicateCandleError(StorageError):
    """Bougie déjà traitée : aucun doublon ne doit être enregistré."""


@dataclass(frozen=True)
class BotState:
    """État complet du bot, persisté dans une ligne unique."""

    symbol: str
    timeframe: str
    mode: str
    starting_balance: float
    cash: float
    realized_pnl: float
    peak_equity: float
    day_start_equity: float
    day_start_date: str  # date UTC ISO, vide avant le premier cycle
    day_halted: bool
    last_processed_ts: int | None
    last_price: float
    status: str
    stop_requested: bool
    last_cycle_at: str | None


@dataclass(frozen=True)
class DecisionRecord:
    """Décision enregistrée pour une bougie."""

    candle_ts: int
    signal: str
    action: str
    reason: str
    price: float


@dataclass(frozen=True)
class CycleRecord:
    """Ensemble des écritures d'un cycle, appliquées atomiquement."""

    state: BotState
    position: Position | None
    candle_ts: int
    signal: str
    action: str
    reason: str
    price: float
    equity: float
    trade: ClosedTrade | None = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS bot_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    mode TEXT NOT NULL,
    starting_balance REAL NOT NULL,
    cash REAL NOT NULL,
    realized_pnl REAL NOT NULL,
    peak_equity REAL NOT NULL,
    day_start_equity REAL NOT NULL,
    day_start_date TEXT NOT NULL,
    day_halted INTEGER NOT NULL DEFAULT 0,
    last_processed_ts INTEGER,
    last_price REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    stop_requested INTEGER NOT NULL DEFAULT 0,
    last_cycle_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    symbol TEXT PRIMARY KEY,
    quantity REAL NOT NULL,
    entry_price REAL NOT NULL,
    entry_time INTEGER NOT NULL,
    entry_fee REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    entry_time INTEGER NOT NULL,
    exit_time INTEGER NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL NOT NULL,
    quantity REAL NOT NULL,
    pnl_gross REAL NOT NULL,
    pnl_net REAL NOT NULL,
    fees REAL NOT NULL,
    exit_reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (symbol, entry_time, exit_time)
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    candle_ts INTEGER NOT NULL,
    signal TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    price REAL NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (symbol, candle_ts)
);

CREATE TABLE IF NOT EXISTS processed_candles (
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    candle_ts INTEGER NOT NULL,
    processed_at TEXT NOT NULL,
    PRIMARY KEY (symbol, timeframe, candle_ts)
);

CREATE TABLE IF NOT EXISTS equity_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    candle_ts INTEGER NOT NULL,
    equity REAL NOT NULL,
    cash REAL NOT NULL,
    realized_pnl REAL NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (symbol, candle_ts)
);
"""


def _now_iso() -> str:
    """Horodatage UTC lisible, pour les colonnes de traçabilité."""
    return datetime.datetime.now(tz=datetime.UTC).isoformat(timespec="seconds")


class PaperStore:
    """Accès transactionnel à la base SQLite du Paper Trading."""

    def __init__(self, path: str | Path) -> None:
        """Ouvre (et crée si besoin) la base de données.

        Raises:
            StorageError: Base inaccessible ou schéma d'une version inconnue.
            OSError: Dossier impossible à créer.
        """
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(str(self._path), timeout=5.0, isolation_level=None)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=FULL")
            self._ensure_schema()
        except sqlite3.Error as exc:
            raise StorageError(f"Base de données inaccessible ({self._path}) : {exc}") from exc

    # ------------------------------------------------------------------
    # Connexion et transactions
    # ------------------------------------------------------------------

    def _ensure_schema(self) -> None:
        """Crée ou vérifie le schéma ; refuse une version inconnue."""
        version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        if version == SCHEMA_VERSION:
            return
        if version > SCHEMA_VERSION:
            raise StorageError(
                f"Base {self._path} en version {version}, plus récente que la version "
                f"supportée ({SCHEMA_VERSION}). Mettez à jour le projet."
            )
        self._conn.executescript(_SCHEMA)
        self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        """Transaction explicite : tout est validé ou rien ne l'est."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield self._conn
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")

    def close(self) -> None:
        """Ferme la connexion SQLite."""
        self._conn.close()

    def __enter__(self) -> PaperStore:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # État et position
    # ------------------------------------------------------------------

    def load_state(self) -> BotState | None:
        """Charge l'état du bot, ou ``None`` si aucun cycle n'a encore tourné."""
        row = self._conn.execute("SELECT * FROM bot_state WHERE id = 1").fetchone()
        if row is None:
            return None
        return BotState(
            symbol=row["symbol"],
            timeframe=row["timeframe"],
            mode=row["mode"],
            starting_balance=row["starting_balance"],
            cash=row["cash"],
            realized_pnl=row["realized_pnl"],
            peak_equity=row["peak_equity"],
            day_start_equity=row["day_start_equity"],
            day_start_date=row["day_start_date"],
            day_halted=bool(row["day_halted"]),
            last_processed_ts=row["last_processed_ts"],
            last_price=row["last_price"],
            status=row["status"],
            stop_requested=bool(row["stop_requested"]),
            last_cycle_at=row["last_cycle_at"],
        )

    def save_state(self, state: BotState) -> None:
        """Enregistre l'état du bot (une seule ligne)."""
        with self._transaction() as conn:
            self._write_state(conn, state)

    def load_position(self) -> Position | None:
        """Charge la position ouverte, s'il y en a une."""
        row = self._conn.execute("SELECT * FROM positions LIMIT 1").fetchone()
        if row is None:
            return None
        return Position(
            symbol=row["symbol"],
            quantity=row["quantity"],
            entry_price=row["entry_price"],
            entry_time=row["entry_time"],
            entry_fee=row["entry_fee"],
        )

    def _write_state(self, conn: sqlite3.Connection, state: BotState) -> None:
        conn.execute(
            """
            INSERT INTO bot_state (
                id, symbol, timeframe, mode, starting_balance, cash, realized_pnl,
                peak_equity, day_start_equity, day_start_date, day_halted,
                last_processed_ts, last_price, status, stop_requested, last_cycle_at,
                updated_at
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                symbol = excluded.symbol,
                timeframe = excluded.timeframe,
                mode = excluded.mode,
                starting_balance = excluded.starting_balance,
                cash = excluded.cash,
                realized_pnl = excluded.realized_pnl,
                peak_equity = excluded.peak_equity,
                day_start_equity = excluded.day_start_equity,
                day_start_date = excluded.day_start_date,
                day_halted = excluded.day_halted,
                last_processed_ts = excluded.last_processed_ts,
                last_price = excluded.last_price,
                status = excluded.status,
                stop_requested = excluded.stop_requested,
                last_cycle_at = excluded.last_cycle_at,
                updated_at = excluded.updated_at
            """,
            (
                state.symbol,
                state.timeframe,
                state.mode,
                state.starting_balance,
                state.cash,
                state.realized_pnl,
                state.peak_equity,
                state.day_start_equity,
                state.day_start_date,
                int(state.day_halted),
                state.last_processed_ts,
                state.last_price,
                state.status,
                int(state.stop_requested),
                state.last_cycle_at,
                _now_iso(),
            ),
        )

    def _write_position(self, conn: sqlite3.Connection, position: Position | None) -> None:
        conn.execute("DELETE FROM positions")
        if position is None:
            return
        conn.execute(
            """
            INSERT INTO positions (symbol, quantity, entry_price, entry_time, entry_fee)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                position.symbol,
                position.quantity,
                position.entry_price,
                position.entry_time,
                position.entry_fee,
            ),
        )

    # ------------------------------------------------------------------
    # Cycle
    # ------------------------------------------------------------------

    def record_cycle(self, record: CycleRecord) -> None:
        """Enregistre un cycle complet de façon atomique.

        Args:
            record: État, position, décision et transaction éventuelle.

        Raises:
            DuplicateCandleError: La bougie a déjà été traitée (aucune écriture).
            StorageError: Violation d'unicité ou erreur SQLite (rollback complet).
        """
        try:
            with self._transaction() as conn:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO processed_candles
                        (symbol, timeframe, candle_ts, processed_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        record.state.symbol,
                        record.state.timeframe,
                        record.candle_ts,
                        _now_iso(),
                    ),
                )
                if cursor.rowcount == 0:
                    raise DuplicateCandleError(
                        f"Bougie {record.candle_ts} déjà traitée pour {record.state.symbol} "
                        f"{record.state.timeframe}."
                    )
                conn.execute(
                    """
                    INSERT INTO decisions
                        (symbol, candle_ts, signal, action, reason, price, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.state.symbol,
                        record.candle_ts,
                        record.signal,
                        record.action,
                        record.reason,
                        record.price,
                        _now_iso(),
                    ),
                )
                if record.trade is not None:
                    trade = record.trade
                    conn.execute(
                        """
                        INSERT INTO trades (
                            symbol, entry_time, exit_time, entry_price, exit_price,
                            quantity, pnl_gross, pnl_net, fees, exit_reason, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            trade.symbol,
                            trade.entry_time,
                            trade.exit_time,
                            trade.entry_price,
                            trade.exit_price,
                            trade.quantity,
                            trade.pnl_gross,
                            trade.pnl_net,
                            trade.fees,
                            trade.exit_reason,
                            _now_iso(),
                        ),
                    )
                conn.execute(
                    """
                    INSERT INTO equity_history
                        (symbol, candle_ts, equity, cash, realized_pnl, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.state.symbol,
                        record.candle_ts,
                        record.equity,
                        record.state.cash,
                        record.state.realized_pnl,
                        _now_iso(),
                    ),
                )
                self._write_state(conn, record.state)
                self._write_position(conn, record.position)
        except DuplicateCandleError:
            raise
        except sqlite3.IntegrityError as exc:
            raise StorageError(
                f"Écriture refusée (doublon ou contrainte violée) : {exc}"
            ) from exc
        except sqlite3.Error as exc:
            raise StorageError(f"Écriture du cycle impossible : {exc}") from exc

    # ------------------------------------------------------------------
    # Lecture de l'historique
    # ------------------------------------------------------------------

    def trades(self, limit: int = 20) -> list[ClosedTrade]:
        """Dernières transactions clôturées, les plus récentes d'abord."""
        rows = self._conn.execute(
            "SELECT * FROM trades ORDER BY exit_time DESC, id DESC LIMIT ?",
            (max(1, limit),),
        ).fetchall()
        return [
            ClosedTrade(
                symbol=row["symbol"],
                entry_time=row["entry_time"],
                exit_time=row["exit_time"],
                entry_price=row["entry_price"],
                exit_price=row["exit_price"],
                quantity=row["quantity"],
                pnl_gross=row["pnl_gross"],
                pnl_net=row["pnl_net"],
                fees=row["fees"],
                exit_reason=row["exit_reason"],
            )
            for row in rows
        ]

    def decisions(self, limit: int = 20) -> list[DecisionRecord]:
        """Dernières décisions enregistrées, les plus récentes d'abord."""
        rows = self._conn.execute(
            "SELECT * FROM decisions ORDER BY candle_ts DESC, id DESC LIMIT ?",
            (max(1, limit),),
        ).fetchall()
        return [
            DecisionRecord(
                candle_ts=row["candle_ts"],
                signal=row["signal"],
                action=row["action"],
                reason=row["reason"],
                price=row["price"],
            )
            for row in rows
        ]

    def equity_points(self, limit: int = 20) -> list[tuple[int, float]]:
        """Derniers points d'equity (horodatage de bougie, valeur totale)."""
        rows = self._conn.execute(
            "SELECT candle_ts, equity FROM equity_history "
            "ORDER BY candle_ts DESC LIMIT ?",
            (max(1, limit),),
        ).fetchall()
        return [(row["candle_ts"], row["equity"]) for row in rows]

    def trade_count(self) -> int:
        """Nombre de transactions clôturées enregistrées."""
        return int(self._conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0])

    def total_fees(self) -> float:
        """Somme des frais des transactions clôturées."""
        value = self._conn.execute("SELECT COALESCE(SUM(fees), 0) FROM trades").fetchone()[0]
        return float(value)

    # ------------------------------------------------------------------
    # Contrôle de l'exécution et réinitialisation
    # ------------------------------------------------------------------

    def set_status(self, status: str, *, stop_requested: bool | None = None) -> None:
        """Met à jour l'état du bot (et éventuellement le drapeau d'arrêt)."""
        with self._transaction() as conn:
            conn.execute(
                "UPDATE bot_state SET status = ?, updated_at = ? WHERE id = 1",
                (status, _now_iso()),
            )
            if stop_requested is not None:
                conn.execute(
                    "UPDATE bot_state SET stop_requested = ? WHERE id = 1",
                    (int(stop_requested),),
                )

    def request_stop(self) -> None:
        """Pose le drapeau d'arrêt lu par une exécution continue."""
        with self._transaction() as conn:
            conn.execute(
                "UPDATE bot_state SET stop_requested = 1, updated_at = ? WHERE id = 1",
                (_now_iso(),),
            )

    def stop_requested(self) -> bool:
        """Indique si un arrêt a été demandé (``paper stop``)."""
        row = self._conn.execute("SELECT stop_requested FROM bot_state WHERE id = 1").fetchone()
        return bool(row["stop_requested"]) if row is not None else False

    def reset(self) -> dict[str, int]:
        """Vide l'état et l'historique, en conservant le schéma.

        Returns:
            Nombre de lignes supprimées par table.

        Raises:
            StorageError: Suppression impossible (rollback complet).
        """
        tables = (
            "trades",
            "decisions",
            "processed_candles",
            "equity_history",
            "positions",
            "bot_state",
        )
        counts: dict[str, int] = {}
        try:
            with self._transaction() as conn:
                for table in tables:
                    counts[table] = int(
                        conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
                    )
                    conn.execute(f"DELETE FROM {table}")  # noqa: S608
        except sqlite3.Error as exc:
            raise StorageError(f"Réinitialisation impossible : {exc}") from exc
        return counts
