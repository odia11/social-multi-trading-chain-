"""Public-only dynamic OrcAgent data for feed assistant replies.

This module is deliberately an allowlist. It may read public market/call/platform
data, but it never reads balances, portfolios, trades, bot state, messages,
notifications, referrals, wallet secrets or any other account-specific data.
"""
from __future__ import annotations

import math
import re
import sqlite3

PRIVATE_ACTION = re.compile(
    r"\b(?:show|tell|give|list|what(?:'s| is)|how much|which|toon|laat zien|"
    r"geef|wat is|hoeveel)\b",
    re.I,
)
PRIVATE_FIELD = re.compile(
    r"\b(?:portfolio|balance|saldo|holdings?|positions?|bot settings?|"
    r"stop.?loss|take.?profit|messages?|dms?|notifications?|transactions?|"
    r"(?:transaction\s+)?history|earnings?|referrals?|wallet address)\b",
    re.I,
)
PRIVATE_OWNER = re.compile(
    r"\b(?:my|mine|your|yours|their|theirs|his|her|user(?:'s)?|account(?:'s)?|"
    r"wallet(?:'s)?)\b|@[a-z0-9_]{2,32}",
    re.I,
)


def _private_request(text):
    if not PRIVATE_ACTION.search(text) or not PRIVATE_FIELD.search(text):
        return False
    if PRIVATE_OWNER.search(text):
        return True
    # These are private by nature even when the owner is only implied.
    return bool(re.search(
        r"\b(?:messages?|dms?|notifications?|(?:transaction\s+)?history|"
        r"earnings?|wallet address)\b",
        text,
        re.I,
    ))
BEST_CALL = re.compile(
    r"\b(?:best|top|beste)\s+(?:performing\s+)?call\b|"
    r"\bcall\s+(?:of|for)\s+(?:today|the day)\b|\bbeste\s+call\s+vandaag\b",
    re.I,
)
TOP_CALLS = re.compile(
    r"\b(?:top|beste)\s*(?:3|three|drie)?\s+calls\b|"
    r"\b(?:best|beste)\s+calls\b|\bcalls?\s+leaderboard\b",
    re.I,
)
WHY_BEST_CALL = re.compile(
    r"\b(?:why|waarom|reason|reasons|uitleg)\b.*\b(?:best|beste)\s+call\b|"
    r"\b(?:best|beste)\s+call\b.*\b(?:why|waarom|reason|reasons|uitleg)\b",
    re.I,
)
SHOW_BEST_CALL = re.compile(
    r"\b(?:show|laat|toon|chart|grafiek|zien|preview)\b.*\b(?:best|beste)\s+call\b|"
    r"\b(?:best|beste)\s+call\b.*\b(?:show|laat|toon|chart|grafiek|preview)\b",
    re.I,
)
MARKET_MOVERS = re.compile(
    r"\b(?:top|best|biggest|grootste)\s+(?:market\s+)?movers?\b|"
    r"\bwhat(?:'s| is)\s+trending\b|\bwat\s+is\s+trending\b",
    re.I,
)
PLATFORM_FEE = re.compile(
    r"\b(?:current|exact|actual|huidige|exacte)?\s*(?:platform\s+)?"
    r"(?:trading\s+)?fee\b",
    re.I,
)


def query(text):
    if not isinstance(text, str):
        return None
    clean = text.strip()
    if _private_request(clean):
        return {"kind": "private"}
    if TOP_CALLS.search(clean):
        return {"kind": "top_calls"}
    if BEST_CALL.search(clean):
        if WHY_BEST_CALL.search(clean):
            return {"kind": "best_call", "variant": "explain"}
        if SHOW_BEST_CALL.search(clean):
            return {"kind": "best_call", "variant": "chart"}
        return {"kind": "best_call", "variant": "simple"}
    if MARKET_MOVERS.search(clean):
        return {"kind": "market_movers"}
    if PLATFORM_FEE.search(clean):
        return {"kind": "platform_fee"}
    return None


def _finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _call_rows(db_file, limit):
    with sqlite3.connect(db_file, timeout=3) as c:
        rows = c.execute(
            """SELECT id,mint,symbol,token_name,price_at_call,peak_price,last_price,
                      timestamp,post_id
               FROM token_calls
              WHERE timestamp >= datetime('now','-1 day')
                AND price_at_call > 0
              ORDER BY (peak_price * 1.0 / price_at_call) DESC
              LIMIT ?""",
            (limit,),
        ).fetchall()
    result = []
    for row in rows:
        entry = _finite(row[4])
        peak = _finite(row[5])
        last = _finite(row[6])
        if not entry or entry <= 0 or peak is None:
            continue
        result.append({
            "id": row[0],
            "mint": row[1] or "",
            "symbol": row[2] or "?",
            "name": row[3] or "",
            "entry": entry,
            "peak": peak,
            "last": last if last and last > 0 else entry,
            "peak_multiple": peak / entry,
            "now_multiple": (last / entry) if last and last > 0 else 1.0,
            "timestamp": row[7] or "",
            "post_id": row[8],
        })
    return result


def _public_market_for_call(row, dashboard):
    mint = str(row.get("mint") or "").strip().lower()
    symbol = str(row.get("symbol") or "").strip().upper()
    for token in list(getattr(dashboard, "state", {}).get("tokens", []) or []):
        token_mint = str(token.get("mint") or token.get("address") or "").strip().lower()
        token_symbol = str(token.get("symbol") or "").strip().upper()
        if (mint and token_mint == mint) or (symbol and token_symbol == symbol):
            return {
                "volume24h": _finite(token.get("volume24h") if token.get("volume24h") is not None else token.get("volume_24h")),
                "liquidity": _finite(token.get("liquidity") if token.get("liquidity") is not None else token.get("liquidity_usd")),
                "change24h": _finite(token.get("change24h") if token.get("change24h") is not None else token.get("price_change_24h")),
            }
    return {}


def fetch(q, dashboard):
    if not q or not dashboard:
        return None
    kind = q.get("kind")
    if kind == "private":
        return {"kind": "private"}
    if kind in ("best_call", "top_calls"):
        rows = _call_rows(dashboard.DB_FILE, 1 if kind == "best_call" else 3)
        if kind == "best_call" and rows:
            rows[0].update(_public_market_for_call(rows[0], dashboard))
        return {"kind": kind, "variant": q.get("variant", "simple"), "rows": rows}
    if kind == "market_movers":
        rows = []
        for token in list(getattr(dashboard, "state", {}).get("tokens", []) or []):
            change = _finite(token.get("price_change_24h"))
            if change is None:
                continue
            rows.append({
                "symbol": str(token.get("symbol") or "?")[:20],
                "change_24h": change,
            })
        rows.sort(key=lambda row: abs(row["change_24h"]), reverse=True)
        return {"kind": kind, "rows": rows[:3]}
    if kind == "platform_fee":
        fee = _finite(getattr(dashboard, "FEE_RATE_TXN", None))
        return {"kind": kind, "fee": fee}
    return None


def _price(value):
    value = float(value)
    if value >= 1:
        return f"${value:,.4f}".rstrip("0").rstrip(".")
    fixed = f"{value:.12f}".rstrip("0").rstrip(".")
    if fixed in ("0", "-0"):
        fixed = f"{value:.8g}"
    return "$" + fixed


def _peak_percent(entry, peak):
    pct = (float(peak) / float(entry) - 1.0) * 100.0
    if abs(pct - round(pct)) < 0.05:
        return f"{int(round(pct)):+d}%"
    return f"{pct:+.1f}%"


def _money_short(value):
    value = _finite(value)
    if value is None or value <= 0:
        return ""
    if value >= 1_000_000:
        return ("$" + f"{value / 1_000_000:.1f}M").replace(".0M", "M")
    if value >= 1_000:
        return ("$" + f"{value / 1_000:.1f}K").replace(".0K", "K")
    return "$" + f"{value:,.0f}"


def _why_lines(row):
    reasons = ["Best recorded peak today (" + _peak_percent(row["entry"], row["peak"]) + ")"]
    volume = _money_short(row.get("volume24h"))
    liquidity = _money_short(row.get("liquidity"))
    change = _finite(row.get("change24h"))
    if volume:
        reasons.append("24h volume " + volume)
    if liquidity:
        reasons.append("Liquidity " + liquidity)
    if change is not None and abs(change) >= 5 and len(reasons) < 4:
        reasons.append("24h move " + f"{change:+.1f}%")
    return reasons[:4]


def render(q, snapshot):
    kind = (q or {}).get("kind")
    if kind == "private":
        return (
            "privacy",
            "I can explain where to find account data, but I never expose user-specific "
            "balances, holdings, bot settings, messages, notifications or transaction history in public replies.",
        )
    if not snapshot:
        return None
    if kind == "best_call":
        rows = snapshot.get("rows") or []
        if not rows or max((r.get("peak_multiple") or 0) for r in rows) <= 1:
            return (
                "calls_live",
                "No clear best call today.\n"
                "There is no winning public call in the last 24h yet.\n"
                "View trending: https://orcagent.fun/live-market",
            )
        row = rows[0]
        variant = (snapshot.get("variant") or q.get("variant") or "simple").lower()
        lines = [
            "Best call today: $" + str(row["symbol"]),
            "Peak: " + _peak_percent(row["entry"], row["peak"]),
            "Entry: " + _price(row["entry"]),
            "Top: " + _price(row["peak"]),
        ]
        if variant == "explain":
            lines.extend("Why: " + reason for reason in _why_lines(row))
        elif variant == "chart":
            lines.append("Chart: yes")
        lines.append("View call: https://orcagent.fun/call/" + str(row["id"]))
        return "calls_live", "\n".join(lines)[:360]
    if kind == "top_calls":
        rows = snapshot.get("rows") or []
        if not rows:
            return (
                "calls_live",
                "No clear best call today.\n"
                "There are no public calls in the last 24h yet.\n"
                "View trending: https://orcagent.fun/live-market",
            )
        lines = ["Top 3 calls today:"]
        for idx, row in enumerate(rows[:3], 1):
            lines.append(
                str(idx) + ". $" + str(row["symbol"]) + " | "
                + _peak_percent(row["entry"], row["peak"])
                + " | /call/" + str(row["id"])
            )
        lines.append("View all calls: https://orcagent.fun/calls")
        return "calls_live", "\n".join(lines)[:360]
    if kind == "market_movers":
        rows = snapshot.get("rows") or []
        if not rows:
            return "market_live", "Live public market data is temporarily unavailable. Check Live Market: https://orcagent.fun/live-market"
        summary = ", ".join(f"${r['symbol']} {r['change_24h']:+.1f}%" for r in rows)
        return "market_live", ("Top public OrcAgent market movers right now (24h change): " + summary + ". This is market data, not a recommendation.")[:240]
    if kind == "platform_fee":
        fee = snapshot.get("fee")
        if fee is None:
            return None
        return "fees_live", f"Current OrcAgent platform trading fee: {fee * 100:.3g}%. Network costs are separate and shown before confirmation."
    return None
