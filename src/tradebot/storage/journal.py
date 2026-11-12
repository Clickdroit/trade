"""Append-only CSV journal for decisions and simulated trades."""

import csv
from datetime import UTC, datetime
from pathlib import Path

FIELDS = ["timestamp", "symbol", "signal", "price", "quantity", "mode", "reason"]


def record_event(
    path: Path,
    *,
    symbol: str,
    signal: str,
    price: float,
    quantity: float = 0.0,
    mode: str = "simulation",
    reason: str = "",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "symbol": symbol,
                "signal": signal,
                "price": price,
                "quantity": quantity,
                "mode": mode,
                "reason": reason,
            }
        )
