"""Keep the one long-lived app process lean.

OrcAgent runs as a single gunicorn worker that stays up for days, with the
trading loops inside it. A handful of per-token and per-user caches only
ever add entries: every mint the scanner checks, every position the exit
guardian has looked at, every wallet that logged in. Each entry is small and
each cache honours its own short TTL on read, but nothing ever removed an
expired entry, so they grew for as long as the process lived.

Every few minutes this drops entries that are far past their TTL (a later
read would refetch them anyway), then asks glibc to hand freed heap pages
back to the OS. With many threads, Python's freed memory otherwise stays
parked in malloc arenas and the process RSS only goes up; the service also
sets MALLOC_ARENA_MAX=2 for the same reason (deploy/orcagent.service).

Nothing here changes what a cache returns: an entry is removed only when it
is older than its TTL many times over, and only if it was not replaced in
the meantime.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import threading
import time

INTERVAL = 600  # seconds between passes

# (cache, how to read an entry's timestamp, drop after this many seconds,
#  the lock the owning code holds while writing it, or None)
# Each max age is far above the TTL the owning code reads it with.
_TTL_CACHES = (
    ('_scanner_safety_cache', 'first', 3600, '_scanner_safety_lock'),  # TTL 600 s
    ('_realizable_cache', 'first', 600, '_realizable_lock'),            # TTL 5 s
    ('_AI_TRADE_GATE_CACHE', 'ts', 600, None),                           # TTL 30 s
    ('_guardian_settings_cache', 'first', 600, None),                   # TTL 10 s
    ('_wallet_ips', 'newest', 3600, '_wallet_ips_lock'),               # 1 h window
)

# Decimals never change, so these entries never expire; only cap the count.
_CAPPED = (('_token_decimals_cache', 20000),)


def _stamp(value, how):
    try:
        if how == 'first':
            return float(value[0])
        if how == 'ts':
            return float(value['ts'])
        if how == 'newest':
            return max((float(ts) for _, ts in value), default=0.0)
    except Exception:
        return None
    return None


class _NoLock:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _prune_ttl(d, cache, how, max_age, lock, now):
    removed = 0
    with lock or _NoLock():
        for key, value in list(cache.items()):
            ts = _stamp(value, how)
            if ts is None or now - ts <= max_age:
                continue
            # Only if nobody refreshed it while we looked.
            if cache.get(key) is value:
                cache.pop(key, None)
                removed += 1
    return removed


def _prune_exit_token_data(d, now, max_age=3600):
    """_exit_td_cache and _exit_td_at are one cache in two dicts (data and
    when it was read). A mint nobody asked about for an hour is no longer
    held; its next read just refetches."""
    data = getattr(d, '_exit_td_cache', None)
    at = getattr(d, '_exit_td_at', None)
    lock = getattr(d, '_exit_td_lock', None)
    inflight = getattr(d, '_exit_td_inflight', set())
    if not isinstance(data, dict) or not isinstance(at, dict) or lock is None:
        return 0
    removed = 0
    with lock:
        for mint, ts in list(at.items()):
            if mint in inflight or now - ts <= max_age:
                continue
            at.pop(mint, None)
            data.pop(mint, None)
            removed += 1
        # Data without a timestamp can only be a leftover.
        for mint in [m for m in list(data) if m not in at and m not in inflight]:
            data.pop(mint, None)
            removed += 1
    return removed


def prune(d, now=None) -> int:
    """One pass over every known growing cache. Returns entries removed."""
    now = time.time() if now is None else now
    removed = 0
    for name, how, max_age, lock_name in _TTL_CACHES:
        cache = getattr(d, name, None)
        if not isinstance(cache, dict):
            continue
        lock = getattr(d, lock_name, None) if lock_name else None
        try:
            removed += _prune_ttl(d, cache, how, max_age, lock, now)
        except Exception as exc:
            print(f'[memory] pruning {name} failed: {exc}', flush=True)
    try:
        removed += _prune_exit_token_data(d, now)
    except Exception as exc:
        print(f'[memory] pruning exit token data failed: {exc}', flush=True)
    for name, cap in _CAPPED:
        cache = getattr(d, name, None)
        if isinstance(cache, dict) and len(cache) > cap:
            removed += len(cache)
            cache.clear()
    return removed


_libc = None


def release_free_memory() -> bool:
    """Return freed heap pages to the OS (glibc only; a no-op elsewhere)."""
    global _libc
    try:
        if _libc is None:
            _libc = ctypes.CDLL(ctypes.util.find_library('c') or 'libc.so.6')
        return bool(_libc.malloc_trim(0))
    except Exception:
        return False


def rss_mb() -> int:
    try:
        with open('/proc/self/status') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass
    return 0


def install(dashboard_module):
    app = dashboard_module.app
    if getattr(app, '_orca_memory_hygiene_installed', False):
        return
    app._orca_memory_hygiene_installed = True

    def loop():
        while True:
            time.sleep(INTERVAL)
            try:
                before = rss_mb()
                removed = prune(dashboard_module)
                release_free_memory()
                print(f'[memory] removed {removed} expired cache entries; '
                      f'rss {before} -> {rss_mb()} MB', flush=True)
            except Exception as exc:
                print(f'[memory] pass failed: {exc}', flush=True)

    threading.Thread(target=loop, name='orca-memory-hygiene', daemon=True).start()
