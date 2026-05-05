"""Portfolio calculations around persisted positions and live prices."""

from __future__ import annotations

from typing import Any

from app import db
from app.market.cache import PriceCache


def current_price(cache: PriceCache, ticker: str, fallback: float = 0.0) -> float:
    update = cache.get(ticker)
    return float(update.price) if update else fallback


def portfolio_summary(cache: PriceCache) -> dict[str, Any]:
    """Build the current portfolio state using live prices where available."""
    cash = db.get_cash_balance()
    positions = []
    positions_value = 0.0
    cost_basis = 0.0

    for row in db.get_positions():
        price = current_price(cache, row["ticker"], row["avg_cost"])
        quantity = float(row["quantity"])
        avg_cost = float(row["avg_cost"])
        market_value = quantity * price
        basis = quantity * avg_cost
        unrealized_pl = market_value - basis
        unrealized_pl_percent = (unrealized_pl / basis * 100) if basis else 0.0
        positions_value += market_value
        cost_basis += basis
        positions.append(
            {
                "ticker": row["ticker"],
                "quantity": round(quantity, 6),
                "avg_cost": round(avg_cost, 2),
                "current_price": round(price, 2),
                "market_value": round(market_value, 2),
                "unrealized_pl": round(unrealized_pl, 2),
                "unrealized_pl_percent": round(unrealized_pl_percent, 2),
                "updated_at": row["updated_at"],
            }
        )

    total_value = cash + positions_value
    total_pl = positions_value - cost_basis
    total_pl_percent = (total_pl / cost_basis * 100) if cost_basis else 0.0
    return {
        "cash_balance": round(cash, 2),
        "positions_value": round(positions_value, 2),
        "total_value": round(total_value, 2),
        "unrealized_pl": round(total_pl, 2),
        "unrealized_pl_percent": round(total_pl_percent, 2),
        "positions": positions,
        "recent_trades": db.get_recent_trades(),
    }


def record_current_snapshot(cache: PriceCache) -> None:
    summary = portfolio_summary(cache)
    db.record_snapshot(summary["total_value"])
