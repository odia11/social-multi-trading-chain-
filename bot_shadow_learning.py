"""Public-market shadow learning for the Solana auto-trading bot.

Purpose:
- observe every *public* Solana candidate that already crossed the hard +7%
  entry floor, whether a user's bot buys it or skips it;
- measure what happened afterward without risking extra capital;
- learn only conservative negative entry patterns (vetoes), never force buys;
- never change a user's take-profit, stop-loss, trade size, max positions or
  other risk settings.

The shadow model uses public token features only. It has no user_id column,
wallet address, balance, holdings, private key, DMs or account data.
"""
from __future__ import annotations

import math
import sqlite3
import threading
import time

ENTRY_TRIGGER_PCT = 7.0
HORIZON_SEC = 60 * 60
RESOLVE_GRACE_SEC = 20 * 60
EPISODE_SEC = 6 * 60 * 60
WRITE_THROTTLE_SEC = 25
VETO_REFRESH_SEC = 300
RETENTION_SEC = 45 * 86400

MIN_RESOLVED = 40
MIN_BUCKET = 15
MIN_HALF = 5
MAX_ACTIVE_VETOES = 2
NEGATIVE_AVG_PCT = -2.0
NEGATIVE_WIN_RATE = 0.35
Z_MIN = 3.2

_lock = threading.Lock()
_last_write = {}  # (mint, episode) -> ts
_veto_cache = {}  # db_file -> (computed_at, vetoes, resolved)


def _f(v):
    try:
        v = float(v)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _observed_move(token):
    vals = []
    for key in ("change5m", "change15m", "change1h",
                "price_change_5m", "price_change_15m", "price_change_1h"):
        v = _f((token or {}).get(key))
        if v is not None:
            vals.append(v)
    return max(vals) if vals else None


def _features(token, now=None):
    now = now or time.time()
    created = _f((token or {}).get("pairCreatedAt")) or 0
    buys = (_f((token or {}).get("txns_buys"))
            or _f((token or {}).get("txns24h_buys")) or 0)
    sells = (_f((token or {}).get("txns_sells"))
             or _f((token or {}).get("txns24h_sells")) or 0)
    v5 = _f((token or {}).get("volume5m")) or 0
    v1 = _f((token or {}).get("volume1h")) or 0
    return {
        "entry_score": _f((token or {}).get("score")),
        "pair_age_minutes": ((now - created / 1000) / 60) if created > 0 else None,
        "market_cap": _f((token or {}).get("market_cap")) or _f((token or {}).get("fdv")),
        "buy_sell_ratio": (buys / sells) if sells > 0 else None,
        "liquidity": _f((token or {}).get("liquidity")),
        "change5m": _f((token or {}).get("change5m")),
        "change1h": _f((token or {}).get("change1h")),
        "volume_accel": (v5 / (v1 / 12)) if v5 > 0 and v1 > 0 else None,
    }


def _ensure(conn):
    conn.executescript("""
CREATE TABLE IF NOT EXISTS bot_shadow_candidates(
 mint TEXT NOT NULL,
 episode INTEGER NOT NULL,
 symbol TEXT,
 first_seen REAL NOT NULL,
 last_seen REAL NOT NULL,
 entry_price REAL NOT NULL,
 last_price REAL NOT NULL,
 max_price REAL NOT NULL,
 min_price REAL NOT NULL,
 entry_score REAL,
 pair_age_minutes REAL,
 market_cap REAL,
 buy_sell_ratio REAL,
 liquidity REAL,
 change5m REAL,
 change1h REAL,
 volume_accel REAL,
 ret_60m REAL,
 max_gain_60m REAL,
 max_drawdown_60m REAL,
 resolved INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(mint,episode)
);
CREATE INDEX IF NOT EXISTS idx_bot_shadow_resolved ON bot_shadow_candidates(resolved,first_seen);
CREATE INDEX IF NOT EXISTS idx_bot_shadow_time ON bot_shadow_candidates(first_seen);
""")


def _episode(now):
    return int(now // EPISODE_SEC)


def _basic_observation(token):
    if not isinstance(token, dict):
        return None
    mint = str(token.get("mint") or "").strip()
    price = _f(token.get("price"))
    if not mint or not price or price <= 0:
        return None
    return mint, price


def _new_candidate_eligible(token):
    move = _observed_move(token)
    return move is not None and move >= ENTRY_TRIGGER_PCT


def _resolve_row(conn, db_file, mint, episode, first_seen, entry, hi, lo, price, now):
    hi = max(float(hi or entry), price)
    lo = min(float(lo or entry), price)
    age = now - float(first_seen)
    if age < HORIZON_SEC:
        conn.execute(
            """UPDATE bot_shadow_candidates
               SET last_seen=?,last_price=?,max_price=?,min_price=?
               WHERE mint=? AND episode=?""",
            (now, price, hi, lo, mint, episode),
        )
        return "tracking"
    if age > HORIZON_SEC + RESOLVE_GRACE_SEC:
        # Too late to call this a 60-minute outcome. Exclude instead of
        # contaminating the training set with a multi-hour return.
        conn.execute(
            """UPDATE bot_shadow_candidates
               SET last_seen=?,last_price=?,max_price=?,min_price=?,resolved=-1
               WHERE mint=? AND episode=?""",
            (now, price, hi, lo, mint, episode),
        )
        return "expired"
    ret = (price - entry) / entry * 100
    max_gain = (hi - entry) / entry * 100
    max_dd = (entry - lo) / entry * 100
    conn.execute(
        """UPDATE bot_shadow_candidates
           SET last_seen=?,last_price=?,max_price=?,min_price=?,
               ret_60m=?,max_gain_60m=?,max_drawdown_60m=?,resolved=1
           WHERE mint=? AND episode=?""",
        (now, price, hi, lo, ret, max_gain, max_dd, mint, episode),
    )
    with _lock:
        _veto_cache.pop(db_file, None)
    return "resolved"


def _observe_conn(conn, db_file, token, now):
    basic = _basic_observation(token)
    if not basic:
        return False
    mint, price = basic
    ep = _episode(now)
    cache_key = (mint, ep)
    with _lock:
        last = _last_write.get(cache_key, 0)
        if now - last < WRITE_THROTTLE_SEC:
            return True
        _last_write[cache_key] = now

    # Once a +7% setup entered the paper dataset, keep tracking it even if its
    # current momentum later falls below +7%. Otherwise losers that fade out
    # of the scanner would disappear from training and create survivor bias.
    pending = conn.execute(
        """SELECT episode,first_seen,entry_price,max_price,min_price
           FROM bot_shadow_candidates
           WHERE mint=? AND resolved=0 ORDER BY first_seen DESC LIMIT 1""",
        (mint,),
    ).fetchone()
    if pending:
        episode, first_seen, entry, hi, lo = pending
        state = _resolve_row(
            conn, db_file, mint, episode, first_seen, float(entry),
            float(hi or entry), float(lo or entry), price, now,
        )
        if state != "expired":
            return True
        # A stale old sample was excluded. The same mint may start a fresh
        # six-hour episode below only if it is currently >=+7% again.

    if not _new_candidate_eligible(token):
        return False

    existing = conn.execute(
        "SELECT 1 FROM bot_shadow_candidates WHERE mint=? AND episode=?",
        (mint, ep),
    ).fetchone()
    if existing:
        return True

    f = _features(token, now)
    conn.execute(
        """INSERT INTO bot_shadow_candidates(
 mint,episode,symbol,first_seen,last_seen,entry_price,last_price,max_price,min_price,
 entry_score,pair_age_minutes,market_cap,buy_sell_ratio,liquidity,change5m,change1h,
 volume_accel,resolved)
 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)""",
        (
            mint, ep, str(token.get("symbol") or "")[:32], now, now, price, price, price, price,
            f["entry_score"], f["pair_age_minutes"], f["market_cap"], f["buy_sell_ratio"],
            f["liquidity"], f["change5m"], f["change1h"], f["volume_accel"],
        ),
    )
    return True


def observe_many(db_file, tokens, now=None):
    """Observe a shared scanner batch in one SQLite transaction."""
    now = now or time.time()
    if not isinstance(tokens, (list, tuple)):
        return 0
    conn = sqlite3.connect(db_file, timeout=3)
    try:
        _ensure(conn)
        seen = 0
        for token in tokens:
            try:
                if _observe_conn(conn, db_file, token, now):
                    seen += 1
            except (sqlite3.Error, TypeError, ValueError):
                continue
        conn.execute("DELETE FROM bot_shadow_candidates WHERE first_seen<?", (now - RETENTION_SEC,))
        # Unresolved samples too old to represent a 60-minute outcome are
        # excluded even if they never reappear in the scanner.
        conn.execute(
            "UPDATE bot_shadow_candidates SET resolved=-1 "
            "WHERE resolved=0 AND first_seen<?",
            (now - HORIZON_SEC - RESOLVE_GRACE_SEC,),
        )
        conn.commit()
        return seen
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def observe(db_file, token, now=None):
    """Observe one public candidate (test/manual compatibility wrapper)."""
    return bool(observe_many(db_file, [token], now))


def due_mints(db_file, now=None, limit=5):
    """Unresolved candidates that need one 60m price read even if off-list."""
    now = now or time.time()
    try:
        conn = sqlite3.connect(db_file, timeout=3)
        try:
            _ensure(conn)
            conn.execute(
                "UPDATE bot_shadow_candidates SET resolved=-1 "
                "WHERE resolved=0 AND first_seen<?",
                (now - HORIZON_SEC - RESOLVE_GRACE_SEC,),
            )
            rows = conn.execute(
                """SELECT mint FROM bot_shadow_candidates
                   WHERE resolved=0 AND first_seen<=? AND first_seen>=?
                   ORDER BY first_seen ASC LIMIT ?""",
                (now - HORIZON_SEC, now - HORIZON_SEC - RESOLVE_GRACE_SEC, int(limit)),
            ).fetchall()
            conn.commit()
            return [r[0] for r in rows]
        finally:
            conn.close()
    except sqlite3.Error:
        return []


def resolve_price(db_file, mint, price, now=None):
    """Resolve/advance one already-recorded candidate from a fresh price read."""
    now = now or time.time()
    price = _f(price)
    mint = str(mint or "").strip()
    if not mint or not price or price <= 0:
        return False
    try:
        conn = sqlite3.connect(db_file, timeout=3)
        try:
            _ensure(conn)
            row = conn.execute(
                """SELECT episode,first_seen,entry_price,max_price,min_price
                   FROM bot_shadow_candidates
                   WHERE mint=? AND resolved=0 ORDER BY first_seen DESC LIMIT 1""",
                (mint,),
            ).fetchone()
            if not row:
                return False
            episode, first_seen, entry, hi, lo = row
            _resolve_row(
                conn, db_file, mint, episode, first_seen, float(entry),
                float(hi or entry), float(lo or entry), price, now,
            )
            conn.commit()
            return True
        finally:
            conn.close()
    except sqlite3.Error:
        return False


BUCKETS = {
    "score": [
        (0, 6, "entry score under 6"),
        (6, 7, "entry score 6-7"),
        (7, 8, "entry score 7-8"),
        (8, 11, "entry score 8+"),
    ],
    "age": [
        (0, 15, "token under 15 min old"),
        (15, 60, "token 15-60 min old"),
        (60, 360, "token 1-6 h old"),
        (360, 1440, "token 6-24 h old"),
        (1440, float("inf"), "token over a day old"),
    ],
    "mcap": [
        (0, 100e3, "market cap under $100K"),
        (100e3, 500e3, "market cap $100K-$500K"),
        (500e3, 2e6, "market cap $500K-$2M"),
        (2e6, 10e6, "market cap $2M-$10M"),
        (10e6, float("inf"), "market cap over $10M"),
    ],
    "bsr": [
        (0, 0.8, "more sells than buys"),
        (0.8, 1.2, "balanced buys and sells"),
        (1.2, 2.0, "more buys than sells"),
        (2.0, float("inf"), "buys over 2x sells"),
    ],
    "liq": [
        (0, 25e3, "liquidity under $25K"),
        (25e3, 100e3, "liquidity $25K-$100K"),
        (100e3, 500e3, "liquidity $100K-$500K"),
        (500e3, float("inf"), "liquidity over $500K"),
    ],
    "momentum": [
        (7, 10, "momentum 7-10%"),
        (10, 20, "momentum 10-20%"),
        (20, 35, "momentum 20-35%"),
        (35, 50, "momentum 35-50%"),
        (50, float("inf"), "momentum 50%+"),
    ],
    "volaccel": [
        (0, 0.8, "volume slowing"),
        (0.8, 1.5, "volume steady"),
        (1.5, float("inf"), "volume accelerating"),
    ],
}


def _bucket(dim, value):
    if value is None:
        return None
    for lo, hi, label in BUCKETS[dim]:
        if lo <= value < hi:
            return label
    return None


def _row_buckets(row):
    score, age, mcap, bsr, liq, m5, h1, accel = row
    momentum = max(v for v in (m5, h1) if v is not None) if (m5 is not None or h1 is not None) else None
    vals = {
        "score": score,
        "age": age,
        "mcap": mcap,
        "bsr": bsr,
        "liq": liq,
        "momentum": momentum,
        "volaccel": accel,
    }
    return {(dim, _bucket(dim, value)) for dim, value in vals.items() if _bucket(dim, value)}


def _z_worse(inside, outside):
    if len(inside) < 2 or len(outside) < 2:
        return 0.0
    vals = inside + outside
    mean = sum(vals) / len(vals)
    sd = math.sqrt(sum((x - mean) ** 2 for x in vals) / (len(vals) - 1))
    if sd <= 0:
        return 0.0
    a = sum(inside) / len(inside)
    b = sum(outside) / len(outside)
    return (b - a) / (sd * math.sqrt(1 / len(inside) + 1 / len(outside)))


def _learned_vetoes(conn):
    rows = conn.execute(
        """SELECT first_seen,ret_60m,entry_score,pair_age_minutes,market_cap,
                  buy_sell_ratio,liquidity,change5m,change1h,volume_accel
           FROM bot_shadow_candidates
           WHERE resolved=1 AND ret_60m IS NOT NULL
           ORDER BY first_seen ASC"""
    ).fetchall()
    if len(rows) < MIN_RESOLVED:
        return [], len(rows)

    samples = []
    for first_seen, ret, score, age, mcap, bsr, liq, m5, h1, accel in rows:
        samples.append({
            "ts": first_seen,
            "ret": float(ret),
            "buckets": _row_buckets((score, age, mcap, bsr, liq, m5, h1, accel)),
        })

    keys = set().union(*(s["buckets"] for s in samples))
    bad = []
    for key in keys:
        inside = [s for s in samples if key in s["buckets"]]
        outside = [s for s in samples if key not in s["buckets"]]
        if len(inside) < MIN_BUCKET or len(outside) < MIN_BUCKET:
            continue
        rets = [s["ret"] for s in inside]
        avg = sum(rets) / len(rets)
        win = sum(1 for x in rets if x > 0) / len(rets)
        mid = len(inside) // 2
        older, newer = inside[:mid], inside[mid:]
        if len(older) < MIN_HALF or len(newer) < MIN_HALF:
            continue
        old_avg = sum(s["ret"] for s in older) / len(older)
        new_avg = sum(s["ret"] for s in newer) / len(newer)
        z = _z_worse(rets, [s["ret"] for s in outside])
        if avg <= NEGATIVE_AVG_PCT and win <= NEGATIVE_WIN_RATE and old_avg < 0 and new_avg < 0 and z >= Z_MIN:
            bad.append({
                "dim": key[0],
                "label": key[1],
                "n": len(inside),
                "avg": round(avg, 1),
                "win_rate": round(win * 100, 1),
                "z": round(z, 2),
            })
    bad.sort(key=lambda x: (x["avg"], -x["n"]))
    return bad[:MAX_ACTIVE_VETOES], len(rows)


def _cached_vetoes(db_file):
    now = time.time()
    with _lock:
        hit = _veto_cache.get(db_file)
        if hit and now - hit[0] < VETO_REFRESH_SEC:
            return hit[1], hit[2]
    try:
        conn = sqlite3.connect(db_file, timeout=3)
        try:
            _ensure(conn)
            vetoes, resolved = _learned_vetoes(conn)
        finally:
            conn.close()
    except sqlite3.Error:
        return [], 0
    with _lock:
        _veto_cache[db_file] = (now, vetoes, resolved)
    return vetoes, resolved


def veto_reason(db_file, token):
    """Strong public-market negative pattern for this candidate, or ''.

    This function can only veto. It never approves a candidate or weakens any
    existing safety/user rule.
    """
    vetoes, _ = _cached_vetoes(db_file)
    f = _features(token)
    row_buckets = _row_buckets((
        f["entry_score"], f["pair_age_minutes"], f["market_cap"], f["buy_sell_ratio"],
        f["liquidity"], f["change5m"], f["change1h"], f["volume_accel"],
    ))
    for item in vetoes:
        if (item["dim"], item["label"]) in row_buckets:
            return item["label"]
    return ""


def status(db_file):
    vetoes, resolved = _cached_vetoes(db_file)
    try:
        conn = sqlite3.connect(db_file, timeout=3)
        try:
            _ensure(conn)
            observed = conn.execute("SELECT COUNT(*) FROM bot_shadow_candidates").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error:
        return {"observed": 0, "resolved": 0, "needs": MIN_RESOLVED, "ready": False, "avoid": []}
    return {
        "observed": int(observed),
        "resolved": int(resolved),
        "needs": MIN_RESOLVED,
        "ready": resolved >= MIN_RESOLVED,
        "avoid": [v["label"] for v in vetoes],
        "details": vetoes,
    }
