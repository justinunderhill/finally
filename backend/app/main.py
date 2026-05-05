"""FastAPI application entrypoint for the FinAlly trading workstation."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import chat, db
from app.config import STATIC_ROOT, load_env
from app.market.cache import PriceCache
from app.market.factory import create_market_data_source
from app.market.interface import MarketDataSource
from app.market.seed_prices import SEED_PRICES
from app.market.stream import create_stream_router
from app.portfolio import current_price, portfolio_summary, record_current_snapshot

price_cache = PriceCache()
market_source: MarketDataSource | None = None
snapshot_task: asyncio.Task[None] | None = None


class TickerRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)


class TradeRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    side: str
    quantity: float = Field(gt=0)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize persistence and market data background work."""
    global market_source, snapshot_task

    load_env()
    db.init_db()
    market_source = create_market_data_source(price_cache)
    await market_source.start(_tracked_tickers())
    record_current_snapshot(price_cache)
    snapshot_task = asyncio.create_task(_record_snapshots(), name="portfolio-snapshots")
    try:
        yield
    finally:
        if snapshot_task is not None:
            snapshot_task.cancel()
            try:
                await snapshot_task
            except asyncio.CancelledError:
                pass
            snapshot_task = None
        if market_source is not None:
            await market_source.stop()
            market_source = None


app = FastAPI(title="FinAlly Backend", lifespan=lifespan)
app.include_router(create_stream_router(price_cache))


@app.get("/api/health")
async def api_health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/prices")
async def get_prices() -> dict[str, dict[str, Any]]:
    return {ticker: update.to_dict() for ticker, update in price_cache.get_all().items()}


@app.get("/api/tickers")
async def get_tickers() -> list[str]:
    return list(SEED_PRICES)


@app.get("/api/watchlist")
async def get_watchlist() -> list[dict[str, Any]]:
    result = []
    for ticker in db.get_watchlist():
        update = price_cache.get(ticker)
        result.append(
            {
                "ticker": ticker,
                "price": update.price if update else None,
                "change": update.change if update else 0,
                "change_percent": update.change_percent if update else 0,
                "direction": update.direction if update else "flat",
            }
        )
    return result


@app.post("/api/watchlist")
async def add_watchlist(payload: TickerRequest) -> dict[str, str]:
    try:
        ticker = db.normalize_ticker(payload.ticker)
        db.add_watchlist_ticker(ticker)
        if market_source is not None:
            await market_source.add_ticker(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ticker": ticker, "status": "added"}


@app.delete("/api/watchlist/{ticker}")
async def remove_watchlist(ticker: str) -> dict[str, str]:
    try:
        ticker = db.normalize_ticker(ticker)
        db.remove_watchlist_ticker(ticker)
        if market_source is not None and ticker not in _held_tickers():
            await market_source.remove_ticker(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ticker": ticker, "status": "removed"}


@app.get("/api/portfolio")
async def get_portfolio() -> dict[str, Any]:
    return portfolio_summary(price_cache)


@app.get("/api/portfolio/history")
async def get_portfolio_history() -> list[dict[str, Any]]:
    return db.get_portfolio_history()


@app.post("/api/portfolio/trade")
async def trade(payload: TradeRequest) -> dict[str, Any]:
    try:
        ticker = db.normalize_ticker(payload.ticker)
        price = current_price(price_cache, ticker)
        trade_result = db.execute_trade(ticker, payload.side, payload.quantity, price)
        db.add_watchlist_ticker(ticker)
        if market_source is not None:
            await market_source.add_ticker(ticker)
        record_current_snapshot(price_cache)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"trade": trade_result, "portfolio": portfolio_summary(price_cache)}


@app.post("/api/chat")
async def post_chat(payload: ChatRequest) -> dict[str, Any]:
    user_message = payload.message.strip()
    db.save_chat_message("user", user_message)

    context = {
        "portfolio": portfolio_summary(price_cache),
        "watchlist": db.get_watchlist(),
    }
    assistant = await run_in_threadpool(chat.call_llm, user_message, context)
    actions = await _apply_assistant_actions(assistant)
    message = assistant.get("message") or "I reviewed the portfolio."
    db.save_chat_message("assistant", message, actions)
    return {"message": message, "actions": actions, "portfolio": portfolio_summary(price_cache)}


async def _apply_assistant_actions(assistant: dict[str, Any]) -> dict[str, Any]:
    executed_trades = []
    watchlist_changes = []
    errors = []

    for change in assistant.get("watchlist_changes", []):
        try:
            ticker = db.normalize_ticker(str(change.get("ticker", "")))
            action = str(change.get("action", "")).lower()
            if action == "add":
                db.add_watchlist_ticker(ticker)
                if market_source is not None:
                    await market_source.add_ticker(ticker)
            elif action == "remove":
                db.remove_watchlist_ticker(ticker)
                if market_source is not None and ticker not in _held_tickers():
                    await market_source.remove_ticker(ticker)
            else:
                raise ValueError("watchlist action must be add or remove")
            watchlist_changes.append({"ticker": ticker, "action": action})
        except ValueError as exc:
            errors.append(str(exc))

    for trade in assistant.get("trades", []):
        try:
            ticker = db.normalize_ticker(str(trade.get("ticker", "")))
            side = str(trade.get("side", "")).lower()
            quantity = float(trade.get("quantity", 0))
            price = current_price(price_cache, ticker)
            executed = db.execute_trade(ticker, side, quantity, price)
            db.add_watchlist_ticker(ticker)
            if market_source is not None:
                await market_source.add_ticker(ticker)
            executed_trades.append(executed)
        except (TypeError, ValueError) as exc:
            errors.append(str(exc))

    if executed_trades:
        record_current_snapshot(price_cache)
    return {"trades": executed_trades, "watchlist_changes": watchlist_changes, "errors": errors}


async def _record_snapshots() -> None:
    while True:
        await asyncio.sleep(30)
        record_current_snapshot(price_cache)


def _held_tickers() -> set[str]:
    return {position["ticker"] for position in db.get_positions()}


def _tracked_tickers() -> list[str]:
    return sorted(set(db.get_watchlist()) | _held_tickers())


if STATIC_ROOT.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_ROOT / "assets"), name="assets")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_ROOT / "index.html")
