"""LLM and mock chat behavior for FinAlly."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from app import db

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "openrouter/openai/gpt-oss-120b"


def build_mock_response(message: str, context: dict[str, Any]) -> dict[str, Any]:
    """Return deterministic assistant output for local dev and tests."""
    lower = message.lower()
    trades: list[dict[str, Any]] = []
    watchlist_changes: list[dict[str, str]] = []

    if "buy" in lower:
        ticker = _extract_ticker(message, context.get("watchlist", [])) or "AAPL"
        trades.append({"ticker": ticker, "side": "buy", "quantity": 1})
    elif "sell" in lower:
        positions = context.get("portfolio", {}).get("positions", [])
        ticker = positions[0]["ticker"] if positions else "AAPL"
        trades.append({"ticker": ticker, "side": "sell", "quantity": 1})
    elif "add" in lower or "watch" in lower:
        ticker = _extract_ticker(message, context.get("watchlist", [])) or "AMD"
        watchlist_changes.append({"ticker": ticker, "action": "add"})

    total_value = context.get("portfolio", {}).get("total_value", 0)
    cash = context.get("portfolio", {}).get("cash_balance", 0)
    return {
        "message": (
            f"Portfolio value is ${total_value:,.2f} with ${cash:,.2f} in cash. "
            "I will keep actions conservative in this simulated account."
        ),
        "trades": trades,
        "watchlist_changes": watchlist_changes,
    }


def call_llm(message: str, context: dict[str, Any]) -> dict[str, Any]:
    """Call OpenRouter for structured JSON, falling back to mock behavior."""
    if os.environ.get("LLM_MOCK", "").lower() == "true":
        return build_mock_response(message, context)

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return build_mock_response(message, context)

    prompt = {
        "portfolio": context.get("portfolio"),
        "watchlist": context.get("watchlist"),
        "recent_messages": db.get_recent_chat_messages(),
        "user_message": message,
    }
    body = {
        "model": OPENROUTER_MODEL,
        "provider": {"only": ["Cerebras"]},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are FinAlly, a concise AI trading assistant for a simulated portfolio. "
                    "Respond only as valid JSON with keys: message, trades, watchlist_changes. "
                    "Trades must use ticker, side, quantity. Watchlist changes must use ticker, action."
                ),
            },
            {"role": "user", "content": json.dumps(prompt)},
        ],
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "FinAlly",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = payload["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except (KeyError, json.JSONDecodeError, TimeoutError, urllib.error.URLError):
        return build_mock_response(message, context)

    return {
        "message": str(parsed.get("message", "")) or "I reviewed the portfolio.",
        "trades": parsed.get("trades") or [],
        "watchlist_changes": parsed.get("watchlist_changes") or [],
    }


def _extract_ticker(message: str, watchlist: list[str]) -> str | None:
    tokens = [token.strip(".,:;!?()[]{}").upper() for token in message.split()]
    for token in tokens:
        if 1 <= len(token) <= 5 and token.isalpha() and token not in {"BUY", "SELL", "ADD"}:
            return token
    return watchlist[0] if watchlist else None
