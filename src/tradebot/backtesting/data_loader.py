"""Chargement de données OHLCV pour le backtesting (CSV local ou CCXT)."""

from __future__ import annotations

import csv
import time
from pathlib import Path

import ccxt

from tradebot.domain.models import TIMEFRAME_MS, Candle

#: Nombre maximal de bougies par requête (limite courante des exchanges).
_CHUNK_SIZE = 1000

#: Garde-fou contre une pagination qui ne progresserait pas.
_MAX_CHUNKS = 1000

#: Colonnes obligatoires d'un CSV de bougies.
REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")


class DataLoadError(RuntimeError):
    """Erreur de chargement de données historiques, avec un message actionnable."""


def _normalise(candles: list[Candle]) -> list[Candle]:
    """Trie les bougies par timestamp et supprime les doublons."""
    unique: dict[int, Candle] = {candle.timestamp: candle for candle in candles}
    return [unique[timestamp] for timestamp in sorted(unique)]


def load_from_exchange(
    symbol: str,
    timeframe: str = "1h",
    since_days: int = 30,
    sandbox: bool = True,
) -> list[Candle]:
    """Télécharge des bougies OHLCV publiques via CCXT.

    Aucune clé API n'est utilisée et aucun ordre n'est envoyé : seuls les
    endpoints publics de données de marché sont appelés.

    Args:
        symbol: Paire, par exemple ``BTC/USDT``.
        timeframe: Intervalle supporté (voir :data:`TIMEFRAME_MS`).
        since_days: Profondeur historique demandée, en jours.
        sandbox: Utilise le Testnet Binance (données publiques uniquement).

    Returns:
        Bougies triées et sans doublon.

    Raises:
        DataLoadError: Paramètres invalides, erreur réseau/exchange, ou aucune
            donnée reçue.
    """
    if not symbol or "/" not in symbol:
        raise DataLoadError(f"Symbole invalide : {symbol!r} (attendu, ex. BTC/USDT).")
    if timeframe not in TIMEFRAME_MS:
        supported = ", ".join(sorted(TIMEFRAME_MS))
        raise DataLoadError(f"Timeframe non supporté : {timeframe!r}. Choix : {supported}.")
    if since_days <= 0:
        raise DataLoadError("La profondeur historique doit être d'au moins un jour.")

    exchange = ccxt.binance({"enableRateLimit": True})
    if sandbox:
        exchange.set_sandbox_mode(True)

    timeframe_ms = TIMEFRAME_MS[timeframe]
    since_ms = int((time.time() - since_days * 86_400) * 1000)

    candles: list[Candle] = []
    current_since = since_ms

    for _ in range(_MAX_CHUNKS):
        try:
            raw = exchange.fetch_ohlcv(symbol, timeframe, since=current_since, limit=_CHUNK_SIZE)
        except ccxt.BaseError as exc:
            raise DataLoadError(f"Téléchargement {symbol} {timeframe} impossible : {exc}") from exc

        if not raw:
            break

        for row in raw:
            candles.append(
                Candle(
                    timestamp=int(row[0]),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
            )

        next_since = int(raw[-1][0]) + timeframe_ms
        if next_since <= current_since:
            break
        current_since = next_since

        if len(raw) < _CHUNK_SIZE:
            break

    result = _normalise(candles)
    if not result:
        raise DataLoadError(
            f"Aucune bougie reçue pour {symbol} {timeframe} sur {since_days} jours."
        )

    # Une bougie dont la période n'est pas terminée n'a pas de clôture définitive.
    # L'utiliser reviendrait à connaître son prix final avant la fin de la bougie.
    now_ms = int(time.time() * 1000)
    closed = [candle for candle in result if candle.timestamp + timeframe_ms <= now_ms]
    if not closed:
        raise DataLoadError(
            f"Aucune bougie clôturée pour {symbol} {timeframe} sur {since_days} jours."
        )
    return closed


def load_from_csv(path: Path) -> list[Candle]:
    """Charge des bougies OHLCV depuis un fichier CSV local.

    Le fichier doit contenir l'en-tête
    ``timestamp,open,high,low,close,volume`` (timestamp en millisecondes).
    L'ordre doit être strictement croissant : un fichier désordonné ou
    dupliqué est refusé plutôt que corrigé silencieusement.

    Raises:
        DataLoadError: Fichier absent, illisible, colonnes manquantes, valeur
            invalide, ordre incorrect ou fichier vide.
    """
    if not path.exists():
        raise DataLoadError(f"Fichier CSV introuvable : {path}")
    if not path.is_file():
        raise DataLoadError(f"Le chemin CSV n'est pas un fichier : {path}")

    candles: list[Candle] = []
    previous_timestamp: int | None = None

    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise DataLoadError(f"Le fichier CSV est vide : {path}")

            missing = [column for column in REQUIRED_COLUMNS if column not in reader.fieldnames]
            if missing:
                raise DataLoadError(
                    f"Colonnes manquantes dans {path} : {', '.join(missing)}. "
                    f"En-tête attendu : {', '.join(REQUIRED_COLUMNS)}."
                )

            for line_number, row in enumerate(reader, start=2):
                try:
                    candle = Candle(
                        timestamp=int(row["timestamp"]),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row["volume"]),
                    )
                except (TypeError, ValueError) as exc:
                    raise DataLoadError(
                        f"Ligne {line_number} invalide dans {path} : {row}"
                    ) from exc

                if previous_timestamp is not None and candle.timestamp <= previous_timestamp:
                    raise DataLoadError(
                        f"Ligne {line_number} : bougies non strictement chronologiques "
                        f"dans {path} ({candle.timestamp} après {previous_timestamp})."
                    )
                previous_timestamp = candle.timestamp
                candles.append(candle)
    except OSError as exc:
        raise DataLoadError(f"Lecture impossible de {path} : {exc}") from exc

    if not candles:
        raise DataLoadError(f"Le fichier CSV ne contient aucune bougie : {path}")
    return candles


def save_to_csv(candles: list[Candle], path: Path) -> None:
    """Sauvegarde des bougies au format CSV, pour un backtest hors ligne."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["timestamp", "open", "high", "low", "close", "volume"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for candle in candles:
            writer.writerow(
                {
                    "timestamp": candle.timestamp,
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "volume": candle.volume,
                }
            )
